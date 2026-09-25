from __future__ import annotations

import json

from pydantic import BaseModel

from forge.deep_review import (
    DeepReviewReport,
    build_deep_review,
    mechanical_claim_occurrences,
)
from forge.extract.batch import ExtractionBatch, verify_extraction_batch_with_claims
from forge.ingest.batching import batch_document
from forge.ingest.document import (
    add_product_context,
    add_supplemental_answers,
    ingest_document,
)
from forge.ingest.models import (
    NormalizedDocument,
    ProductContextTerm,
    SupplementalAnswer,
)
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
    answers = supplemental_answers or []
    terms = product_context or []
    document, rubric = prepare_assessment_input(
        source_path, rubric_name, answers, terms
    )
    document_batches = batch_document(document)
    runs, claims = verify_extraction_batch_with_claims(
        document_batches, batch, rubric
    )
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
    )


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
    payload = json.loads(extraction_json)
    if "runs" not in payload:
        payload = {"runs": [payload]}
    return assess_extractions(
        source_path,
        ExtractionBatch.model_validate(payload),
        rubric_name=rubric_name,
        supplemental_answers=supplemental_answers,
        product_context=product_context,
        framing=framing,
        edge_case_coverage=edge_case_coverage,
        consistency_ledger=consistency_ledger,
    )


def prepare_assessment_input(
    source_path: str,
    rubric_name: str = "prd",
    supplemental_answers: list[SupplementalAnswer] | None = None,
    product_context: list[ProductContextTerm] | None = None,
) -> tuple[NormalizedDocument, Rubric]:
    rubric = load_rubric(rubric_name)
    answers = supplemental_answers or []
    known_criteria = {criterion.id for criterion in rubric.criteria}
    unknown = sorted(
        {answer.criterion_id for answer in answers} - known_criteria
    )
    if unknown:
        raise ValueError(
            "supplemental answers reference unknown criteria: " + ", ".join(unknown)
        )
    document = add_supplemental_answers(ingest_document(source_path), answers)
    return add_product_context(document, product_context or []), rubric
