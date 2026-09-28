from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from forge.evaluate.consolidate import (
    consolidate_evaluation_fragments,
    consolidate_evaluation_runs,
)
from forge.evaluate.models import (
    CriterionEvaluation,
    CriterionEvaluationSubmission,
)
from forge.evaluate.prompt import build_criterion_evaluation_prompt
from forge.evaluate.verify import verify_criterion_evaluation
from forge.questions.models import PreparedQuestionGeneration
from forge.questions.prepare import prepare_question_generation

if TYPE_CHECKING:
    from forge.service import PreparedAssessmentInput


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CriterionEvaluationPlanItem(StrictModel):
    criterion_id: str
    batch_id: str
    plan_fingerprint: str
    prompt: str


class PreparedCriterionEvaluation(StrictModel):
    source_path: str
    snapshot_id: str
    rubric_id: str
    rubric_version: str
    plan_fingerprint: str
    expected_runs: int
    items: list[CriterionEvaluationPlanItem]


class CriterionEvaluationFragment(StrictModel):
    batch_id: str
    plan_fingerprint: str
    criteria: list[CriterionEvaluationSubmission]


class CriterionEvaluationRun(StrictModel):
    run_index: int = Field(ge=1)
    fragments: list[CriterionEvaluationFragment] = Field(min_length=1)


class CriterionEvaluationBatch(StrictModel):
    runs: list[CriterionEvaluationRun] = Field(min_length=1)


class VerifiedCriterionEvaluations(StrictModel):
    artifacts: list[CriterionEvaluation]
    consolidated: list[CriterionEvaluation]
    question_generation: PreparedQuestionGeneration | None = None


def _run_id(
    prepared: PreparedAssessmentInput, run: CriterionEvaluationRun
) -> str:
    payload = {
        "snapshot_id": prepared.snapshot.snapshot_id,
        "rubric_id": prepared.rubric.id,
        "rubric_version": prepared.rubric.version,
        "plan_fingerprint": prepared.plan_fingerprint,
        "run_index": run.run_index,
        "fragments": [item.model_dump(mode="json") for item in run.fragments],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def prepare_evaluation_plan(
    prepared: PreparedAssessmentInput,
) -> PreparedCriterionEvaluation:
    return PreparedCriterionEvaluation(
        source_path=prepared.document.source_path,
        snapshot_id=prepared.snapshot.snapshot_id,
        rubric_id=prepared.rubric.id,
        rubric_version=prepared.rubric.version,
        plan_fingerprint=prepared.plan_fingerprint,
        expected_runs=prepared.rubric.extraction_runs,
        items=[
            CriterionEvaluationPlanItem(
                criterion_id=criterion.id,
                batch_id=batch.id,
                plan_fingerprint=prepared.plan_fingerprint,
                prompt=build_criterion_evaluation_prompt(
                    batch.document,
                    criterion,
                    batch_id=batch.id,
                    plan_fingerprint=prepared.plan_fingerprint,
                    run_index=1,
                ),
            )
            for batch in prepared.batches
            for criterion in prepared.rubric.criteria
        ],
    )


def prepare_evaluation_item(
    prepared: PreparedAssessmentInput,
    criterion_id: str,
    batch_id: str,
    *,
    run_index: int,
) -> CriterionEvaluationPlanItem:
    criterion = prepared.rubric.criterion(criterion_id)
    batch = next(
        (item for item in prepared.batches if item.id == batch_id), None
    )
    if batch is None:
        expected = ", ".join(item.id for item in prepared.batches)
        raise ValueError(
            f"unknown batch_id {batch_id!r}; expected one of: {expected}"
        )
    return CriterionEvaluationPlanItem(
        criterion_id=criterion.id,
        batch_id=batch.id,
        plan_fingerprint=prepared.plan_fingerprint,
        prompt=build_criterion_evaluation_prompt(
            batch.document,
            criterion,
            batch_id=batch.id,
            plan_fingerprint=prepared.plan_fingerprint,
            run_index=run_index,
        ),
    )


def verify_evaluation_batch(
    prepared: PreparedAssessmentInput,
    submitted: CriterionEvaluationBatch,
) -> VerifiedCriterionEvaluations:
    run_indexes = [run.run_index for run in submitted.runs]
    if len(run_indexes) != len(set(run_indexes)):
        raise ValueError("duplicate criterion evaluation run_index")
    expected_batches = [batch.id for batch in prepared.batches]
    batches = {batch.id: batch for batch in prepared.batches}
    expected_criteria = {criterion.id for criterion in prepared.rubric.criteria}
    per_run: list[list[CriterionEvaluation]] = []
    for run in submitted.runs:
        fragment_ids = [fragment.batch_id for fragment in run.fragments]
        if len(fragment_ids) != len(set(fragment_ids)):
            raise ValueError("duplicate criterion evaluation batch fragments")
        missing = sorted(set(expected_batches) - set(fragment_ids))
        unknown = sorted(set(fragment_ids) - set(expected_batches))
        if missing or unknown:
            details = []
            if missing:
                details.append("missing " + ", ".join(missing))
            if unknown:
                details.append("unknown " + ", ".join(unknown))
            raise ValueError("invalid criterion evaluation fragments: " + "; ".join(details))
        run_id = _run_id(prepared, run)
        by_criterion: dict[str, list[CriterionEvaluation]] = {
            criterion.id: [] for criterion in prepared.rubric.criteria
        }
        for fragment in run.fragments:
            if fragment.plan_fingerprint != prepared.plan_fingerprint:
                raise ValueError("criterion evaluation uses a stale plan_fingerprint")
            criterion_ids = [item.criterion_id for item in fragment.criteria]
            if len(criterion_ids) != len(set(criterion_ids)):
                raise ValueError("duplicate criteria in criterion evaluation fragment")
            if set(criterion_ids) != expected_criteria:
                raise ValueError("criterion evaluation fragment schema is incomplete")
            for submission in fragment.criteria:
                by_criterion[submission.criterion_id].append(
                    verify_criterion_evaluation(
                        batches[fragment.batch_id].document,
                        prepared.rubric,
                        submission,
                        plan_fingerprint=prepared.plan_fingerprint,
                        run_id=run_id,
                        batch_ids=[fragment.batch_id],
                        coverage_complete=False,
                    )
                )
        per_run.append(
            [
                consolidate_evaluation_fragments(
                    by_criterion[criterion.id],
                    expected_batch_ids=expected_batches,
                    criterion=criterion,
                )
                for criterion in prepared.rubric.criteria
            ]
        )
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
            criterion=criterion,
        )
        for criterion in prepared.rubric.criteria
    ]
    return VerifiedCriterionEvaluations(
        artifacts=artifacts,
        consolidated=consolidated,
        question_generation=prepare_question_generation(
            prepared.rubric, consolidated
        ),
    )
