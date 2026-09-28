"""Offline diagnostics for score-neutral criterion evaluations."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from forge.evaluate.batch import CriterionEvaluationBatch, verify_evaluation_batch
from forge.service import (
    build_legacy_criterion_evaluations,
    prepare_assessment,
)
from forge.extract.batch import ExtractionBatch, verify_extraction_batch


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DiagnosticCallMetadata(StrictModel):
    run_index: int = Field(ge=1)
    batch_id: str = Field(min_length=1)
    criterion_id: str = Field(min_length=1)
    model: str | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class EvaluationDiagnosticCase(StrictModel):
    case_id: str = Field(min_length=1)
    source_kind: Literal["internal", "authored_regression", "public", "synthetic"]
    source_path: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rubric_name: str = "prd"
    rubric_version: str
    native: CriterionEvaluationBatch
    legacy_extraction_json: str | None = None
    calls: list[DiagnosticCallMetadata] = Field(default_factory=list)


class EvaluationDiagnosticSuite(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    artifact_type: Literal["forge.criterion_evaluation_diagnostics.v1"] = (
        "forge.criterion_evaluation_diagnostics.v1"
    )
    calibration_eligible: Literal[False] = False
    score_effect: Literal["none"] = "none"
    cases: list[EvaluationDiagnosticCase] = Field(min_length=1)


class Rate(StrictModel):
    matched: int
    total: int
    rate: float | None


class EvidenceMetrics(StrictModel):
    submitted_references: int
    verified_references: int
    unique_verified_spans: int
    duplicate_references: int
    duplicate_rate: float | None


class CallMetadataReport(StrictModel):
    call_count: int
    calls_with_latency: int
    latency_ms_total: int | None
    latency_ms_mean: float | None
    calls_with_tokens: int
    input_tokens_total: int | None
    output_tokens_total: int | None


class NativeLegacyComparison(StrictModel):
    paired_criteria: int
    exact_status_agreement: int
    agreement_rate: float | None
    matrix: dict[str, dict[str, int]]
    note: str = (
        "Symmetric shadow comparison; legacy extraction is not ground truth."
    )


class CriterionStatusMismatch(StrictModel):
    criterion_id: str
    native_status: str
    legacy_status: str


class EvaluationCaseReport(StrictModel):
    case_id: str
    source_kind: str
    status_counts: dict[str, int]
    abstention: Rate
    full_run_agreement: Rate
    assertion_full_agreement: Rate
    evidence: EvidenceMetrics
    run_disagreement_criteria: list[str]
    criterion_run_statuses: dict[str, list[str]]
    native_legacy_mismatches: list[CriterionStatusMismatch]


class EvaluationDiagnosticReport(StrictModel):
    artifact_type: Literal["forge.criterion_evaluation_diagnostic_report.v1"] = (
        "forge.criterion_evaluation_diagnostic_report.v1"
    )
    calibration_eligible: Literal[False] = False
    score_effect: Literal["none"] = "none"
    case_count: int
    source_counts: dict[str, int]
    status_counts: dict[str, int]
    abstention: Rate
    full_run_agreement: Rate
    assertion_full_agreement: Rate
    evidence: EvidenceMetrics
    call_metadata: CallMetadataReport
    native_legacy_comparison: NativeLegacyComparison
    cases: list[EvaluationCaseReport]
    warnings: list[str]


def _rate(matched: int, total: int) -> Rate:
    return Rate(
        matched=matched,
        total=total,
        rate=round(matched / total, 4) if total else None,
    )


def _source(root: Path, source_path: str) -> Path:
    candidate = (root / source_path).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError("diagnostic source_path must stay within workspace_root")
    if not candidate.is_file():
        raise FileNotFoundError(f"diagnostic source not found: {candidate}")
    return candidate


def _submitted_evidence(case: EvaluationDiagnosticCase) -> tuple[int, int]:
    submitted = duplicates = 0
    for run in case.native.runs:
        seen: set[tuple[object, ...]] = set()
        for fragment in run.fragments:
            for criterion in fragment.criteria:
                for reference in criterion.evidence:
                    submitted += 1
                    identity = (
                        criterion.criterion_id,
                        reference.source_block_id,
                        reference.quote,
                        reference.quote_start_char,
                        reference.quote_end_char,
                    )
                    if identity in seen:
                        duplicates += 1
                    seen.add(identity)
    return submitted, duplicates


def evaluate_diagnostics(
    suite: EvaluationDiagnosticSuite, *, workspace_root: Path
) -> EvaluationDiagnosticReport:
    if len({case.case_id for case in suite.cases}) != len(suite.cases):
        raise ValueError("diagnostic suite contains duplicate case ids")
    case_reports: list[EvaluationCaseReport] = []
    status_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    unclear = evaluated = full_agreement = compared_agreement = 0
    assertion_full_agreement = assertion_compared = 0
    submitted_total = duplicate_total = verified_total = 0
    unique_evidence: set[tuple[str, str]] = set()
    comparison_matrix: dict[str, Counter[str]] = {}
    paired = exact = 0
    all_calls: list[DiagnosticCallMetadata] = []

    for case in suite.cases:
        source = _source(workspace_root, case.source_path)
        actual_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        if actual_hash != case.source_sha256:
            raise ValueError(f"case {case.case_id} source SHA-256 changed")
        prepared = prepare_assessment(str(source), case.rubric_name)
        if prepared.rubric.version != case.rubric_version:
            raise ValueError(f"case {case.case_id} rubric version changed")
        verified = verify_evaluation_batch(prepared, case.native)
        native_by_criterion = {
            item.criterion_id: item for item in verified.consolidated
        }
        run_statuses: dict[str, list[str]] = {}
        for artifact in verified.artifacts:
            run_statuses.setdefault(artifact.criterion_id, []).append(
                artifact.status.value
            )
        counts = Counter(item.status.value for item in verified.consolidated)
        status_counts.update(counts)
        source_counts[case.source_kind] += 1
        case_unclear = counts["unclear"]
        case_evaluated = len(verified.consolidated)
        case_full = sum(
            len(set(statuses)) == 1 for statuses in run_statuses.values()
        )
        case_assertion_outcomes = [
            outcome
            for item in verified.consolidated
            for outcome in item.assertion_outcomes
        ]
        case_assertion_full = sum(
            outcome.agreement == 1.0 for outcome in case_assertion_outcomes
        )
        unclear += case_unclear
        evaluated += case_evaluated
        full_agreement += case_full
        compared_agreement += case_evaluated
        assertion_full_agreement += case_assertion_full
        assertion_compared += len(case_assertion_outcomes)
        submitted, duplicates = _submitted_evidence(case)
        submitted_total += submitted
        duplicate_total += duplicates
        case_evidence = [
            span for item in verified.artifacts for span in item.evidence
        ]
        verified_total += len(case_evidence)
        case_unique = {
            (span.snapshot_id, span.evidence_id) for span in case_evidence
        }
        unique_evidence.update(case_unique)

        case_mismatches: list[CriterionStatusMismatch] = []
        if case.legacy_extraction_json is not None:
            legacy_payload = json.loads(case.legacy_extraction_json)
            if "runs" not in legacy_payload:
                legacy_payload = {"runs": [legacy_payload]}
            legacy_batch = ExtractionBatch.model_validate(legacy_payload)
            legacy_runs = verify_extraction_batch(
                list(prepared.batches), legacy_batch, prepared.rubric
            )
            _, legacy = build_legacy_criterion_evaluations(prepared, legacy_runs)
            for legacy_item in legacy:
                native_item = native_by_criterion.get(legacy_item.criterion_id)
                if native_item is None:
                    continue
                native_status = native_item.status.value
                legacy_status = legacy_item.status.value
                comparison_matrix.setdefault(native_status, Counter())[legacy_status] += 1
                paired += 1
                exact += native_status == legacy_status
                if native_status != legacy_status:
                    case_mismatches.append(
                        CriterionStatusMismatch(
                            criterion_id=legacy_item.criterion_id,
                            native_status=native_status,
                            legacy_status=legacy_status,
                        )
                    )

        case_reports.append(
            EvaluationCaseReport(
                case_id=case.case_id,
                source_kind=case.source_kind,
                status_counts=dict(sorted(counts.items())),
                abstention=_rate(case_unclear, case_evaluated),
                full_run_agreement=_rate(case_full, case_evaluated),
                assertion_full_agreement=_rate(
                    case_assertion_full, len(case_assertion_outcomes)
                ),
                evidence=EvidenceMetrics(
                    submitted_references=submitted,
                    verified_references=len(case_evidence),
                    unique_verified_spans=len(case_unique),
                    duplicate_references=duplicates,
                    duplicate_rate=(
                        round(duplicates / submitted, 4) if submitted else None
                    ),
                ),
                run_disagreement_criteria=sorted(
                    criterion_id
                    for criterion_id, statuses in run_statuses.items()
                    if len(set(statuses)) > 1
                ),
                criterion_run_statuses={
                    criterion_id: statuses
                    for criterion_id, statuses in sorted(run_statuses.items())
                },
                native_legacy_mismatches=sorted(
                    case_mismatches, key=lambda item: item.criterion_id
                ),
            )
        )
        all_calls.extend(case.calls)

    latencies = [call.latency_ms for call in all_calls if call.latency_ms is not None]
    token_calls = [
        call
        for call in all_calls
        if call.input_tokens is not None or call.output_tokens is not None
    ]
    warnings = [
        "Diagnostic-only shadow artifact; it cannot establish calibration, accuracy, or organization validity."
    ]
    if not any(case.source_kind == "internal" for case in suite.cases):
        warnings.append("No internal cases were supplied.")
    return EvaluationDiagnosticReport(
        case_count=len(suite.cases),
        source_counts=dict(sorted(source_counts.items())),
        status_counts=dict(sorted(status_counts.items())),
        abstention=_rate(unclear, evaluated),
        full_run_agreement=_rate(full_agreement, compared_agreement),
        assertion_full_agreement=_rate(
            assertion_full_agreement, assertion_compared
        ),
        evidence=EvidenceMetrics(
            submitted_references=submitted_total,
            verified_references=verified_total,
            unique_verified_spans=len(unique_evidence),
            duplicate_references=duplicate_total,
            duplicate_rate=(
                round(duplicate_total / submitted_total, 4)
                if submitted_total
                else None
            ),
        ),
        call_metadata=CallMetadataReport(
            call_count=len(all_calls),
            calls_with_latency=len(latencies),
            latency_ms_total=sum(latencies) if latencies else None,
            latency_ms_mean=(
                round(sum(latencies) / len(latencies), 4) if latencies else None
            ),
            calls_with_tokens=len(token_calls),
            input_tokens_total=(
                sum(call.input_tokens or 0 for call in token_calls)
                if token_calls
                else None
            ),
            output_tokens_total=(
                sum(call.output_tokens or 0 for call in token_calls)
                if token_calls
                else None
            ),
        ),
        native_legacy_comparison=NativeLegacyComparison(
            paired_criteria=paired,
            exact_status_agreement=exact,
            agreement_rate=round(exact / paired, 4) if paired else None,
            matrix={
                native: dict(sorted(values.items()))
                for native, values in sorted(comparison_matrix.items())
            },
        ),
        cases=case_reports,
        warnings=warnings,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure score-neutral criterion evaluation shadow artifacts."
    )
    parser.add_argument("suite", type=Path)
    parser.add_argument("--workspace-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    suite = EvaluationDiagnosticSuite.model_validate_json(args.suite.read_text())
    report = evaluate_diagnostics(suite, workspace_root=args.workspace_root.resolve())
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
