from __future__ import annotations

import json

from forge.remediation import (
    apply_checkpoint,
    begin_remediation,
    prepare_checkpoint,
    record_answer,
)
from forge.score.edge_coverage import (
    CoverageStatus,
    EdgeCaseCoverageItem,
    EdgeCaseCoverageLedger,
)
from forge.rubric.loader import load_rubric


def _empty_problem_extraction() -> str:
    rubric = load_rubric("prd")
    criterion = rubric.criterion("problem_statement")
    return json.dumps(
        {
            "criteria": [
                {
                    "criterion_id": criterion.id,
                    "fields": [
                        {"name": field.name, "value": None, "evidence": None}
                        for field in criterion.fields
                    ],
                }
            ]
        }
    )


def _problem_delta(turn) -> str:
    rubric = load_rubric("prd")
    criterion = rubric.criterion("problem_statement")
    answers = {
        pending.target_field: pending.answer.answer
        for pending in turn.state.pending_answers
    }
    values = {
        "problem": answers["problem"],
        "affected_users": answers["affected_users"],
        "evidence": answers["evidence"],
    }
    plan = prepare_checkpoint(turn.state)
    return json.dumps(
        {
            "delta_fingerprint": plan.delta_fingerprint,
            "criteria": [
                {
                    "criterion_id": criterion.id,
                    "fields": [
                        {
                            "name": field.name,
                            "value": values.get(field.name),
                            "evidence": (
                                {"quote": values[field.name]}
                                if field.name in values
                                else None
                            ),
                        }
                        for field in criterion.fields
                    ],
                }
            ],
        }
    )


def test_collects_gate_answers_without_rescoring_then_checkpoints(tmp_path):
    source = tmp_path / "prd.md"
    source.write_text("ORIGINAL_SECRET_BODY that must not enter a delta prompt.")
    turn = begin_remediation(str(source), _empty_problem_extraction())
    initial_score = turn.state.assessment.raw_score

    turn = record_answer(turn.state, "GenZ users lack short-form stories.")
    assert not turn.checkpoint_due
    assert not turn.score_is_current
    assert turn.state.assessment.raw_score == initial_score
    assert turn.next_question.target_field == "affected_users"

    turn = record_answer(turn.state, "Mobile-first GenZ viewers.")
    assert not turn.checkpoint_due
    assert turn.next_question.target_field == "evidence"

    turn = record_answer(turn.state, "38 support interviews requested it.")
    assert turn.checkpoint_due
    assert turn.checkpoint_reason == "failed_gate_fields_collected"
    assert turn.next_question is None
    assert turn.state.assessment.raw_score == initial_score

    plan = prepare_checkpoint(turn.state)
    assert "ORIGINAL_SECRET_BODY" not in plan.extraction_prompt
    assert "38 support interviews requested it." in plan.extraction_prompt
    assert plan.affected_criteria == ["problem_statement"]
    assert plan.input_character_count == len(plan.extraction_prompt)

    result = apply_checkpoint(turn.state, _problem_delta(turn))
    problem = next(
        item
        for item in result.state.assessment.criteria
        if item.criterion_id == "problem_statement"
    )
    assert problem.verdict.value == "present"
    assert not problem.gate_triggered
    assert len(result.credited_answer_ids) == 3
    assert result.uncredited_answer_ids == []
    assert result.state.pending_answers == []
    assert result.state.delta_extraction_count == 1
    assert result.state.delta_input_characters == plan.input_character_count
    assert result.state.assessment.confidence_basis == (
        "source_runs_plus_single_verified_deltas"
    )
    assert result.state.assessment.remediated_criteria == ["problem_statement"]
    assert problem.agreement_basis == "source_before_remediation"
    assert "not repeated independent full-document runs" in (
        result.state.report.confidence_note
    )
    assert result.next_question is not None


def test_delta_rejects_cross_criterion_evidence(tmp_path):
    source = tmp_path / "prd.md"
    source.write_text("A product note.")
    turn = begin_remediation(str(source), _empty_problem_extraction())
    turn = record_answer(turn.state, "A clear opportunity.", force_checkpoint=True)
    plan = prepare_checkpoint(turn.state)
    rubric = load_rubric("prd")
    criterion = rubric.criterion("problem_statement")
    payload = {
        "delta_fingerprint": plan.delta_fingerprint,
        "criteria": [
            {
                "criterion_id": criterion.id,
                "fields": [
                    {
                        "name": field.name,
                        "value": "A clear opportunity." if field.name == "evidence" else None,
                        "evidence": (
                            {"quote": "A clear opportunity."}
                            if field.name == "evidence"
                            else None
                        ),
                    }
                    for field in criterion.fields
                ],
            }
        ],
    }
    result = apply_checkpoint(turn.state, json.dumps(payload))
    # Same-criterion evidence is allowed but it cannot invent the other fields.
    problem = next(
        item
        for item in result.state.assessment.criteria
        if item.criterion_id == "problem_statement"
    )
    assert problem.verdict.value == "partial"
    assert problem.missing == ["problem", "affected_users"]


def test_source_change_invalidates_remediation_state(tmp_path):
    source = tmp_path / "prd.md"
    source.write_text("Initial")
    turn = begin_remediation(str(source), _empty_problem_extraction())
    source.write_text("Changed")

    try:
        record_answer(turn.state, "An answer")
    except ValueError as error:
        assert "source PRD changed" in str(error)
    else:
        raise AssertionError("source changes must invalidate remediation")


def test_begin_remediation_downgrades_unverified_positive_coverage(tmp_path):
    source = tmp_path / "prd.md"
    anchor = "Playback progress syncs with the backend every ten seconds."
    source.write_text(anchor)
    ledger = EdgeCaseCoverageLedger(
        items=[
            EdgeCaseCoverageItem(
                requirement_criterion_id="functional_requirements",
                requirement_field="primary_flows",
                requirement_quote=anchor,
                edge_case_id="connectivity_loss",
                status=CoverageStatus.COVERED,
                evidence_quote="Invented offline recovery behavior.",
            )
        ]
    )

    turn = begin_remediation(
        str(source),
        _empty_problem_extraction(),
        edge_case_coverage=ledger,
    )

    stored = turn.state.edge_case_coverage
    assert stored is not None
    assert stored.items[0].status is CoverageStatus.UNCLEAR
    assert stored.items[0].evidence_quote is None
    edge_result = next(
        item
        for item in turn.state.assessment.criteria
        if item.criterion_id == "edge_cases_and_states"
    )
    assert edge_result.verdict.value == "absent"
