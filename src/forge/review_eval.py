"""Offline measurement of deep-review findings against human labels.

D-045 and D-046 both keep findings advisory until their precision, recall, and
false-positive rate are measured. This module is that measurement: a developer
workflow, never an MCP tool, and never something the review loop can consult.

The asymmetry that matters is deliberate. Telling an author their document
contradicts itself when it does not destroys trust in every other finding, so
false positives are reported per case rather than averaged away, and an expected
finding only enters headline recall when a strict majority of reviewers recorded
it. Contested items are surfaced, not resolved in Forge's favour.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from forge.deep_review import DeepReviewFinding, DeepReviewReport

# Reviewers describe a defect by quoting the document, not by guessing Forge's
# internal identifiers. Matching therefore happens on verified evidence text.
class ExpectedFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_id: str = Field(min_length=1)
    # None means "any finding kind is acceptable"; reviewers should not be
    # forced to learn Forge's taxonomy before they can report a real defect.
    kind: str | None = None
    quote_fragments: list[str] = Field(min_length=1)
    note: str | None = None
    # A blocker is a defect the reviewer believes stops implementation. Recall
    # is reported separately for blockers because missing one is worse than
    # missing a minor inconsistency.
    blocker: bool = True


class GoldenLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str = Field(min_length=1)
    reviewer_id: str = Field(min_length=1)
    source_ref: str | None = None
    expected: list[ExpectedFinding] = Field(default_factory=list)
    note: str | None = None


class GoldenCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str = Field(min_length=1)
    source_kind: Literal["internal", "public", "synthetic"] = "internal"
    source_ref: str | None = None
    study_split: Literal["development", "holdout"] = "development"
    predicted: DeepReviewReport
    labels: list[GoldenLabel] = Field(default_factory=list)


class GoldenSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cases: list[GoldenCase] = Field(min_length=1)


class MatchRate(BaseModel):
    matched: int
    total: int
    rate: float | None


class CaseReport(BaseModel):
    case_id: str
    source_kind: str
    study_split: str
    reviewer_count: int
    consensus_expected: int
    contested_expected: int
    precision: MatchRate
    recall: MatchRate
    blocker_recall: MatchRate
    false_positives: list[str]
    missed: list[str]
    duplicate_findings: list[str]
    findings_without_evidence: list[str]


class ReviewEvalReport(BaseModel):
    case_count: int
    scored_case_count: int
    source_counts: dict[str, int]
    split_counts: dict[str, int]
    precision: MatchRate
    recall: MatchRate
    blocker_recall: MatchRate
    false_positives_per_case: float | None
    duplicate_rate: float | None
    evidence_completeness: MatchRate
    human_quote_alignment: MatchRate
    inter_reviewer_agreement: MatchRate
    contested_expected: int
    by_kind: dict[str, dict[str, MatchRate]]
    cases: list[CaseReport]
    warnings: list[str]


class ReviewEvalThresholds(BaseModel):
    minimum_scored_cases: int = Field(default=5, ge=1)
    minimum_precision: float = Field(default=0.8, ge=0, le=1)
    minimum_blocker_recall: float = Field(default=0.6, ge=0, le=1)
    maximum_false_positives_per_case: float = Field(default=1.0, ge=0)
    minimum_inter_reviewer_agreement: float = Field(default=0.6, ge=0, le=1)


class ReviewEvalDecision(BaseModel):
    passed: bool
    checks: dict[str, bool]
    blockers: list[str]


def make_label_template(
    case_id: str, reviewer_id: str, source_ref: str | None = None
) -> GoldenLabel:
    """Create a blinded sheet.

    It deliberately contains no Forge output. A reviewer who has already seen
    the predicted findings cannot produce an independent label, which is the
    same anchoring problem `forge.calibration` avoids.
    """
    return GoldenLabel(
        case_id=case_id,
        reviewer_id=reviewer_id,
        source_ref=source_ref,
        expected=[
            ExpectedFinding(
                expected_id=f"{case_id}-1",
                kind=None,
                quote_fragments=["<paste the exact conflicting text here>"],
                note=(
                    "Describe what a team cannot implement. Add one entry per "
                    "defect, quoting each statement involved. Delete this row "
                    "if the document has no such defect."
                ),
            )
        ],
    )


def evaluate_review(suite: GoldenSuite) -> ReviewEvalReport:
    """Compare predicted findings with consensus human labels."""
    _validate_suite(suite)
    cases: list[CaseReport] = []
    warnings: list[str] = []
    kind_totals: dict[str, dict[str, list[int]]] = {}

    matched_total = predicted_total = expected_total = 0
    blocker_matched = blocker_total = 0
    false_positive_total = duplicate_total = 0
    evidence_ok = evidence_total = 0
    quote_aligned = quote_total = 0
    agreement_matched = agreement_total = 0
    contested_total = 0

    for case in suite.cases:
        consensus, contested = _consensus(case.labels)
        contested_total += len(contested)
        findings = case.predicted.findings
        matches = _match(findings, consensus)
        quote_matches = _match(findings, consensus, require_kind=False)

        matched_ids = {finding.finding_id for finding, _ in matches}
        matched_expected = {expected.expected_id for _, expected in matches}
        false_positives = sorted(
            finding.finding_id for finding in findings
            if finding.finding_id not in matched_ids
        )
        missed = sorted(
            expected.expected_id for expected in consensus
            if expected.expected_id not in matched_expected
        )
        duplicates = _duplicates(findings)
        no_evidence = sorted(
            finding.finding_id
            for finding in findings
            if not finding.evidence or any(
                not item.quote.strip() for item in finding.evidence
            )
        )

        blockers = [item for item in consensus if item.blocker]
        blocker_hits = sum(
            1 for item in blockers if item.expected_id in matched_expected
        )

        scored = len(case.labels) >= 2
        if not scored:
            warnings.append(
                f"case {case.case_id} has fewer than two reviewer labels and "
                "is excluded from headline precision and recall"
            )
        if case.source_kind != "internal":
            warnings.append(
                f"case {case.case_id} is {case.source_kind}; it is reported "
                "but excluded from headline metrics"
            )

        headline = scored and case.source_kind == "internal"
        if headline:
            matched_total += len(matches)
            predicted_total += len(findings)
            expected_total += len(consensus)
            blocker_matched += blocker_hits
            blocker_total += len(blockers)
            false_positive_total += len(false_positives)
            duplicate_total += len(duplicates)
            evidence_ok += len(findings) - len(no_evidence)
            evidence_total += len(findings)
            quote_aligned += len(quote_matches)
            quote_total += len(findings)
            for finding, _ in matches:
                kind_totals.setdefault(
                    finding.kind, {"matched": [], "predicted": [], "expected": []}
                )["matched"].append(1)
            for finding in findings:
                kind_totals.setdefault(
                    finding.kind, {"matched": [], "predicted": [], "expected": []}
                )["predicted"].append(1)
            for expected in consensus:
                if expected.kind is not None:
                    kind_totals.setdefault(
                        expected.kind,
                        {"matched": [], "predicted": [], "expected": []},
                    )["expected"].append(1)
            hits, total = _label_agreement(case.labels)
            agreement_matched += hits
            agreement_total += total

        cases.append(
            CaseReport(
                case_id=case.case_id,
                source_kind=case.source_kind,
                study_split=case.study_split,
                reviewer_count=len(case.labels),
                consensus_expected=len(consensus),
                contested_expected=len(contested),
                precision=_rate(len(matches), len(findings)),
                recall=_rate(len(matches), len(consensus)),
                blocker_recall=_rate(blocker_hits, len(blockers)),
                false_positives=false_positives,
                missed=missed,
                duplicate_findings=duplicates,
                findings_without_evidence=no_evidence,
            )
        )

    scored_cases = sum(
        1
        for case in suite.cases
        if len(case.labels) >= 2 and case.source_kind == "internal"
    )
    if scored_cases == 0:
        warnings.append(
            "no internal labelled cases: precision and recall are undefined and "
            "this suite cannot support any accuracy claim"
        )

    return ReviewEvalReport(
        case_count=len(suite.cases),
        scored_case_count=scored_cases,
        source_counts=dict(Counter(case.source_kind for case in suite.cases)),
        split_counts=dict(Counter(case.study_split for case in suite.cases)),
        precision=_rate(matched_total, predicted_total),
        recall=_rate(matched_total, expected_total),
        blocker_recall=_rate(blocker_matched, blocker_total),
        false_positives_per_case=(
            round(false_positive_total / scored_cases, 4) if scored_cases else None
        ),
        duplicate_rate=(
            round(duplicate_total / predicted_total, 4) if predicted_total else None
        ),
        evidence_completeness=_rate(evidence_ok, evidence_total),
        human_quote_alignment=_rate(quote_aligned, quote_total),
        inter_reviewer_agreement=_rate(agreement_matched, agreement_total),
        contested_expected=contested_total,
        by_kind={
            kind: {
                "precision": _rate(
                    len(values["matched"]), len(values["predicted"])
                ),
                "recall": _rate(
                    len(values["matched"]), len(values["expected"])
                ),
            }
            for kind, values in sorted(kind_totals.items())
        },
        cases=cases,
        warnings=warnings,
    )


def evaluate_thresholds(
    report: ReviewEvalReport, thresholds: ReviewEvalThresholds
) -> ReviewEvalDecision:
    """Apply preregistered thresholds without renegotiating them."""
    checks = {
        "scored_cases": report.scored_case_count >= thresholds.minimum_scored_cases,
        "precision": (
            report.precision.rate is not None
            and report.precision.rate >= thresholds.minimum_precision
        ),
        "blocker_recall": (
            report.blocker_recall.rate is not None
            and report.blocker_recall.rate >= thresholds.minimum_blocker_recall
        ),
        "false_positives_per_case": (
            report.false_positives_per_case is not None
            and report.false_positives_per_case
            <= thresholds.maximum_false_positives_per_case
        ),
        "inter_reviewer_agreement": (
            report.inter_reviewer_agreement.rate is not None
            and report.inter_reviewer_agreement.rate
            >= thresholds.minimum_inter_reviewer_agreement
        ),
    }
    return ReviewEvalDecision(
        passed=all(checks.values()),
        checks=checks,
        blockers=sorted(name for name, ok in checks.items() if not ok),
    )


def holdout_only(suite: GoldenSuite) -> GoldenSuite:
    cases = [case for case in suite.cases if case.study_split == "holdout"]
    if not cases:
        raise ValueError("suite contains no holdout cases")
    return GoldenSuite(cases=cases)


def merge_labels(suite: GoldenSuite, sheets: list[GoldenLabel]) -> GoldenSuite:
    """Attach completed sheets to predictions after review is finished."""
    labels: dict[str, list[GoldenLabel]] = {}
    for sheet in sheets:
        labels.setdefault(sheet.case_id, []).append(sheet)
    unknown = sorted(set(labels) - {case.case_id for case in suite.cases})
    if unknown:
        raise ValueError("labels reference unknown cases: " + ", ".join(unknown))
    merged = GoldenSuite(
        cases=[
            case.model_copy(
                update={"labels": case.labels + labels.get(case.case_id, [])}
            )
            for case in suite.cases
        ]
    )
    _validate_suite(merged)
    return merged


def _consensus(
    labels: list[GoldenLabel],
) -> tuple[list[ExpectedFinding], list[ExpectedFinding]]:
    """Keep expected findings a strict majority of reviewers recorded."""
    if not labels:
        return [], []
    seen: dict[str, tuple[ExpectedFinding, int]] = {}
    for label in labels:
        for expected in label.expected:
            key = _key(expected)
            found, count = seen.get(key, (expected, 0))
            seen[key] = (found, count + 1)
    consensus: list[ExpectedFinding] = []
    contested: list[ExpectedFinding] = []
    for expected, count in seen.values():
        if count * 2 > len(labels):
            consensus.append(expected)
        else:
            contested.append(expected)
    return (
        sorted(consensus, key=lambda item: item.expected_id),
        sorted(contested, key=lambda item: item.expected_id),
    )


def _match(
    findings: list[DeepReviewFinding],
    expected: list[ExpectedFinding],
    *,
    require_kind: bool = True,
) -> list[tuple[DeepReviewFinding, ExpectedFinding]]:
    """Greedy one-to-one matching on normalized evidence text."""
    matches: list[tuple[DeepReviewFinding, ExpectedFinding]] = []
    used: set[str] = set()
    for item in sorted(expected, key=lambda value: value.expected_id):
        for finding in sorted(findings, key=lambda value: value.finding_id):
            if finding.finding_id in used:
                continue
            if require_kind and item.kind is not None and finding.kind != item.kind:
                continue
            haystack = _normalize(
                " ".join(evidence.quote for evidence in finding.evidence)
            )
            if all(
                _normalize(fragment) in haystack
                for fragment in item.quote_fragments
            ):
                matches.append((finding, item))
                used.add(finding.finding_id)
                break
    return matches


def _duplicates(findings: list[DeepReviewFinding]) -> list[str]:
    seen: dict[tuple[str, str], str] = {}
    duplicates: list[str] = []
    for finding in sorted(findings, key=lambda value: value.finding_id):
        key = (
            finding.kind,
            _normalize(" ".join(item.quote for item in finding.evidence)),
        )
        if key in seen:
            duplicates.append(finding.finding_id)
        else:
            seen[key] = finding.finding_id
    return duplicates


def _label_agreement(labels: list[GoldenLabel]) -> tuple[int, int]:
    """How often reviewers independently recorded the same defect."""
    if len(labels) < 2:
        return 0, 0
    keys = [{_key(item) for item in label.expected} for label in labels]
    union = set().union(*keys)
    if not union:
        return 0, 0
    agreed = sum(1 for key in union if all(key in group for group in keys))
    return agreed, len(union)


def _validate_suite(suite: GoldenSuite) -> None:
    case_ids = [case.case_id for case in suite.cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("golden suite contains duplicate case ids")
    for case in suite.cases:
        reviewers = [label.reviewer_id for label in case.labels]
        if len(reviewers) != len(set(reviewers)):
            raise ValueError(f"case {case.case_id!r} has duplicate reviewer ids")
        for label in case.labels:
            if label.case_id != case.case_id:
                raise ValueError(
                    f"case {case.case_id!r} contains a label for {label.case_id!r}"
                )
            expected_ids = [item.expected_id for item in label.expected]
            if len(expected_ids) != len(set(expected_ids)):
                raise ValueError(
                    f"reviewer {label.reviewer_id!r} has duplicate expected ids"
                )


def _key(expected: ExpectedFinding) -> str:
    return "|".join(sorted(_normalize(part) for part in expected.quote_fragments))


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _rate(matched: int, total: int) -> MatchRate:
    return MatchRate(
        matched=matched,
        total=total,
        rate=round(matched / total, 4) if total else None,
    )


def _load_report(path: Path) -> DeepReviewReport:
    payload = json.loads(path.read_text())
    return DeepReviewReport.model_validate(payload.get("deep_review", payload))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Create blinded deep-review label sheets and measure finding "
            "precision, recall, and false positives."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    case = subparsers.add_parser("case")
    case.add_argument("assessment", type=Path)
    case.add_argument("output", type=Path)
    case.add_argument("--case-id", required=True)
    case.add_argument("--source-ref")
    case.add_argument(
        "--source-kind", default="internal",
        choices=["internal", "public", "synthetic"],
    )
    case.add_argument(
        "--split", default="development", choices=["development", "holdout"]
    )

    template = subparsers.add_parser("template")
    template.add_argument("output", type=Path)
    template.add_argument("--case-id", required=True)
    template.add_argument("--reviewer", required=True)
    template.add_argument("--source-ref")

    merge = subparsers.add_parser("merge")
    merge.add_argument("predictions", type=Path)
    merge.add_argument("output", type=Path)
    merge.add_argument("labels", type=Path, nargs="+")

    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("suite", type=Path)
    evaluate.add_argument("--holdout-only", action="store_true")
    evaluate.add_argument("--thresholds", type=Path)

    args = parser.parse_args()

    if args.command == "case":
        suite = GoldenSuite(
            cases=[
                GoldenCase(
                    case_id=args.case_id,
                    source_kind=args.source_kind,
                    source_ref=args.source_ref,
                    study_split=args.split,
                    predicted=_load_report(args.assessment),
                )
            ]
        )
        args.output.write_text(suite.model_dump_json(indent=2) + "\n")
        return

    if args.command == "template":
        sheet = make_label_template(args.case_id, args.reviewer, args.source_ref)
        args.output.write_text(sheet.model_dump_json(indent=2) + "\n")
        return

    if args.command == "merge":
        suite = GoldenSuite.model_validate_json(args.predictions.read_text())
        sheets = [
            GoldenLabel.model_validate_json(path.read_text()) for path in args.labels
        ]
        merged = merge_labels(suite, sheets)
        args.output.write_text(merged.model_dump_json(indent=2) + "\n")
        return

    suite = GoldenSuite.model_validate_json(args.suite.read_text())
    if args.holdout_only:
        suite = holdout_only(suite)
    report = evaluate_review(suite)
    if args.thresholds:
        thresholds = ReviewEvalThresholds.model_validate_json(
            args.thresholds.read_text()
        )
        print(
            json.dumps(
                {
                    "report": report.model_dump(mode="json"),
                    "decision": evaluate_thresholds(
                        report, thresholds
                    ).model_dump(mode="json"),
                },
                indent=2,
            )
        )
    else:
        print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
