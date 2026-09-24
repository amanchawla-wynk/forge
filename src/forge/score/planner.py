"""Remediation loop: which question to ask next.

Ordering is by *band movement*, not by raw points. A PM does not care that an
answer is worth 0.03; they care that three answers move them from
'Needs work' to 'Ready with gaps'. Gates are always asked first because no
amount of other work can lift the band while a gate is failed.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from forge.rubric.models import Rubric, Verdict
from forge.score.engine import BAND_ORDER, Assessment, _band_for


def document_display_name(source_path: str) -> str:
    """A deterministic, LLM-free document label. Always safe to show a user.

    Derived purely from the filename already supplied by the caller, so it
    can never disagree with the document actually being scored.
    """
    stem = Path(source_path).stem.strip()
    cleaned = stem.replace("_", " ").replace("-", " ").strip()
    return cleaned or stem or source_path


def level0_question(base_question: str, display_name: str | None) -> str:
    """Deterministic contextualization: no model call, never fails, always on.

    Naming the document alone answers "this question feels generic" for the
    common case, since the name is derived by Python, never guessed by a
    model. See `forge/score/contextualize.py` for the optional, guardrailed
    LLM-assisted layer built on top of this.
    """
    if not display_name:
        return base_question
    return f'For "{display_name}": {base_question}'


class Question(BaseModel):
    criterion_id: str
    criterion_name: str
    target_field: str | None
    question: str
    # The rubric-owned question text before any contextualization (D-031).
    # `question` may prefix or extend this with document-derived content;
    # `base_question` is always the plain, static, config-owned string.
    base_question: str
    # Framing whose phrasing produced `base_question`, or None when the
    # rubric default was used. Audit only; never affects scoring (D-036).
    framing: str | None = None
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
    rubric: Rubric,
    assessment: Assessment,
    limit: int | None = None,
    *,
    display_name: str | None = None,
    framing: str | None = None,
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

    # An unknown framing must behave exactly like no framing at all, so a bad
    # value can never strand the loop on a question nobody authored.
    resolved_framing = (
        framing
        if framing is not None and rubric.framing(framing) is not None
        else rubric.default_framing
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
        configured = target.question_for(resolved_framing) if target else None
        base_question = (
            configured.strip()
            if configured
            else (
                f"What should the PRD say about "
                f"this missing detail? {target.description.strip()}"
                if target
                else criterion.remediation_prompt.strip()
            )
        )
        questions.append(
            Question(
                criterion_id=result.criterion_id,
                criterion_name=result.name,
                target_field=target.name if target else None,
                question=level0_question(base_question, display_name),
                base_question=base_question,
                framing=resolved_framing,
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
