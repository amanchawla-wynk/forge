"""Remediation loop: which question to ask next.

Ordering is by *band movement*, not by raw points. A PM does not care that an
answer is worth 0.03; they care that three answers move them from
'Needs work' to 'Ready with gaps'. Gates are always asked first because no
amount of other work can lift the band while a gate is failed.
"""

from __future__ import annotations

from pydantic import BaseModel

from forge.rubric.models import Rubric, Verdict
from forge.score.engine import BAND_ORDER, Assessment


class Question(BaseModel):
    criterion_id: str
    criterion_name: str
    question: str
    missing_fields: list[str]
    is_gate: bool
    # Band this document would reach if this and all higher-priority
    # questions were answered fully.
    band_if_answered: str
    unblocks_consumers: list[str]


def _simulate(rubric: Rubric, assessment: Assessment, fixed: set[str]) -> str:
    """Recompute the band assuming `fixed` criteria become PRESENT."""
    earned = 0.0
    possible = 0.0
    cap_index = len(BAND_ORDER) - 1

    for result in assessment.criteria:
        if result.verdict is Verdict.NOT_APPLICABLE:
            continue
        credit = 1.0 if result.criterion_id in fixed else result.credit
        earned += credit * result.weight
        possible += result.weight

        criterion = rubric.criterion(result.criterion_id)
        still_failing = result.gate_triggered and result.criterion_id not in fixed
        if still_failing:
            from forge.score.engine import _GATE_CAP

            cap_index = min(cap_index, BAND_ORDER.index(_GATE_CAP[criterion.gate]))

    raw = earned / possible if possible else 0.0
    uncapped = next(
        b.id for b in rubric.bands_descending() if raw >= b.min_score
    )
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
    fixed: set[str] = set()
    for result in failing:
        fixed.add(result.criterion_id)
        criterion = rubric.criterion(result.criterion_id)
        questions.append(
            Question(
                criterion_id=result.criterion_id,
                criterion_name=result.name,
                question=criterion.remediation_prompt.strip(),
                missing_fields=result.missing,
                is_gate=result.gate_triggered,
                band_if_answered=_simulate(rubric, assessment, fixed),
                unblocks_consumers=[c.value for c in result.consumers],
            )
        )
        if limit is not None and len(questions) >= limit:
            break
    return questions
