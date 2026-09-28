from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from forge.evaluate.consolidate import (
    consolidate_evaluation_runs,
    evaluations_from_legacy_extraction_run,
)
from forge.evaluate.models import CriterionEvaluation
from forge.deep_review import (
    DeepReviewReport,
    build_deep_review,
    mechanical_claim_occurrences,
)
from forge.extract.batch import ExtractionBatch, verify_extraction_batch_with_claims
from forge.extract.models import CriterionExtraction
from forge.ingest.adapters import LocalFileSourceAdapter, SourceRef
from forge.ingest.batching import DocumentBatch, batch_document, plan_fingerprint
from forge.ingest.document import (
    add_product_context,
    add_supplemental_answers,
    ingest_snapshot,
)
from forge.ingest.models import (
    NormalizedDocument,
    ProductContextTerm,
    SupplementalAnswer,
)
from forge.ingest.snapshot import DocumentSnapshot, SnapshotRepository
from forge.rubric.loader import load_rubric
from forge.rubric.models import Rubric
from forge.score.engine import Assessment, score
from forge.score.edge_coverage import (
    EdgeCaseCoverageLedger,
    apply_coverage_answers,
    edge_case_type,
    next_uncovered_item,
    render_coverage_question,
    verify_coverage_ledger,
)
from forge.score.consistency import (
    ConsistencyLedger,
    consistency_findings,
    verify_consistency_ledger,
)
from forge.score.planner import Question, document_display_name, plan_questions
from forge.score.report import NarrativeReport, build_narrative_report


class AssessmentResponse(BaseModel):
    source_path: str
    deep_review: DeepReviewReport | None = None
    report: NarrativeReport
    assessment: Assessment
    next_question: Question | None
    supplemental_answers: list[SupplementalAnswer]
    run_count: int
    expected_run_count: int
    disputed_criteria: list[str]
    recommended_additional_runs: int
    client_models: list[str]
    product_context: list[ProductContextTerm]
    framing: str | None
    edge_case_coverage: EdgeCaseCoverageLedger | None
    consistency_ledger: ConsistencyLedger | None = None
    warnings: list[str]
    criterion_evaluations: list[CriterionEvaluation] = Field(default_factory=list)


@dataclass(frozen=True)
class PreparedAssessmentInput:
    snapshot: DocumentSnapshot
    rubric: Rubric
    rubric_name: str
    document: NormalizedDocument
    batches: tuple[DocumentBatch, ...]
    plan_fingerprint: str
    supplemental_answers: tuple[SupplementalAnswer, ...]
    product_context: tuple[ProductContextTerm, ...]


def assess_extractions(
    source_path: str,
    batch: ExtractionBatch,
    *,
    rubric_name: str = "prd",
    client_models: list[str] | None = None,
    supplemental_answers: list[SupplementalAnswer] | None = None,
    product_context: list[ProductContextTerm] | None = None,
    framing: str | None = None,
    display_name: str | None = None,
    edge_case_coverage: EdgeCaseCoverageLedger | None = None,
    consistency_ledger: ConsistencyLedger | None = None,
) -> AssessmentResponse:
    prepared = prepare_assessment(
        source_path,
        rubric_name,
        supplemental_answers,
        product_context,
    )
    return assess_prepared_extractions(
        prepared,
        batch,
        client_models=client_models,
        framing=framing,
        display_name=display_name,
        edge_case_coverage=edge_case_coverage,
        consistency_ledger=consistency_ledger,
    )


