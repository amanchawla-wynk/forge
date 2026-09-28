from __future__ import annotations

import json
import sqlite3

import pytest

from forge.extract.models import FieldExtraction
from forge.ingest.parsers import LegacyDocumentParser
from forge.remediation import (
    RemediationState,
    apply_checkpoint,
    begin_remediation,
    prepare_checkpoint,
    record_answer,
)
from forge.revise import revision_operation_temp_path
from forge.rubric.loader import load_rubric
from forge.sessions import (
    ClientBinding,
    ReviewSessionRepository,
    WorkflowState,
    status_for,
    workflow_for_turn,
)


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
    assert loaded.state.state_schema_version == 3
    assert loaded.state.evaluation_revision == 0
    assert loaded.state.source_snapshot == turn.state.source_snapshot
    assert loaded.state.source_snapshot.document.snapshot_id == turn.state.snapshot_id
    assert reopened.get_snapshot(turn.state.snapshot_id) == turn.state.source_snapshot
    with sqlite3.connect(repo.path) as connection:
        snapshot_row = connection.execute(
            "SELECT snapshot_json FROM document_snapshots WHERE snapshot_id = ?",
            (turn.state.snapshot_id,),
        ).fetchone()
    assert snapshot_row is not None
    assert '"content"' in snapshot_row[0]


def test_shared_snapshot_rebinds_origin_for_each_session_after_restart(tmp_path):
    first = tmp_path / "first.md"
    second = tmp_path / "nested" / "second.md"
    second.parent.mkdir()
    first.write_text("An incomplete product note.")
    second.write_bytes(first.read_bytes())
    repository = ReviewSessionRepository(tmp_path / "reviews.sqlite3")

    first_session = repository.create(
        begin_remediation(str(first), _empty_problem_extraction()).state
    )
    second_session = repository.create(
        begin_remediation(str(second), _empty_problem_extraction()).state
    )
    assert first_session.state.snapshot_id == second_session.state.snapshot_id

    reopened = ReviewSessionRepository(tmp_path / "reviews.sqlite3")
    loaded_first = reopened.get(first_session.review_session_id)
    loaded_second = reopened.get(second_session.review_session_id)

    first_snapshot = loaded_first.state.source_snapshot
    second_snapshot = loaded_second.state.source_snapshot
    assert first_snapshot is not None
    assert second_snapshot is not None
    assert first_snapshot.snapshot_id == second_snapshot.snapshot_id
    assert first_snapshot.source.origin_locator == str(first.resolve())
    assert first_snapshot.source.display_name == first.name
    assert first_snapshot.document.source_path == str(first.resolve())
    assert second_snapshot.source.origin_locator == str(second.resolve())
    assert second_snapshot.source.display_name == second.name
    assert second_snapshot.document.source_path == str(second.resolve())
    with sqlite3.connect(repository.path) as connection:
        row_count = connection.execute(
            "SELECT COUNT(*) FROM document_snapshots"
        ).fetchone()[0]
    assert row_count == 1


def test_checkpoint_after_restart_does_not_call_parser(
    prd, tmp_path, repo, monkeypatch
):
    turn = record_answer(
        begin_remediation(str(prd), _empty_problem_extraction()).state,
        "GenZ viewers cannot find short-form stories.",
    )
    created = repo.create(turn.state)
    reopened = ReviewSessionRepository(tmp_path / "reviews.sqlite3")
    loaded = reopened.get(created.review_session_id)

    def fail_parse(parser, artifact):
        raise AssertionError("checkpoint reparsed the source")

    monkeypatch.setattr(LegacyDocumentParser, "parse", fail_parse)
    plan = prepare_checkpoint(loaded.state)
    criterion = load_rubric("prd").criterion("problem_statement")
    delta = {
        "delta_fingerprint": plan.delta_fingerprint,
        "criteria": [
            {
                "criterion_id": criterion.id,
                "fields": [
                    {
                        "name": field.name,
                        "value": (
                            "GenZ viewers cannot find short-form stories."
                            if field.name == "problem"
                            else None
                        ),
                        "evidence": (
                            {"quote": "GenZ viewers cannot find short-form stories."}
                            if field.name == "problem"
                            else None
                        ),
                    }
                    for field in criterion.fields
                ],
            }
        ],
    }

    result = apply_checkpoint(loaded.state, json.dumps(delta))

    assert result.state.evaluation_revision == 1
    assert result.state.source_snapshot == loaded.state.source_snapshot


