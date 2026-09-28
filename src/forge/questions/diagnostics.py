"""Offline diagnostics for bounded shadow question generation."""

from __future__ import annotations

import re
from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from forge.questions.apply import (
    apply_question_generation,
    render_deterministic_question,
)
from forge.questions.models import PreparedQuestionGeneration, ShadowQuestion


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuestionCompletion(StrictModel):
    plan_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    completion: str


class Rate(StrictModel):
    matched: int
    total: int
    rate: float | None


class QuestionDiagnosticReport(StrictModel):
    artifact_type: Literal["forge.question_diagnostic_report.v1"] = (
        "forge.question_diagnostic_report.v1"
    )
    calibration_eligible: Literal[False] = False
    score_effect: Literal["none"] = "none"
    eligible_questions: int
    completions_supplied: int
    missing_completions: int
    deterministic: Rate
    generated: Rate
    fallback: Rate
    unsupported_text_count: int
    unsupported_wording_rejections: int
    duplicates: Rate
    stable: bool | None
    questions: list[ShadowQuestion]
    warnings: list[str]


def _rate(matched: int, total: int) -> Rate:
    return Rate(
        matched=matched,
        total=total,
        rate=round(matched / total, 4) if total else None,
    )


def _normalized_question(question: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", question.casefold()))


def evaluate_question_diagnostics(
    preparations: list[PreparedQuestionGeneration],
    completions: list[QuestionCompletion],
    *,
    repeated_preparations: list[PreparedQuestionGeneration] | None = None,
    group_by_plan: dict[str, str] | None = None,
    deterministic_primary: bool = False,
) -> QuestionDiagnosticReport:
    plan_ids = [item.target.plan_id for item in preparations]
    if len(plan_ids) != len(set(plan_ids)):
        raise ValueError("question diagnostics contain duplicate plan ids")
    completion_ids = [item.plan_id for item in completions]
    if len(completion_ids) != len(set(completion_ids)):
        raise ValueError("question diagnostics contain duplicate completions")
    unknown = sorted(set(completion_ids) - set(plan_ids))
    if unknown:
        raise ValueError("question completion references unknown plan id(s): " + ", ".join(unknown))
    if deterministic_primary and completions:
        raise ValueError("deterministic question diagnostics do not accept completions")
    if group_by_plan is not None and set(group_by_plan) != set(plan_ids):
        raise ValueError("question diagnostic groups must cover every plan id exactly")

    by_plan = {item.plan_id: item.completion for item in completions}
    questions = (
        [render_deterministic_question(item) for item in preparations]
        if deterministic_primary
        else [
            apply_question_generation(item, by_plan.get(item.target.plan_id, ""))
            for item in preparations
        ]
    )
    deterministic = sum(
        item.generation_mode == "deterministic_template" for item in questions
    )
    generated = sum(item.generation_mode == "generated" for item in questions)
    fallback = sum(
        item.generation_mode == "rubric_fallback" for item in questions
    )
    unsupported_rejections = sum(
        item.rejection_reason == "unsupported_wording" for item in questions
    )
    counts = Counter(
        (
            group_by_plan[item.plan_id] if group_by_plan is not None else "all",
            _normalized_question(item.question),
        )
        for item in questions
    )
    duplicate_count = sum(count - 1 for count in counts.values() if count > 1)
    stable = None
    if repeated_preparations is not None:
        stable = [item.model_dump(mode="json") for item in preparations] == [
            item.model_dump(mode="json") for item in repeated_preparations
        ]

    warnings: list[str] = []
    missing = 0 if deterministic_primary else len(preparations) - len(completions)
    if missing:
        warnings.append(f"{missing} eligible question(s) had no model completion.")
    if fallback:
        warnings.append(f"{fallback} question(s) used rubric-owned fallback wording.")
    if duplicate_count:
        warnings.append(f"{duplicate_count} duplicate rendered question(s) detected.")
    if stable is False:
        warnings.append("Repeated preparation produced different plans or prompts.")
    return QuestionDiagnosticReport(
        eligible_questions=len(preparations),
        completions_supplied=len(completions),
        missing_completions=missing,
        deterministic=_rate(deterministic, len(questions)),
        generated=_rate(generated, len(questions)),
        fallback=_rate(fallback, len(questions)),
        unsupported_text_count=0,
        unsupported_wording_rejections=unsupported_rejections,
        duplicates=_rate(duplicate_count, len(questions)),
        stable=stable,
        questions=questions,
        warnings=warnings,
    )