def assess_prepared_extractions(
    prepared: PreparedAssessmentInput,
    batch: ExtractionBatch,
    *,
    client_models: list[str] | None = None,
    framing: str | None = None,
    display_name: str | None = None,
    edge_case_coverage: EdgeCaseCoverageLedger | None = None,
    consistency_ledger: ConsistencyLedger | None = None,
) -> AssessmentResponse:
    document = prepared.document
    rubric = prepared.rubric
    answers = list(prepared.supplemental_answers)
    terms = list(prepared.product_context)
    runs, claims = verify_extraction_batch_with_claims(
        list(prepared.batches), batch, rubric
    )
    _, criterion_evaluations = build_legacy_criterion_evaluations(prepared, runs)
    verified_coverage = (
        verify_coverage_ledger(
            document, apply_coverage_answers(edge_case_coverage, answers)
        )
        if edge_case_coverage is not None
        else None
    )
    assessment = score(
        rubric, runs, edge_case_coverage=verified_coverage
    )
    resolved_display_name = display_name or document_display_name(document.source_path)
    questions = plan_questions(
        rubric,
        assessment,
        display_name=resolved_display_name,
        framing=framing,
    )
    if verified_coverage is not None:
        uncovered = next_uncovered_item(verified_coverage)
        edge_question = next(
            (
                question
                for question in questions
                if question.criterion_id == "edge_cases_and_states"
            ),
            None,
        )
        if uncovered is not None and edge_question is not None:
            rendered = render_coverage_question(resolved_display_name, uncovered)
            edge = edge_case_type(uncovered.edge_case_id)
            edge_question.target_field = "edge_case_coverage"
            edge_question.question = rendered
            edge_question.base_question = edge.question
            edge_question.answer_requirements = [
                "State the expected behavior for this requirement and edge "
                "case, including the user-visible result and recovery path."
            ]
            edge_question.band_if_answered = assessment.band
            edge_question.requirement_quote = uncovered.requirement_quote
            edge_question.edge_case_id = uncovered.edge_case_id
            edge_question.taxonomy_version = verified_coverage.taxonomy_version
    disputed = [
        result.criterion_id
        for result in assessment.criteria
        if result.agreement < 1.0
    ]
    recommended_additional_runs = (
        rubric.extraction_runs - len(runs)
        if len(runs) < rubric.extraction_runs
        else max(0, 5 - len(runs)) if disputed else 0
    )

    warnings = [
        "This assessment uses Forge's source-backed cross-industry expert "
        "baseline. It is operational without company data, but has not been "
        "validated against your organization's independent reviewer labels."
    ]
    if document.visual_assets:
        warnings.append(
            f"Detected {len(document.visual_assets)} visual asset(s). Text found in "
            "the document may receive credit, but image and diagram interpretation "
            "is advisory and is not yet included in scoring."
        )
    if len(runs) < rubric.extraction_runs:
        warnings.append(
            f"Only {len(runs)} extraction run(s) were supplied; "
            f"the rubric expects {rubric.extraction_runs}. Confidence does not measure test/retest stability."
        )
    if terms:
        warnings.append(
            "Product terminology context was used only to disambiguate names; "
            "it was excluded from evidence verification and scoring."
        )
    if verified_coverage is not None:
        covered = sum(
            item.status.value in {"covered", "not_applicable"}
            for item in verified_coverage.items
        )
        warnings.append(
            f"Edge-case taxonomy {verified_coverage.taxonomy_version} covers "
            f"{covered} of {len(verified_coverage.items)} applicable/assessed "
            "pairs. Completeness is relative to this declared taxonomy, not "
            "every imaginable edge case."
        )

    claims.extend(mechanical_claim_occurrences(document, claims))
    verified_consistency = (
        verify_consistency_ledger(document, consistency_ledger)
        if consistency_ledger is not None
        else None
    )
    if verified_consistency is not None:
        warnings.append(
            f"Consistency taxonomy {verified_consistency.taxonomy_version} "
            f"classified {len(verified_consistency.items)} source-verified "
            "statement pair(s). Conflict relations are advisory and never "
            "change the readiness score."
        )
    return AssessmentResponse(
        source_path=document.source_path,
        deep_review=build_deep_review(
            rubric,
            claims,
            extra_findings=(
                consistency_findings(rubric, verified_consistency, claims)
                if verified_consistency is not None
                else None
            ),
        ),
        report=build_narrative_report(
            assessment,
            questions,
            run_count=len(runs),
            expected_run_count=rubric.extraction_runs,
        ),
        assessment=assessment,
        next_question=questions[0] if questions else None,
        supplemental_answers=answers,
        run_count=len(runs),
        expected_run_count=rubric.extraction_runs,
        disputed_criteria=disputed,
        recommended_additional_runs=recommended_additional_runs,
        client_models=client_models or [],
        product_context=terms,
        framing=questions[0].framing if questions else rubric.default_framing,
        edge_case_coverage=verified_coverage,
        consistency_ledger=verified_consistency,
        warnings=warnings,
        criterion_evaluations=criterion_evaluations,
    )


def build_legacy_criterion_evaluations(
    prepared: PreparedAssessmentInput,
    runs: list[list[CriterionExtraction]],
) -> tuple[list[CriterionEvaluation], list[CriterionEvaluation]]:
    """Build score-neutral Phase 2 records from verified legacy runs."""
    per_run = [
        evaluations_from_legacy_extraction_run(
            prepared.rubric,
            run,
            snapshot_id=prepared.snapshot.snapshot_id,
            plan_fingerprint=prepared.plan_fingerprint,
            run_index=index,
        )
        for index, run in enumerate(runs, start=1)
    ]
    artifacts = [evaluation for run in per_run for evaluation in run]
    consolidated = [
        consolidate_evaluation_runs(
            [
                evaluation
                for run in per_run
                for evaluation in run
                if evaluation.criterion_id == criterion.id
            ],
            expected_run_count=prepared.rubric.extraction_runs,
        )
        for criterion in prepared.rubric.criteria
    ]
    return artifacts, consolidated


