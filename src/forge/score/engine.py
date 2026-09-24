"""Deterministic aggregation. Given verdicts, the score is a pure function.

Nothing in this module calls an LLM. Same verdicts in => same band out, always.
That property is what makes the rating defensible.
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, Field

from forge.extract.models import (
    CriterionExtraction,
    SatisfiedFieldEvidence,
    derive_verdict,
    missing_fields,
    satisfied_field_evidence,
)
from forge.rubric.models import (
    VERDICT_CREDIT,
    Band,
    Consumer,
    GateLevel,
    Rubric,
    Verdict,
)
from forge.score.edge_coverage import (
    CoverageStatus,
    EdgeCaseCoverageLedger,
)

# Band ordering, worst to best. Gates clamp an index into this list.
BAND_ORDER = ["not_a_prd", "needs_work", "ready_with_gaps", "ready_to_build"]

_GATE_CAP: dict[GateLevel, str] = {
    GateLevel.CAPS_AT_NEEDS_WORK: "needs_work",
    GateLevel.CAPS_AT_READY_WITH_GAPS: "ready_with_gaps",
}


class CriterionResult(BaseModel):
    criterion_id: str
    name: str
    verdict: Verdict
    weight: float
    credit: float
    consumers: list[Consumer]
    missing: list[str]
    rationale: str
    # Fraction of the k extraction runs that agreed on this verdict (0..1).
    agreement: float = 1.0
    agreement_basis: str = "independent_extraction_runs"
    gate_triggered: bool = False
    # Already-verified fields, kept only so remediation questions can refer to
    # real document content. Never re-enters scoring. See
    # `forge/score/contextualize.py`.
    satisfied_fields: list[SatisfiedFieldEvidence] = Field(default_factory=list)


class ConsumerReadiness(BaseModel):
    consumer: Consumer
    score: float          # 0..1 over criteria this consumer depends on
    blocking: list[str]   # criterion ids that are ABSENT for this consumer


class Assessment(BaseModel):
    rubric_id: str
    rubric_version: str
    calibration_status: str
    raw_score: float           # 0..1, weighted, before gates
    band: str                  # after gates
    band_label: str
    uncapped_band: str         # what it would have been without gates
    gates_failed: list[str]
    confidence: float          # mean agreement across criteria
    confidence_basis: str = "independent_extraction_runs"
    remediated_criteria: list[str] = Field(default_factory=list)
    remediation_delta_count: int = 0
    criteria: list[CriterionResult]
    consumers: list[ConsumerReadiness]

    @property
    def was_capped(self) -> bool:
        return self.band != self.uncapped_band


def _band_for(
    rubric: Rubric, score: float, *, all_applicable_present: bool
) -> Band:
    for band in rubric.bands_descending():
        if score < band.min_score:
            continue
        if band.requires_all_applicable_present and not all_applicable_present:
            continue
        return band
    return rubric.bands_descending()[-1]


def _consolidate(
    rubric: Rubric, runs: list[list[CriterionExtraction]]
) -> tuple[
    dict[str, Verdict],
    dict[str, float],
    dict[str, list[str]],
    dict[str, list[SatisfiedFieldEvidence]],
]:
    """Reduce k independent runs to one verdict per criterion, plus agreement.

    We take the *modal* verdict, not the mean. Averaging a PRESENT and an ABSENT
    into a PARTIAL would invent a result neither run supports; instead the
    disagreement is surfaced as low confidence.

    Ties are broken pessimistically (worst verdict wins) so that an unreliable
    signal can never inflate a score.
    """
    verdicts: dict[str, Verdict] = {}
    agreement: dict[str, float] = {}
    missing: dict[str, list[str]] = {}
    satisfied: dict[str, list[SatisfiedFieldEvidence]] = {}

    severity = {Verdict.PRESENT: 3, Verdict.PARTIAL: 2, Verdict.NOT_APPLICABLE: 1, Verdict.ABSENT: 0}

    for criterion in rubric.criteria:
        observed: list[Verdict] = []
        per_run_missing: list[list[str]] = []
        per_run_satisfied: list[list[SatisfiedFieldEvidence]] = []
        for run in runs:
            extraction = next(
                (e for e in run if e.criterion_id == criterion.id), None
            )
            if extraction is None:
                observed.append(Verdict.ABSENT)
                per_run_missing.append([f.name for f in criterion.required_fields])
                per_run_satisfied.append([])
                continue
            observed.append(derive_verdict(criterion, extraction))
            per_run_missing.append(missing_fields(criterion, extraction))
            per_run_satisfied.append(satisfied_field_evidence(criterion, extraction))

        counts = Counter(observed)
        top = max(counts.values())
        tied = [v for v, n in counts.items() if n == top]
        chosen = min(tied, key=lambda v: severity[v])  # pessimistic tie-break

        verdicts[criterion.id] = chosen
        agreement[criterion.id] = counts[chosen] / len(observed)
        # Report the missing-field list from a run that produced the chosen verdict.
        idx = observed.index(chosen)
        missing[criterion.id] = per_run_missing[idx]
        satisfied[criterion.id] = per_run_satisfied[idx]

    return verdicts, agreement, missing, satisfied


def score(
    rubric: Rubric,
    runs: list[list[CriterionExtraction]],
    *,
    edge_case_coverage: EdgeCaseCoverageLedger | None = None,
) -> Assessment:
    """Turn k extraction runs into a banded assessment."""
    if not runs:
        raise ValueError("no extraction runs supplied")

    verdicts, agreement, missing, satisfied = _consolidate(rubric, runs)

    results: list[CriterionResult] = []
    earned = 0.0
    possible = 0.0
    gates_failed: list[str] = []
    cap_index = len(BAND_ORDER) - 1

    for criterion in rubric.criteria:
        verdict = verdicts[criterion.id]
        criterion_missing = missing[criterion.id]
        if criterion.id == "edge_cases_and_states" and edge_case_coverage is not None:
            # The ledger replaces the three broad behavioural-state fields,
            # but platform scope and accessibility remain normal rubric
            # requirements. A complete matrix must not hide either gap.
            noncoverage_missing = [
                name
                for name in criterion_missing
                if name in {"supported_platforms", "accessibility_approach"}
            ]
            criterion_missing = list(noncoverage_missing)
            if not edge_case_coverage.is_complete:
                criterion_missing.insert(0, "edge_case_coverage")
            coverage_progress = edge_case_coverage.is_complete or any(
                item.status is CoverageStatus.COVERED
                for item in edge_case_coverage.items
            )
            noncoverage_hits = 2 - len(noncoverage_missing)
            if edge_case_coverage.is_complete and noncoverage_hits == 2:
                verdict = Verdict.PRESENT
            elif coverage_progress or noncoverage_hits > 0:
                verdict = Verdict.PARTIAL
            else:
                verdict = Verdict.ABSENT
        credit = VERDICT_CREDIT[verdict]

        # NOT_APPLICABLE leaves the denominator, rather than scoring zero.
        # Otherwise a doc is punished for a section it correctly omitted.
        if verdict is not Verdict.NOT_APPLICABLE:
            earned += credit * criterion.weight
            possible += criterion.weight

        gate_hit = (
            criterion.gate is not GateLevel.NONE
            and verdict in (Verdict.ABSENT, Verdict.PARTIAL)
        )
        if gate_hit:
            gates_failed.append(criterion.id)
            cap_index = min(cap_index, BAND_ORDER.index(_GATE_CAP[criterion.gate]))

        results.append(
            CriterionResult(
                criterion_id=criterion.id,
                name=criterion.name,
                verdict=verdict,
                weight=criterion.weight,
                credit=credit,
                consumers=criterion.consumers,
                missing=criterion_missing,
                rationale=criterion.rationale,
                agreement=agreement[criterion.id],
                gate_triggered=gate_hit,
                satisfied_fields=satisfied[criterion.id],
            )
        )

    raw = earned / possible if possible else 0.0
    all_applicable_present = all(
        result.verdict in (Verdict.PRESENT, Verdict.NOT_APPLICABLE)
        for result in results
    )
    uncapped = _band_for(
        rubric, raw, all_applicable_present=all_applicable_present
    )
    final_id = BAND_ORDER[min(BAND_ORDER.index(uncapped.id), cap_index)]
    final = next(b for b in rubric.bands if b.id == final_id)

    return Assessment(
        rubric_id=rubric.id,
        rubric_version=rubric.version,
        calibration_status=rubric.calibration_status,
        raw_score=round(raw, 4),
        band=final.id,
        band_label=final.label,
        uncapped_band=uncapped.id,
        gates_failed=gates_failed,
        confidence=round(
            sum(agreement.values()) / len(agreement), 4
        ) if agreement else 0.0,
        criteria=results,
        consumers=_consumer_readiness(results),
    )


def _consumer_readiness(results: list[CriterionResult]) -> list[ConsumerReadiness]:
    """Per-consumer rollup: 'can engineering act on this?' etc.

    This is the headline output. A single number tells a PM nothing actionable;
    'QA cannot write test cases from this' tells them exactly what to fix.
    """
    out: list[ConsumerReadiness] = []
    for consumer in Consumer:
        relevant = [
            r
            for r in results
            if consumer in r.consumers and r.verdict is not Verdict.NOT_APPLICABLE
        ]
        if not relevant:
            continue
        earned = sum(r.credit * r.weight for r in relevant)
        possible = sum(r.weight for r in relevant)
        out.append(
            ConsumerReadiness(
                consumer=consumer,
                score=round(earned / possible, 4) if possible else 0.0,
                blocking=[
                    r.criterion_id for r in relevant if r.verdict is Verdict.ABSENT
                ],
            )
        )
    return out
