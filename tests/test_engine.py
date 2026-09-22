from __future__ import annotations

import pytest

from forge.extract.models import CriterionExtraction, Evidence, FieldExtraction
from forge.rubric.loader import load_rubric
from forge.rubric.models import Rubric, Verdict
from forge.score.engine import score
from forge.score.planner import plan_questions


@pytest.fixture
def rubric() -> Rubric:
    return load_rubric("prd")


def _full(criterion) -> CriterionExtraction:
    return CriterionExtraction(
        criterion_id=criterion.id,
        fields=[
            FieldExtraction(
                name=f.name,
                value=f"value for {f.name}",
                evidence=Evidence(quote=f"quoted {f.name}", page=1),
            )
            for f in criterion.fields
        ],
    )


def _empty(criterion) -> CriterionExtraction:
    return CriterionExtraction(criterion_id=criterion.id, fields=[])


def test_perfect_document_is_ready_to_build(rubric):
    run = [_full(c) for c in rubric.criteria]
    result = score(rubric, [run, run, run])
    assert result.raw_score == 1.0
    assert result.band == "ready_to_build"
    assert result.gates_failed == []
    assert result.confidence == 1.0


def test_empty_document_is_not_a_prd(rubric):
    run = [_empty(c) for c in rubric.criteria]
    result = score(rubric, [run])
    assert result.raw_score == 0.0
    assert result.band == "not_a_prd"


def test_gate_caps_an_otherwise_excellent_document(rubric):
    """The core anti-gaming property: a long, polished, unmeasurable PRD
    must not score well just because everything else is present."""
    run = [
        _empty(c) if c.id == "success_metrics" else _full(c)
        for c in rubric.criteria
    ]
    result = score(rubric, [run])
    assert result.raw_score > 0.88          # would have been top band
    assert result.uncapped_band == "ready_to_build"
    assert result.band == "needs_work"      # gate clamps it
    assert result.was_capped
    assert "success_metrics" in result.gates_failed


def test_partial_extraction_yields_partial_verdict(rubric):
    criterion = rubric.criterion("success_metrics")
    partial = CriterionExtraction(
        criterion_id=criterion.id,
        fields=[
            FieldExtraction(
                name="primary_metric",
                value="activation rate",
                evidence=Evidence(quote="we will track activation rate"),
            )
        ],
    )
    run = [partial if c.id == criterion.id else _full(c) for c in rubric.criteria]
    result = score(rubric, [run])
    got = next(r for r in result.criteria if r.criterion_id == "success_metrics")
    assert got.verdict is Verdict.PARTIAL
    assert set(got.missing) == {"baseline", "target", "measurement_window"}


def test_value_without_evidence_earns_no_credit(rubric):
    """Anti-hallucination: the model cannot award credit for uncited content."""
    criterion = rubric.criterion("non_goals")
    uncited = CriterionExtraction(
        criterion_id=criterion.id,
        fields=[FieldExtraction(name="non_goals", value="mobile app", evidence=None)],
    )
    result = score(rubric, [[uncited]])
    got = next(r for r in result.criteria if r.criterion_id == "non_goals")
    assert got.verdict is Verdict.ABSENT


def test_tbd_is_rejected(rubric):
    criterion = rubric.criterion("non_goals")
    tbd = CriterionExtraction(
        criterion_id=criterion.id,
        fields=[
            FieldExtraction(
                name="non_goals",
                value="TBD",
                evidence=Evidence(quote="Non-goals: TBD"),
            )
        ],
    )
    result = score(rubric, [[tbd]])
    got = next(r for r in result.criteria if r.criterion_id == "non_goals")
    assert got.verdict is Verdict.ABSENT


def test_disagreeing_runs_break_pessimistically(rubric):
    """One PRESENT, one ABSENT must not average into PARTIAL, and must not
    round up. It resolves down, with confidence reported as 0.5."""
    criterion = rubric.criterion("non_goals")
    run_a = [_full(criterion)]
    run_b = [_empty(criterion)]
    result = score(rubric, [run_a, run_b])
    got = next(r for r in result.criteria if r.criterion_id == "non_goals")
    assert got.verdict is Verdict.ABSENT
    assert got.agreement == 0.5


def test_not_applicable_leaves_the_denominator(rubric):
    """A doc correctly omitting an irrelevant section must not be punished."""
    na = CriterionExtraction(
        criterion_id="risk_compliance",
        fields=[],
        not_applicable=True,
        not_applicable_reason="Feature handles no user data; internal tooling only.",
    )
    run = [na if c.id == "risk_compliance" else _full(c) for c in rubric.criteria]
    result = score(rubric, [run])
    assert result.raw_score == 1.0
    assert result.band == "ready_to_build"


def test_not_applicable_rejected_where_not_permitted(rubric):
    """A model cannot opt out of a mandatory criterion."""
    na = CriterionExtraction(
        criterion_id="success_metrics",
        fields=[],
        not_applicable=True,
        not_applicable_reason="hard to measure",
    )
    result = score(rubric, [[na]])
    got = next(r for r in result.criteria if r.criterion_id == "success_metrics")
    assert got.verdict is Verdict.ABSENT


def test_questions_are_gate_first_and_band_aware(rubric):
    run = [_empty(c) for c in rubric.criteria]
    result = score(rubric, [run])
    questions = plan_questions(rubric, result, limit=5)
    assert questions[0].is_gate
    # Band must be monotonically non-decreasing down the question list.
    from forge.score.engine import BAND_ORDER

    indices = [BAND_ORDER.index(q.band_if_answered) for q in questions]
    assert indices == sorted(indices)


def test_scoring_is_deterministic(rubric):
    run = [_full(c) if i % 2 else _empty(c) for i, c in enumerate(rubric.criteria)]
    a = score(rubric, [run, run, run])
    b = score(rubric, [run, run, run])
    assert a.model_dump() == b.model_dump()
