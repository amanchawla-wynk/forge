from __future__ import annotations

from pydantic import BaseModel

from forge.rubric.models import Verdict
from forge.score.engine import Assessment
from forge.score.planner import Question


class NarrativeReport(BaseModel):
    headline: str
    summary: str
    key_gaps: list[str]
    blocked_consumers: list[str]
    next_step: str | None
    confidence_note: str


def build_narrative_report(
    assessment: Assessment,
    questions: list[Question],
    *,
    run_count: int,
    expected_run_count: int,
) -> NarrativeReport:
    applicable = [
        result
        for result in assessment.criteria
        if result.verdict is not Verdict.NOT_APPLICABLE
    ]
    complete = sum(result.verdict is Verdict.PRESENT for result in applicable)
    partial = sum(result.verdict is Verdict.PARTIAL for result in applicable)
    absent = sum(result.verdict is Verdict.ABSENT for result in applicable)

    summary = (
        f"{complete} of {len(applicable)} applicable criteria are complete; "
        f"{partial} are partial and {absent} are absent."
    )
    gate_names = [
        result.name for result in assessment.criteria if result.gate_triggered
    ]
    if gate_names:
        summary += " Failed gates cap readiness: " + ", ".join(gate_names) + "."

    blocked_consumers = [
        readiness.consumer.value
        for readiness in assessment.consumers
        if readiness.blocking
    ]
    if blocked_consumers:
        summary += " Blocking gaps remain for: " + ", ".join(blocked_consumers) + "."

    if run_count < expected_run_count:
        confidence_note = (
            f"Only {run_count} of {expected_run_count} expected extraction runs "
            "were supplied; test/retest stability is unknown."
        )
    else:
        confidence_note = (
            f"Verdict agreement across {run_count} extraction runs was "
            f"{assessment.confidence:.0%}."
        )

    return NarrativeReport(
        headline=assessment.band_label,
        summary=summary,
        key_gaps=[
            _gap_summary(question)
            for question in questions[:3]
        ],
        blocked_consumers=blocked_consumers,
        next_step=questions[0].question if questions else None,
        confidence_note=confidence_note,
    )


def _gap_summary(question: Question) -> str:
    if not question.missing_fields:
        return question.criterion_name
    return (
        f"{question.criterion_name}: missing "
        + ", ".join(question.missing_fields)
    )
