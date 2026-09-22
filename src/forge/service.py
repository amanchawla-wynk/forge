from __future__ import annotations

import json

from pydantic import BaseModel

from forge.extract.batch import ExtractionBatch, verify_extraction_batch
from forge.ingest.batching import batch_document
from forge.ingest.document import add_supplemental_answers, ingest_document
from forge.ingest.models import NormalizedDocument, SupplementalAnswer
from forge.rubric.loader import load_rubric
from forge.rubric.models import Rubric
from forge.score.engine import Assessment, score
from forge.score.planner import Question, plan_questions
from forge.score.report import NarrativeReport, build_narrative_report


class AssessmentResponse(BaseModel):
    source_path: str
    report: NarrativeReport
    assessment: Assessment
    next_question: Question | None
    supplemental_answers: list[SupplementalAnswer]
    run_count: int
    expected_run_count: int
    client_models: list[str]
    warnings: list[str]


def assess_extractions(
    source_path: str,
    batch: ExtractionBatch,
    *,
    rubric_name: str = "prd",
    client_models: list[str] | None = None,
    supplemental_answers: list[SupplementalAnswer] | None = None,
) -> AssessmentResponse:
    answers = supplemental_answers or []
    document, rubric = prepare_assessment_input(source_path, rubric_name, answers)
    document_batches = batch_document(document)
    runs = verify_extraction_batch(document_batches, batch, rubric)
    assessment = score(rubric, runs)
    questions = plan_questions(rubric, assessment, limit=3)

    warnings = [
        "The bundled PRD rubric is generic, untuned, and not calibrated for your company."
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

    return AssessmentResponse(
        source_path=document.source_path,
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
        client_models=client_models or [],
        warnings=warnings,
    )


def assess_extraction_json(
    source_path: str,
    extraction_json: str,
    *,
    rubric_name: str = "prd",
    supplemental_answers: list[SupplementalAnswer] | None = None,
) -> AssessmentResponse:
    payload = json.loads(extraction_json)
    if "runs" not in payload:
        payload = {"runs": [payload]}
    return assess_extractions(
        source_path,
        ExtractionBatch.model_validate(payload),
        rubric_name=rubric_name,
        supplemental_answers=supplemental_answers,
    )


def prepare_assessment_input(
    source_path: str,
    rubric_name: str = "prd",
    supplemental_answers: list[SupplementalAnswer] | None = None,
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
    return add_supplemental_answers(ingest_document(source_path), answers), rubric
