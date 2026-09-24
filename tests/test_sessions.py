from __future__ import annotations

import json

import pytest

from forge.remediation import begin_remediation, record_answer
from forge.rubric.loader import load_rubric
from forge.sessions import (
    ClientBinding,
    ReviewSessionRepository,
    WorkflowState,
    status_for,
    workflow_for_turn,
)


def _empty_problem_extraction() -> str:
    criterion = load_rubric("prd").criterion("problem_statement")
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


@pytest.fixture
def prd(tmp_path):
    source = tmp_path / "prd.md"
    source.write_text("An incomplete product note.")
    return source


@pytest.fixture
def repo(tmp_path):
    return ReviewSessionRepository(tmp_path / "reviews.sqlite3")


def test_session_survives_a_process_restart(prd, tmp_path, repo):
    turn = begin_remediation(str(prd), _empty_problem_extraction())
    created = repo.create(turn.state)

    # A new repository object is what a restarted Forge process would build.
    reopened = ReviewSessionRepository(tmp_path / "reviews.sqlite3")
    loaded = reopened.get(created.review_session_id)

    assert loaded.review_session_id == created.review_session_id
    assert loaded.session_version == 1
    assert loaded.state.source_sha256 == turn.state.source_sha256
    assert loaded.workflow_state is WorkflowState.AWAITING_ANSWER
    assert loaded.next_action.type == "ask_question"


def test_stale_session_version_is_rejected(prd, repo):
    turn = begin_remediation(str(prd), _empty_problem_extraction())
    session = repo.create(turn.state)
    answered = record_answer(session.state, "GenZ viewers lack short-form stories.")

    repo.update(
        session.review_session_id,
        expected_version=1,
        operation_id="op-1",
        state=answered.state,
        workflow_state=workflow_for_turn(answered),
        event_type="answer_recorded",
        result_json="{}",
    )

    with pytest.raises(ValueError, match="stale session_version"):
        repo.update(
            session.review_session_id,
            expected_version=1,
            operation_id="op-2",
            state=answered.state,
            workflow_state=workflow_for_turn(answered),
            event_type="answer_recorded",
            result_json="{}",
        )


def test_duplicate_operation_id_is_applied_once(prd, repo):
    turn = begin_remediation(str(prd), _empty_problem_extraction())
    session = repo.create(turn.state)
    answered = record_answer(session.state, "GenZ viewers lack short-form stories.")

    first = repo.update(
        session.review_session_id,
        expected_version=1,
        operation_id="answer-abc",
        state=answered.state,
        workflow_state=workflow_for_turn(answered),
        event_type="answer_recorded",
        result_json="{}",
    )
    replay = repo.update(
        session.review_session_id,
        expected_version=1,
        operation_id="answer-abc",
        state=answered.state,
        workflow_state=workflow_for_turn(answered),
        event_type="answer_recorded",
        result_json="{}",
    )

    assert first.session_version == 2
    assert replay.session_version == 2
    assert len(replay.state.pending_answers) == 1


def test_find_matches_only_the_exact_source_and_workspace(prd, tmp_path, repo):
    turn = begin_remediation(str(prd), _empty_problem_extraction())
    repo.create(turn.state)

    same_name_elsewhere = tmp_path / "other" / "prd.md"
    same_name_elsewhere.parent.mkdir()
    same_name_elsewhere.write_text("A different product note.")

    assert len(repo.find(str(prd))) == 1
    assert repo.find(str(same_name_elsewhere)) == []


def test_edited_source_no_longer_matches_its_review(prd, repo):
    turn = begin_remediation(str(prd), _empty_problem_extraction())
    repo.create(turn.state)
    assert len(repo.find(str(prd))) == 1

    prd.write_text("The PRD was edited after the review started.")

    assert repo.find(str(prd)) == []


def test_resume_requires_confirmation_when_the_client_changes(prd, repo):
    turn = begin_remediation(str(prd), _empty_problem_extraction())
    session = repo.create(
        turn.state, client_binding=ClientBinding(client_name="opencode")
    )

    with pytest.raises(ValueError, match="confirm_client_change"):
        repo.resume(
            session.review_session_id,
            source_path=str(prd),
            client_binding=ClientBinding(client_name="cursor"),
            confirm_client_change=False,
            expected_version=session.session_version,
            operation_id="resume-1",
        )

    resumed = repo.resume(
        session.review_session_id,
        source_path=str(prd),
        client_binding=ClientBinding(client_name="cursor"),
        confirm_client_change=True,
        expected_version=session.session_version,
        operation_id="resume-2",
    )

    assert resumed.client_binding.client_name == "cursor"
    assert any(
        event["event_type"] == "client_binding_changed"
        for event in repo.events(session.review_session_id)
    )


def test_resume_rejects_a_different_document(prd, tmp_path, repo):
    turn = begin_remediation(str(prd), _empty_problem_extraction())
    session = repo.create(turn.state)
    other = tmp_path / "other.md"
    other.write_text("A different PRD entirely.")

    with pytest.raises(ValueError, match="different source document"):
        repo.resume(
            session.review_session_id,
            source_path=str(other),
            client_binding=ClientBinding(client_name="opencode"),
            confirm_client_change=True,
            expected_version=session.session_version,
            operation_id="resume-3",
        )


def test_status_reports_next_question_and_action(prd, repo):
    turn = begin_remediation(str(prd), _empty_problem_extraction())
    session = repo.create(turn.state)

    status = status_for(session)

    assert status.workflow_state is WorkflowState.AWAITING_ANSWER
    assert status.next_action.type == "ask_question"
    assert status.next_question is not None
    assert status.pending_answer_count == 0