def test_state_schema_column_is_authoritative_for_existing_v1_rows(
    prd, tmp_path, repo
):
    turn = begin_remediation(str(prd), _empty_problem_extraction())
    created = repo.create(turn.state)
    state = json.loads(turn.state.model_dump_json())
    state.pop("state_schema_version")
    with sqlite3.connect(repo.path) as connection:
        connection.execute(
            "UPDATE review_sessions SET state_schema_version = 1, state_json = ? "
            "WHERE review_session_id = ?",
            (json.dumps(state), created.review_session_id),
        )

    reopened = ReviewSessionRepository(tmp_path / "reviews.sqlite3")
    loaded = reopened.get(created.review_session_id)

    assert loaded.state.state_schema_version == 1


def test_loaded_v1_pending_answer_recovers_nested_identity_before_checkpoint(
    prd, repo
):
    turn = record_answer(
        begin_remediation(str(prd), _empty_problem_extraction()).state,
        "GenZ viewers cannot find short-form stories.",
    )
    created = repo.create(turn.state)
    state = json.loads(turn.state.model_dump_json())
    answer_id = state["pending_answers"][0]["answer_id"]
    state["pending_answers"][0]["answer"].pop("answer_id")
    state.pop("state_schema_version")
    with sqlite3.connect(repo.path) as connection:
        connection.execute(
            "UPDATE review_sessions SET state_schema_version = 1, state_json = ? "
            "WHERE review_session_id = ?",
            (json.dumps(state), created.review_session_id),
        )

    loaded = repo.get(created.review_session_id)
    assert loaded.state.state_schema_version == 1
    assert loaded.state.pending_answers[0].answer.answer_id == answer_id

    plan = prepare_checkpoint(loaded.state)
    criterion = load_rubric("prd").criterion("problem_statement")
    delta = {
        "delta_fingerprint": plan.delta_fingerprint,
        "criteria": [
            {
                "criterion_id": criterion.id,
                "fields": [
                    {
                        "name": field.name,
                        "value": (
                            "GenZ viewers cannot find short-form stories."
                            if field.name == "problem"
                            else None
                        ),
                        "evidence": (
                            {"quote": "GenZ viewers cannot find short-form stories."}
                            if field.name == "problem"
                            else None
                        ),
                    }
                    for field in criterion.fields
                ],
            }
        ],
    }
    result = apply_checkpoint(loaded.state, json.dumps(delta))
    assert result.credited_answer_ids == [answer_id]
    assert result.state.verified_answers[0].answer_id == answer_id


@pytest.mark.parametrize(
    "workflow",
    [
        WorkflowState.AWAITING_DELTA_EXTRACTION,
        WorkflowState.AWAITING_REVISION_APPROVAL,
        WorkflowState.FINAL_ASSESSMENT_REQUIRED,
        WorkflowState.COMPLETE,
    ],
)
def test_resume_preserves_terminal_revision_workflow(prd, repo, workflow):
    turn = begin_remediation(str(prd), _empty_problem_extraction())
    created = repo.create(turn.state)
    phased = repo.update(
        created.review_session_id,
        expected_version=created.session_version,
        operation_id=f"phase-{workflow.value}",
        state=created.state,
        workflow_state=workflow,
        event_type="test_phase",
        result_json="{}",
    )

    resumed = repo.resume(
        phased.review_session_id,
        source_path=str(prd),
        client_binding=ClientBinding(client_name="opencode"),
        confirm_client_change=False,
        expected_version=phased.session_version,
        operation_id=f"resume-{workflow.value}",
    )

    assert resumed.workflow_state is workflow
    assert resumed.next_action == phased.next_action


