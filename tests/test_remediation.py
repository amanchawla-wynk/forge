from __future__ import annotations

import json
import hashlib

import pytest

from forge.evaluate.models import (
    Applicability,
    AssertionOutcome,
    CriterionEvaluation,
    EvaluationConfidence,
    EvaluationGap,
    SemanticStatus,
)
from forge.remediation import (
    apply_checkpoint,
    begin_remediation,
    begin_remediation_prepared,
    _active_atomic_evaluations,
    prepare_checkpoint,
    record_answer,
)
from forge.score.edge_coverage import (
    CoverageStatus,
    EdgeCaseCoverageItem,
    EdgeCaseCoverageLedger,
)
from forge.rubric.loader import load_rubric
from forge.service import prepare_assessment


def _empty_problem_extraction() -> str:
    rubric = load_rubric("prd")
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
                for criterion in rubric.criteria
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
    values = answers
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


def _atomic_problem_evaluation(prepared, *, issue_ids: list[str] | None = None):
    issues = issue_ids or ["3" * 64]
    return CriterionEvaluation(
        evaluation_id="4" * 64,
        criterion_id="problem_statement",
        snapshot_id=prepared.snapshot.snapshot_id,
        rubric_id=prepared.rubric.id,
        rubric_version=prepared.rubric.version,
        plan_fingerprint=prepared.plan_fingerprint,
        run_ids=["run-1", "run-2", "run-3"],
        batch_ids=[batch.id for batch in prepared.batches],
        coverage_complete=True,
        applicability=Applicability.APPLICABLE,
        status=SemanticStatus.UNSUPPORTED,
        gaps=[
            EvaluationGap(
                gap_id=issue_id,
                assertion_ids=["problem"],
                kind="missing_decision",
                question="State the problem.",
            )
            for issue_id in issues
        ],
        assertion_outcomes=[
            AssertionOutcome(
                assertion_id="problem",
                status="gap",
                agreement=1,
                run_count=3,
                issue_ids=issues,
            )
        ],
        confidence=EvaluationConfidence(
            agreement=1,
            run_count=3,
            expected_run_count=3,
            basis="independent_evaluation_runs",
        ),
        origin="criterion_evaluation",
    )


def _atomic_problem_turn(tmp_path, *, issue_ids: list[str] | None = None):
    source = tmp_path / "prd.md"
    source.write_text("An incomplete product note.")
    prepared = prepare_assessment(str(source))
    target = _atomic_problem_evaluation(prepared, issue_ids=issue_ids)
    evaluations = [target]
    for criterion in prepared.rubric.criteria:
        if criterion.id == target.criterion_id:
            continue
        evaluations.append(
            CriterionEvaluation(
                evaluation_id=hashlib.sha256(criterion.id.encode()).hexdigest(),
                criterion_id=criterion.id,
                snapshot_id=prepared.snapshot.snapshot_id,
                rubric_id=prepared.rubric.id,
                rubric_version=prepared.rubric.version,
                plan_fingerprint=prepared.plan_fingerprint,
                run_ids=["run-1", "run-2", "run-3"],
                batch_ids=[batch.id for batch in prepared.batches],
                coverage_complete=True,
                applicability=Applicability.APPLICABLE,
                status=SemanticStatus.UNCLEAR,
                confidence=EvaluationConfidence(
                    agreement=1,
                    run_count=3,
                    expected_run_count=3,
                    basis="independent_evaluation_runs",
                ),
                origin="criterion_evaluation",
            )
        )
    return begin_remediation_prepared(
        prepared,
        _empty_problem_extraction(),
        question_mode="atomic_assertion",
        criterion_evaluations=evaluations,
    )


def test_atomic_mode_rejects_incomplete_evaluation_coverage(tmp_path):
    source = tmp_path / "prd.md"
    source.write_text("An incomplete product note.")
    prepared = prepare_assessment(str(source))

    with pytest.raises(ValueError, match="every rubric criterion exactly once"):
        begin_remediation_prepared(
            prepared,
            _empty_problem_extraction(),
            question_mode="atomic_assertion",
            criterion_evaluations=[_atomic_problem_evaluation(prepared)],
        )


def test_atomic_mode_uses_durable_deterministic_question_identity(tmp_path):
    turn = _atomic_problem_turn(tmp_path)

    assert turn.state.question_mode == "atomic_assertion"
    assert turn.next_question is not None
    assert turn.next_question.question_kind == "atomic_assertion"
    assert turn.next_question.question_id
    assert turn.next_question.plan_id
    assert turn.next_question.assertion_id == "problem"
    assert turn.next_question.issue_ids == ["3" * 64]
    assert turn.next_question.generation_mode == "deterministic_template"
    assert turn.next_question.score_effect == "none"