def assess_extraction_json(
    source_path: str,
    extraction_json: str,
    *,
    rubric_name: str = "prd",
    supplemental_answers: list[SupplementalAnswer] | None = None,
    product_context: list[ProductContextTerm] | None = None,
    framing: str | None = None,
    edge_case_coverage: EdgeCaseCoverageLedger | None = None,
    consistency_ledger: ConsistencyLedger | None = None,
) -> AssessmentResponse:
    prepared = prepare_assessment(
        source_path,
        rubric_name,
        supplemental_answers,
        product_context,
    )
    return assess_prepared_extraction_json(
        prepared,
        extraction_json,
        framing=framing,
        edge_case_coverage=edge_case_coverage,
        consistency_ledger=consistency_ledger,
    )


def assess_prepared_extraction_json(
    prepared: PreparedAssessmentInput,
    extraction_json: str,
    *,
    framing: str | None = None,
    edge_case_coverage: EdgeCaseCoverageLedger | None = None,
    consistency_ledger: ConsistencyLedger | None = None,
) -> AssessmentResponse:
    payload = json.loads(extraction_json)
    if "runs" not in payload:
        payload = {"runs": [payload]}
    return assess_prepared_extractions(
        prepared,
        ExtractionBatch.model_validate(payload),
        framing=framing,
        edge_case_coverage=edge_case_coverage,
        consistency_ledger=consistency_ledger,
    )


def prepare_assessment_input(
    source_path: str,
    rubric_name: str = "prd",
    supplemental_answers: list[SupplementalAnswer] | None = None,
    product_context: list[ProductContextTerm] | None = None,
    snapshot: DocumentSnapshot | None = None,
) -> tuple[NormalizedDocument, Rubric]:
    prepared = prepare_assessment(
        source_path,
        rubric_name,
        supplemental_answers,
        product_context,
        snapshot=snapshot,
    )
    return prepared.document, prepared.rubric


def prepare_assessment(
    source_path: str,
    rubric_name: str = "prd",
    supplemental_answers: list[SupplementalAnswer] | None = None,
    product_context: list[ProductContextTerm] | None = None,
    snapshot_repository: SnapshotRepository | None = None,
    *,
    snapshot: DocumentSnapshot | None = None,
) -> PreparedAssessmentInput:
    rubric = load_rubric(rubric_name)
    answers = tuple(supplemental_answers or [])
    terms = tuple(product_context or [])
    known_criteria = {criterion.id for criterion in rubric.criteria}
    unknown = sorted(
        {answer.criterion_id for answer in answers} - known_criteria
    )
    if unknown:
        raise ValueError(
            "supplemental answers reference unknown criteria: " + ", ".join(unknown)
        )
    if snapshot is not None and snapshot_repository is not None:
        raise ValueError("supply either snapshot or snapshot_repository, not both")
    if snapshot is None:
        snapshot = ingest_snapshot(source_path, snapshot_repository)
    else:
        _verify_live_snapshot_source(source_path, snapshot)
    resolved_source_path = str(Path(source_path).expanduser().resolve())
    snapshot_document = snapshot.document.model_copy(
        update={"source_path": resolved_source_path}, deep=True
    )
    document = add_product_context(
        add_supplemental_answers(snapshot_document, list(answers)),
        list(terms),
    )
    batches = tuple(batch_document(document))
    return PreparedAssessmentInput(
        snapshot=snapshot,
        rubric=rubric,
        rubric_name=rubric_name,
        document=document,
        batches=batches,
        plan_fingerprint=plan_fingerprint(
            list(batches), rubric.id, rubric.version
        ),
        supplemental_answers=answers,
        product_context=terms,
    )


def _verify_live_snapshot_source(
    source_path: str, snapshot: DocumentSnapshot
) -> None:
    artifact = LocalFileSourceAdapter().acquire(SourceRef.local_file(source_path))
    if artifact.sha256 != snapshot.source.sha256:
        raise ValueError("supplied snapshot does not match the live source bytes")
    if artifact.source_type != snapshot.source.source_type:
        raise ValueError("supplied snapshot does not match the live source type")