def test_verified_item_evidence_survives_state_and_sqlite_round_trips(tmp_path):
    source = tmp_path / "prd.md"
    source.write_text("Web is out of scope. Offline downloads are excluded.")
    criteria = json.loads(_empty_problem_extraction())["criteria"]
    non_goals = next(
        criterion
        for criterion in criteria
        if criterion["criterion_id"] == "non_goals"
    )
    non_goals["fields"] = [
        {
            "name": "non_goals",
            "value": ["Web is out of scope.", "Offline downloads are excluded."],
            "evidence": {"quote": "Web is out of scope."},
        }
    ]

    turn = begin_remediation(str(source), json.dumps({"criteria": criteria}))
    field = next(
        criterion.field("non_goals")
        for criterion in turn.state.runs[0]
        if criterion.criterion_id == "non_goals"
    )
    assert field is not None
    assert [evidence.quote for evidence in field.item_evidence] == [
        "Web is out of scope.",
        "Offline downloads are excluded.",
    ]

    restored = RemediationState.model_validate_json(turn.state.model_dump_json())
    restored_field = next(
        criterion.field("non_goals")
        for criterion in restored.runs[0]
        if criterion.criterion_id == "non_goals"
    )
    assert restored_field is not None
    assert restored_field.item_evidence == field.item_evidence

    repository = ReviewSessionRepository(tmp_path / "item-evidence.sqlite3")
    assert "source_snapshot" not in turn.state.model_dump()
    restored.source_snapshot = turn.state.source_snapshot
    created = repository.create(restored)
    loaded = repository.get(created.review_session_id)
    loaded_field = next(
        criterion.field("non_goals")
        for criterion in loaded.state.runs[0]
        if criterion.criterion_id == "non_goals"
    )
    assert loaded_field is not None
    assert loaded_field.item_evidence == field.item_evidence
    assert "item_evidence" not in FieldExtraction.model_json_schema()["properties"]


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


def test_parser_fingerprint_mismatch_is_discoverable_but_blocks_resume(
    prd, repo, monkeypatch
):
    session = repo.create(begin_remediation(str(prd), _empty_problem_extraction()).state)
    monkeypatch.setattr(LegacyDocumentParser, "fingerprint", "test-parser/changed")

    matches = repo.find(str(prd))

    assert len(matches) == 1
    assert matches[0].compatible is False
    assert "parser fingerprint changed" in matches[0].incompatibility_reasons
    with pytest.raises(ValueError, match="parser fingerprint changed"):
        repo.resume(
            session.review_session_id,
            source_path=str(prd),
            client_binding=ClientBinding(client_name="opencode"),
            confirm_client_change=False,
            expected_version=session.session_version,
            operation_id="resume-parser-mismatch",
        )


def test_normalized_mismatch_is_discoverable_but_blocks_resume(
    prd, repo, monkeypatch
):
    session = repo.create(begin_remediation(str(prd), _empty_problem_extraction()).state)
    original_parse = LegacyDocumentParser.parse

    def changed_parse(parser, artifact):
        parsed = original_parse(parser, artifact)
        block = parsed.document.blocks[0].model_copy(
            update={"text": parsed.document.blocks[0].text + " Normalized drift."}
        )
        return parsed.model_copy(
            update={
                "document": parsed.document.model_copy(update={"blocks": [block]})
            }
        )

    monkeypatch.setattr(LegacyDocumentParser, "parse", changed_parse)

    matches = repo.find(str(prd))

    assert matches[0].compatible is False
    assert "normalized document changed" in matches[0].incompatibility_reasons
    with pytest.raises(ValueError, match="normalized document changed"):
        repo.resume(
            session.review_session_id,
            source_path=str(prd),
            client_binding=ClientBinding(client_name="opencode"),
            confirm_client_change=False,
            expected_version=session.session_version,
            operation_id="resume-normalized-mismatch",
        )