def test_atomic_answer_requires_exact_question_and_revision_binding(tmp_path):
    turn = _atomic_problem_turn(tmp_path)
    question = turn.next_question
    assert question is not None

    with pytest.raises(ValueError, match="question_id"):
        record_answer(
            turn.state,
            "Users cannot discover short stories.",
            question_id="0" * 64,
            evaluation_revision=question.evaluation_revision,
        )
    with pytest.raises(ValueError, match="evaluation_revision"):
        record_answer(
            turn.state,
            "Users cannot discover short stories.",
            question_id=question.question_id,
            evaluation_revision=question.evaluation_revision + 1,
        )

    answered = record_answer(
        turn.state,
        "Users cannot discover short stories.",
        question_id=question.question_id,
        evaluation_revision=question.evaluation_revision,
    )
    assert answered.checkpoint_due
    assert answered.checkpoint_reason == "atomic_answer_recorded"
    pending = answered.state.pending_answers[0]
    assert pending.question_id == question.question_id
    assert pending.plan_id == question.plan_id
    assert pending.assertion_id == question.assertion_id
    assert pending.issue_ids == question.issue_ids
    assert pending.evaluation_revision == question.evaluation_revision


def test_atomic_questions_close_only_rendered_issue_and_preserve_same_field_answers(
    tmp_path,
):
    issue_ids = ["3" * 64, "6" * 64]
    turn = _atomic_problem_turn(tmp_path, issue_ids=issue_ids)
    question = turn.next_question
    assert question is not None
    assert question.issue_ids == [issue_ids[0]]
    answered = record_answer(
        turn.state,
        "Users cannot discover short stories.",
        question_id=question.question_id,
        evaluation_revision=question.evaluation_revision,
    )

    result = apply_checkpoint(answered.state, _problem_delta(answered))

    assert result.credited_answer_ids
    assert len(result.state.atomic_resolutions) == 1
    resolution = result.state.atomic_resolutions[0]
    assert resolution.question_id == question.question_id
    assert resolution.issue_ids == [issue_ids[0]]
    assert resolution.answer_id == result.credited_answer_ids[0]
    second = result.next_question
    assert second is not None
    assert second.assertion_id == "problem"
    assert second.issue_ids == [issue_ids[1]]

    second_answer = "Authors cannot distinguish the current problem from the solution."
    answered_again = record_answer(
        result.state,
        second_answer,
        question_id=second.question_id,
        evaluation_revision=second.evaluation_revision,
    )
    final = apply_checkpoint(answered_again.state, _problem_delta(answered_again))

    assert [item.issue_ids for item in final.state.atomic_resolutions] == [
        [issue_ids[0]],
        [issue_ids[1]],
    ]
    problem = next(
        criterion
        for criterion in final.state.runs[0]
        if criterion.criterion_id == "problem_statement"
    ).field("problem")
    assert problem is not None
    assert problem.value == [
        "Users cannot discover short stories.",
        second_answer,
    ]
    assert len(problem.item_evidence) == 2


def test_atomic_answer_does_not_close_issue_from_another_field(tmp_path):
    turn = _atomic_problem_turn(tmp_path)
    question = turn.next_question
    assert question is not None
    answered = record_answer(
        turn.state,
        "Mobile viewers are affected.",
        question_id=question.question_id,
        evaluation_revision=question.evaluation_revision,
    )
    plan = prepare_checkpoint(answered.state)
    criterion = load_rubric("prd").criterion("problem_statement")
    delta = {
        "delta_fingerprint": plan.delta_fingerprint,
        "criteria": [
            {
                "criterion_id": criterion.id,
                "fields": [
                    {
                        "name": field.name,
                        "value": answered.state.pending_answers[0].answer.answer
                        if field.name == "affected_users"
                        else None,
                        "evidence": {
                            "quote": answered.state.pending_answers[0].answer.answer
                        }
                        if field.name == "affected_users"
                        else None,
                    }
                    for field in criterion.fields
                ],
            }
        ],
    }

    result = apply_checkpoint(answered.state, json.dumps(delta))

    assert result.credited_answer_ids == []
    assert result.state.atomic_resolutions == []
    assert result.next_question is not None
    assert result.next_question.assertion_id == "problem"


