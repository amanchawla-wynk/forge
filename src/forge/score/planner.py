"""Remediation loop: which question to ask next.

Ordering is by *band movement*, not by raw points. A PM does not care that an
answer is worth 0.03; they care that three answers move them from
'Needs work' to 'Ready with gaps'. Gates are always asked first because no
amount of other work can lift the band while a gate is failed.
"""

from __future__ import annotations

from pydantic import BaseModel

from forge.rubric.models import Rubric, Verdict
from forge.score.engine import BAND_ORDER, Assessment, _band_for


class Question(BaseModel):
    criterion_id: str
    criterion_name: str
    target_field: str | None
    question: str
    missing_fields: list[str]
    answer_requirements: list[str]
    is_gate: bool
    # Band this document would reach if only the targeted field were answered.
    band_if_answered: str
    unblocks_consumers: list[str]


def _simulate_field_answer(
    rubric: Rubric,
    assessment: Assessment,
    criterion_id: str,
    missing_count: int,
) -> str:
    """Estimate one field answer without assuming the criterion is complete."""
    earned = 0.0
    possible = 0.0
    cap_index = len(BAND_ORDER) - 1

    for result in assessment.criteria:
        if result.verdict is Verdict.NOT_APPLICABLE:
            continue
        completes_criterion = (
            result.criterion_id == criterion_id and missing_count == 1
        )
        adds_first_field = (
            result.criterion_id == criterion_id
            and missing_count > 1
            and result.verdict is Verdict.ABSENT
        )
        credit = (
            1.0
            if completes_criterion
            else 0.5 if adds_first_field else result.credit
        )
        earned += credit * result.weight
        possible += result.weight

        criterion = rubric.criterion(result.criterion_id)
        still_failing = result.gate_triggered and not completes_criterion
        if still_failing:
            from forge.score.engine import _GATE_CAP

            cap_index = min(cap_index, BAND_ORDER.index(_GATE_CAP[criterion.gate]))

    raw = earned / possible if possible else 0.0
    all_applicable_present = all(
        result.verdict is Verdict.NOT_APPLICABLE
        or result.verdict is Verdict.PRESENT
        or (
            result.criterion_id == criterion_id
            and missing_count == 1
        )
        for result in assessment.criteria
    )
    uncapped = _band_for(
        rubric, raw, all_applicable_present=all_applicable_present
    ).id
    return BAND_ORDER[min(BAND_ORDER.index(uncapped), cap_index)]


def plan_questions(
    rubric: Rubric, assessment: Assessment, limit: int | None = None
) -> list[Question]:
    """Greedy, band-aware ordering of remediation questions.

    Greedy rather than optimal: an exact solution is a knapsack problem, and
    the ordering only needs to be defensible and stable, not minimal.
    """
    failing = [
        r
        for r in assessment.criteria
        if r.verdict in (Verdict.ABSENT, Verdict.PARTIAL)
    ]
    # Gates first; then heaviest; then most consumers unblocked; then id for
    # stable output across runs.
    failing.sort(
        key=lambda r: (
            not r.gate_triggered,
            -r.weight,
            -len(r.consumers),
            r.criterion_id,
        )
    )

    questions: list[Question] = []
    for result in failing:
        criterion = rubric.criterion(result.criterion_id)
        target = next(
            (
                field
                for field in criterion.required_fields
                if field.name in result.missing
            ),
            None,
        )
        questions.append(
            Question(
                criterion_id=result.criterion_id,
                criterion_name=result.name,
                target_field=target.name if target else None,
                question=(
                    target.remediation_question.strip()
                    if target and target.remediation_question
                    else (
                        f"What should the PRD say about "
                        f"this missing detail? {target.description.strip()}"
                        if target
                        else criterion.remediation_prompt.strip()
                    )
                ),
                missing_fields=result.missing,
                answer_requirements=(
                    [
                        target.description.strip()
                        + (
                            f" {target.value_requirement.strip()}"
                            if target.value_requirement
                            else ""
                        )
                    ]
                    if target
                    else []
                ),
                is_gate=result.gate_triggered,
                band_if_answered=_simulate_field_answer(
                    rubric,
                    assessment,
                    result.criterion_id,
                    len(result.missing),
                ),
                unblocks_consumers=[c.value for c in result.consumers],
            )
        )
        if limit is not None and len(questions) >= limit:
            break
    return questions