def test_rows_without_snapshot_columns_remain_explicitly_legacy(prd, repo):
    session = repo.create(begin_remediation(str(prd), _empty_problem_extraction()).state)
    with sqlite3.connect(repo.path) as connection:
        connection.execute(
            "UPDATE review_sessions SET snapshot_id = NULL, "
            "parser_fingerprint = NULL, normalized_hash = NULL "
            "WHERE review_session_id = ?",
            (session.review_session_id,),
        )

    loaded = repo.get(session.review_session_id)
    matches = repo.find(str(prd))

    assert loaded.state.snapshot_id is None
    assert loaded.state.parser_fingerprint is None
    assert loaded.state.normalized_hash is None
    assert loaded.state.source_snapshot is None
    assert matches[0].compatible is False
    assert matches[0].incompatibility_reasons == [
        "legacy session has no durable snapshot identity"
    ]
    with pytest.raises(ValueError, match="legacy session"):
        repo.resume(
            session.review_session_id,
            source_path=str(prd),
            client_binding=ClientBinding(client_name="opencode"),
            confirm_client_change=False,
            expected_version=session.session_version,
            operation_id="resume-legacy",
        )


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


def test_pending_operation_blocks_duplicate_external_work(prd, repo):
    turn = begin_remediation(str(prd), _empty_problem_extraction())
    session = repo.create(turn.state)
    digest = "request-digest"

    repo.reserve_operation(
        session.review_session_id,
        expected_version=session.session_version,
        operation_id="checkpoint-1",
        operation_type="dashboard_checkpoint",
        request_digest=digest,
    )

    with pytest.raises(ValueError, match="already in progress"):
        repo.operation_result(
            session.review_session_id,
            "checkpoint-1",
            operation_type="dashboard_checkpoint",
            request_digest=digest,
        )
    with pytest.raises(ValueError, match="different request payload"):
        repo.operation_result(
            session.review_session_id,
            "checkpoint-1",
            operation_type="dashboard_checkpoint",
            request_digest="different",
        )


def test_delete_unlinks_only_the_exact_pending_revision_temp(prd, tmp_path, repo):
    session = repo.create(begin_remediation(str(prd), _empty_problem_extraction()).state)
    output = tmp_path / "revised.md"
    safe_temp = revision_operation_temp_path(
        output, session.review_session_id, "write-safe"
    )
    safe_temp.write_text("staged")
    arbitrary = tmp_path / "keep-me.md"
    arbitrary.write_text("unrelated")
    repo.reserve_operation(
        session.review_session_id,
        expected_version=session.session_version,
        operation_id="write-safe",
        operation_type="write_revision",
        request_digest="safe",
        metadata={"output_path": str(output), "temp_path": str(safe_temp)},
    )
    with sqlite3.connect(repo.path) as connection:
        connection.execute(
            "INSERT INTO review_operations "
            "(review_session_id, operation_id, operation_type, request_digest, "
            "status, result_json, metadata_json, created_at) "
            "VALUES (?, ?, 'write_revision', 'unsafe', 'pending', '', ?, 0)",
            (
                session.review_session_id,
                "write-unsafe",
                json.dumps(
                    {"output_path": str(output), "temp_path": str(arbitrary)}
                ),
            ),
        )

    repo.delete(session.review_session_id)

    assert not safe_temp.exists()
    assert arbitrary.read_text() == "unrelated"


def test_purge_expired_unlinks_pending_revision_temp(prd, tmp_path, repo):
    session = repo.create(begin_remediation(str(prd), _empty_problem_extraction()).state)
    output = tmp_path / "expired-revised.md"
    temp = revision_operation_temp_path(output, session.review_session_id, "write-expired")
    temp.write_text("staged")
    repo.reserve_operation(
        session.review_session_id,
        expected_version=session.session_version,
        operation_id="write-expired",
        operation_type="write_revision",
        request_digest="expired",
        metadata={"output_path": str(output), "temp_path": str(temp)},
    )
    with sqlite3.connect(repo.path) as connection:
        connection.execute(
            "UPDATE review_sessions SET expires_at = 0 WHERE review_session_id = ?",
            (session.review_session_id,),
        )

    assert repo.purge_expired() == 1
    assert not temp.exists()