def test_atomic_resolutions_are_scoped_by_criterion(tmp_path):
    turn = _atomic_problem_turn(tmp_path)
    question = turn.next_question
    assert question is not None
    answered = record_answer(
        turn.state,
        "Users cannot discover short-form stories.",
        question_id=question.question_id,
        evaluation_revision=question.evaluation_revision,
    )
    resolved = apply_checkpoint(answered.state, _problem_delta(answered)).state
    other = next(
        item
        for item in resolved.criterion_evaluations
        if item.criterion_id == "success_metrics"
    ).model_copy(deep=True)
    other.assertion_outcomes = [
        AssertionOutcome(
            assertion_id="problem",
            status="gap",
            agreement=1,
            run_count=3,
            issue_ids=["7" * 64],
        )
    ]
    resolved.criterion_evaluations.append(other)

    active = _active_atomic_evaluations(resolved)
    cross_criterion = active[-1].assertion_outcomes[0]

    assert cross_criterion.status == "gap"
    assert cross_criterion.issue_ids == ["7" * 64]


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
    assert result.state.evaluation_revision == 1
    assert result.state.assessment.evaluation_revision == 1
    assert result.state.report.evaluation_revision == 1
    assert result.state.deep_review is not None
    assert result.state.deep_review.evaluation_revision == 1
    delta_claims = [
        claim
        for claim in result.state.deep_review.claims
        if claim.provenance == "supplemental_answer"
    ]
    assert len(delta_claims) == 3
    assert all(claim.run_indexes == [] for claim in delta_claims)
    assert all(
        claim.batch_ids == ["remediation-delta-1"] for claim in delta_claims
    )
    assert all(
        question.evaluation_revision == 1
        for question in result.state.question_queue
    )
    assert problem.agreement_basis == "source_before_remediation"
    assert "not repeated independent full-document runs" in (
        result.state.report.confidence_note
    )
    assert result.next_question is not None
    assert [answer.answer_id for answer in result.state.verified_answers] == (
        result.credited_answer_ids
    )
    problem_evidence_ids = {
        field.evidence.source_block_id
        for criterion in result.state.runs[0]
        if criterion.criterion_id == "problem_statement"
        for field in criterion.fields
        if field.evidence is not None
    }
    assert problem_evidence_ids == {
        f"supplemental-answer-{answer_id}"
        for answer_id in result.credited_answer_ids
    }

    later = record_answer(
        result.state,
        "Weekly active use rises from 20% to 30% within 90 days.",
        force_checkpoint=True,
    )
    pending = later.state.pending_answers[0]
    assert pending.answer.answer_id == pending.answer_id
    later_plan = prepare_checkpoint(later.state)
    later_criterion = load_rubric("prd").criterion(pending.answer.criterion_id)
    later_delta = {
        "delta_fingerprint": later_plan.delta_fingerprint,
        "criteria": [
            {
                "criterion_id": later_criterion.id,
                "fields": [
                    {
                        "name": field.name,
                        "value": pending.answer.answer
                        if field.name == pending.target_field
                        else None,
                        "evidence": {"quote": pending.answer.answer}
                        if field.name == pending.target_field
                        else None,
                    }
                    for field in later_criterion.fields
                ],
            }
        ],
    }
    later_result = apply_checkpoint(later.state, json.dumps(later_delta))
    rebuilt_problem_evidence_ids = {
        field.evidence.source_block_id
        for criterion in later_result.state.runs[0]
        if criterion.criterion_id == "problem_statement"
        for field in criterion.fields
        if field.evidence is not None
    }
    assert rebuilt_problem_evidence_ids == problem_evidence_ids
    restored = type(later_result.state).model_validate_json(
        later_result.state.model_dump_json()
    )
    assert restored.verified_answers == later_result.state.verified_answers


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


def test_each_uncovered_edge_case_cell_has_a_durable_queue_item(tmp_path):
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
                status=CoverageStatus.MISSING,
            ),
            EdgeCaseCoverageItem(
                requirement_criterion_id="functional_requirements",
                requirement_field="primary_flows",
                requirement_quote=anchor,
                edge_case_id="app_lifecycle",
                status=CoverageStatus.UNCLEAR,
            ),
        ]
    )

    turn = begin_remediation(
        str(source),
        _empty_problem_extraction(),
        edge_case_coverage=ledger,
    )
    edge_questions = [
        question
        for question in turn.state.question_queue
        if question.criterion_id == "edge_cases_and_states"
    ]

    assert [question.edge_case_id for question in edge_questions] == [
        "connectivity_loss",
        "app_lifecycle",
    ]
    assert all(
        question.target_field == "edge_case_coverage"
        for question in edge_questions
    )

    edge_only_state = turn.state.model_copy(
        update={"question_queue": edge_questions}, deep=True
    )
    answered = record_answer(edge_only_state, "Retry after reconnection.")
    assert answered.next_question is not None
    assert answered.next_question.edge_case_id == "app_lifecycle"
