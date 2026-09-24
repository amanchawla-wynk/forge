from __future__ import annotations

from fastapi.testclient import TestClient

from forge_dashboard.app import app
from forge_dashboard.llm import Completion
from forge.sessions import WorkflowState


def _client(monkeypatch) -> TestClient:
    async def fake_call_model(config, prompt, *, max_tokens, temperature=0):
        return Completion(text='{"criteria": []}', model="claude-test")

    # runner.py and app.py each import `call_model` by reference, so both
    # bindings need patching independently.
    monkeypatch.setattr("forge_dashboard.runner.call_model", fake_call_model)
    monkeypatch.setattr("forge_dashboard.app.call_model", fake_call_model)
    return TestClient(app)


def _mark_revision_ready(review_session_id: str, session_version: int) -> int:
    import forge_dashboard.app as dashboard

    session = dashboard._reviews().get(review_session_id)
    updated = dashboard._reviews().update(
        review_session_id,
        expected_version=session_version,
        operation_id="test-revision-ready",
        state=session.state,
        workflow_state=WorkflowState.REVISION_READY,
        event_type="test_revision_ready",
        result_json="{}",
    )
    return updated.session_version


def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_upload_and_assess_round_trip(monkeypatch) -> None:
    client = _client(monkeypatch)

    upload = client.post(
        "/api/documents",
        files={"file": ("prd.md", b"A short and incomplete product note.", "text/markdown")},
    )
    assert upload.status_code == 200
    body = upload.json()
    assert body["filename"] == "prd.md"
    assert body["source_type"] == "md"
    document_id = body["document_id"]

    assessment = client.post(
        "/api/assessments",
        json={
            "document_id": document_id,
            "llm": {
                "provider": "anthropic",
                "model": "claude-3-5-sonnet",
                "api_key": "sk-test-not-real",
            },
            "supplemental_answers": [],
        },
    )
    assert assessment.status_code == 200
    payload = assessment.json()
    assert payload["document_id"] == document_id
    # The browser must never learn the server's on-disk path.
    assert payload["source_path"] == "prd.md"
    assert payload["run_count"] == 3
    assert payload["next_question"] is not None
    assert payload["client_models"] == ["claude-test", "claude-test", "claude-test"]
    # The API key must never be echoed back.
    assert "sk-test-not-real" not in assessment.text


def test_recording_answer_does_not_call_model_until_checkpoint(monkeypatch) -> None:
    calls = 0

    async def fake_call_model(config, prompt, *, max_tokens, temperature=0):
        nonlocal calls
        calls += 1
        return Completion(text='{"criteria": []}', model="claude-test")

    monkeypatch.setattr("forge_dashboard.runner.call_model", fake_call_model)
    monkeypatch.setattr("forge_dashboard.app.call_model", fake_call_model)
    client = TestClient(app)
    upload = client.post(
        "/api/documents",
        files={"file": ("prd.md", b"An incomplete product note.", "text/markdown")},
    )
    document_id = upload.json()["document_id"]
    assessment = client.post(
        "/api/assessments",
        json={
            "document_id": document_id,
            "llm": {
                "provider": "anthropic",
                "model": "claude-test",
                "api_key": "sk-test",
            },
        },
    )
    session_id = assessment.json()["review_session_id"]
    session_version = assessment.json()["session_version"]
    calls_after_assessment = calls

    recorded = client.post(
        f"/api/remediation/{session_id}/answers",
        json={
            "session_version": session_version,
            "operation_id": "answer-1",
            "answer": "GenZ viewers need short-form stories.",
        },
    )

    assert recorded.status_code == 200
    assert recorded.json()["turn"]["pending_answer_count"] == 1
    assert recorded.json()["turn"]["score_is_current"] is False
    assert calls == calls_after_assessment


def test_exact_document_review_requires_explicit_resume_or_start_new(monkeypatch) -> None:
    client = _client(monkeypatch)
    llm = {
        "provider": "anthropic",
        "model": "claude-test",
        "api_key": "sk-test",
    }
    content = b"An incomplete product note with stable content."
    first_document = client.post(
        "/api/documents",
        files={"file": ("prd.md", content, "text/markdown")},
    ).json()
    first = client.post(
        "/api/assessments",
        json={"document_id": first_document["document_id"], "llm": llm},
    )
    assert first.status_code == 200
    review_id = first.json()["review_session_id"]

    # A new tab may upload the same bytes under a new document id. Discovery
    # matches by source hash and workspace rather than filename or recency.
    second_document = client.post(
        "/api/documents",
        files={"file": ("renamed.md", content, "text/markdown")},
    ).json()
    discovery = client.get(
        f"/api/documents/{second_document['document_id']}/reviews"
    )
    assert discovery.status_code == 200
    assert [item["review_session_id"] for item in discovery.json()["matches"]] == [
        review_id
    ]
    assert "source_path" not in discovery.json()["matches"][0]
    assert "source_sha256" not in discovery.json()["matches"][0]
    assert discovery.json()["choices"] == [
        "resume_review",
        "start_new_review",
        "cancel",
    ]

    implicit = client.post(
        "/api/assessments",
        json={"document_id": second_document["document_id"], "llm": llm},
    )
    assert implicit.status_code == 409

    resumed = client.post(
        f"/api/documents/{second_document['document_id']}/reviews/{review_id}/resume",
        json={"operation_id": "resume-dashboard-1"},
    )
    assert resumed.status_code == 200
    assert resumed.json()["review_session_id"] == review_id
    assert resumed.json()["next_action"]["type"] == "ask_question"


def test_dashboard_documents_reviews_and_revision_plans_survive_restart(
    monkeypatch,
) -> None:
    import forge_dashboard.app as dashboard
    from forge_dashboard.storage import DocumentStore

    client = _client(monkeypatch)
    llm = {
        "provider": "anthropic",
        "model": "claude-test",
        "api_key": "sk-test",
    }
    upload = client.post(
        "/api/documents",
        files={
            "file": (
                "prd.md",
                b"# PRD\n\n## Success Metrics\n\nDAU is monitored.\n",
                "text/markdown",
            )
        },
    ).json()
    assessment = client.post(
        "/api/assessments",
        json={"document_id": upload["document_id"], "llm": llm},
    ).json()
    revision_version = _mark_revision_ready(
        assessment["review_session_id"], assessment["session_version"]
    )
    preview = client.post(
        f"/api/documents/{upload['document_id']}/revisions/preview",
        json={
            "review_session_id": assessment["review_session_id"],
            "session_version": revision_version,
            "operation_id": "preview-restart",
            "supplemental_answers": [
                {
                    "criterion_id": "success_metrics",
                    "answer": "Repeat usage rises from 20% to 30% within 90 days.",
                }
            ]
        },
    ).json()

    root = dashboard._store.root
    monkeypatch.setattr(dashboard, "_store", DocumentStore(root))
    monkeypatch.setattr(dashboard, "_review_repository", None)

    assert client.get(
        f"/api/documents/{upload['document_id']}/download"
    ).status_code == 200
    discovery = client.get(
        f"/api/documents/{upload['document_id']}/reviews"
    ).json()
    assert discovery["matches"][0]["review_session_id"] == assessment[
        "review_session_id"
    ]
    planned_document_id, restored_plan = dashboard._store.get_revision_plan(
        preview["plan_id"]
    )
    assert planned_document_id == upload["document_id"]
    assert restored_plan.plan_digest == preview["plan_digest"]


def test_dashboard_answer_retry_is_idempotent_and_stale_versions_fail(monkeypatch) -> None:
    client = _client(monkeypatch)
    upload = client.post(
        "/api/documents",
        files={"file": ("prd.md", b"An incomplete note.", "text/markdown")},
    ).json()
    assessment = client.post(
        "/api/assessments",
        json={
            "document_id": upload["document_id"],
            "llm": {
                "provider": "anthropic",
                "model": "claude-test",
                "api_key": "sk-test",
            },
        },
    ).json()
    review_id = assessment["review_session_id"]
    payload = {
        "session_version": assessment["session_version"],
        "operation_id": "answer-retry-1",
        "answer": "GenZ viewers need short-form stories.",
    }
    first = client.post(f"/api/remediation/{review_id}/answers", json=payload)
    retry = client.post(f"/api/remediation/{review_id}/answers", json=payload)
    assert first.status_code == retry.status_code == 200
    assert retry.json()["session_version"] == first.json()["session_version"]
    assert retry.json()["turn"]["pending_answer_count"] == 1

    changed_replay = client.post(
        f"/api/remediation/{review_id}/answers",
        json={**payload, "answer": "A different answer under the same id."},
    )
    assert changed_replay.status_code == 400
    assert "different request payload" in changed_replay.json()["detail"]

    stale = client.post(
        f"/api/remediation/{review_id}/answers",
        json={**payload, "operation_id": "answer-stale-2"},
    )
    assert stale.status_code == 400
    assert "stale session_version" in stale.json()["detail"]


def test_revision_preview_materializes_copy_and_reassesses(monkeypatch) -> None:
    client = _client(monkeypatch)
    original = b"# PRD\n\n## Success Metrics\n\nDAU is monitored.\n"
    upload = client.post(
        "/api/documents",
        files={"file": ("prd.md", original, "text/markdown")},
    ).json()
    assessment = client.post(
        "/api/assessments",
        json={
            "document_id": upload["document_id"],
            "llm": {
                "provider": "anthropic",
                "model": "claude-test",
                "api_key": "sk-test",
            },
        },
    ).json()
    revision_version = _mark_revision_ready(
        assessment["review_session_id"], assessment["session_version"]
    )
    answer = "Repeat usage should increase from 20% to 30% within 90 days."
    preview = client.post(
        f"/api/documents/{upload['document_id']}/revisions/preview",
        json={
            "review_session_id": assessment["review_session_id"],
            "session_version": revision_version,
            "operation_id": "preview-final",
            "supplemental_answers": [
                {"criterion_id": "success_metrics", "answer": answer}
            ]
        },
    )
    assert preview.status_code == 200
    plan = preview.json()
    edit = plan["edits"][0]
    assert edit["target_section"] == "Success Metrics"

    revised = client.post(
        f"/api/documents/{upload['document_id']}/revisions",
        json={
            "review_session_id": assessment["review_session_id"],
            "session_version": plan["session_version"],
            "operation_id": "materialize-final",
            "plan_id": plan["plan_id"],
            "actions": {edit["edit_id"]: "integrate"},
            "llm": {
                "provider": "anthropic",
                "model": "claude-test",
                "api_key": "sk-test",
            },
        },
    )
    assert revised.status_code == 200
    body = revised.json()
    assert body["revision"]["mode"] == "integrated"
    assert body["revision"]["final_assessment_required"] is True
    assert body["assessment"]["supplemental_answers"] == []
    assert body["assessment"]["source_path"] == "prd - Forge Revision.md"
    import forge_dashboard.app as dashboard

    original_review = dashboard._reviews().get(assessment["review_session_id"])
    assert original_review.workflow_state is WorkflowState.COMPLETE
    artifacts = dashboard._store.review_artifacts(assessment["review_session_id"])
    assert artifacts == [
        {
            "plan_id": plan["plan_id"],
            "source_document_id": upload["document_id"],
            "generated_document_id": body["document_id"],
            "final_review_session_id": body["assessment"]["review_session_id"],
        }
    ]

    download = client.get(f"/api/documents/{body['document_id']}/download")
    assert download.status_code == 200
    assert answer.encode() in download.content
    assert original == client.get(
        f"/api/documents/{upload['document_id']}/download"
    ).content


def test_upload_rejects_unsupported_extension(monkeypatch) -> None:
    client = _client(monkeypatch)
    response = client.post(
        "/api/documents", files={"file": ("prd.exe", b"binary", "application/octet-stream")}
    )
    assert response.status_code == 400
    assert "unsupported document type" in response.json()["detail"]


def test_upload_limit_and_document_deletion(monkeypatch) -> None:
    import forge_dashboard.app as dashboard

    client = _client(monkeypatch)
    monkeypatch.setattr(dashboard, "_MAX_UPLOAD_BYTES", 4)
    oversized = client.post(
        "/api/documents",
        files={"file": ("prd.md", b"12345", "text/markdown")},
    )
    assert oversized.status_code == 413

    allowed = client.post(
        "/api/documents",
        files={"file": ("prd.md", b"1234", "text/markdown")},
    ).json()
    deleted = client.delete(f"/api/documents/{allowed['document_id']}")
    assert deleted.status_code == 200
    assert client.get(
        f"/api/documents/{allowed['document_id']}/download"
    ).status_code == 404


def test_assess_rejects_unknown_document_id(monkeypatch) -> None:
    client = _client(monkeypatch)
    response = client.post(
        "/api/assessments",
        json={
            "document_id": "does-not-exist",
            "llm": {
                "provider": "openai",
                "model": "gpt-4o",
                "api_key": "sk-test",
            },
        },
    )
    assert response.status_code == 404


def test_verify_llm_reports_ok(monkeypatch) -> None:
    client = _client(monkeypatch)
    response = client.post(
        "/api/llm/verify",
        json={"provider": "anthropic", "model": "claude-sonnet-5", "api_key": "sk-test"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["model"] == "claude-test"


def test_verify_llm_reports_failure_as_502(monkeypatch) -> None:
    from forge_dashboard.llm import LLMCallError

    async def failing_call_model(config, prompt, *, max_tokens, temperature=0):
        raise LLMCallError("openai model call failed: AuthenticationError: bad key")

    monkeypatch.setattr("forge_dashboard.app.call_model", failing_call_model)
    client = TestClient(app)

    response = client.post(
        "/api/llm/verify",
        json={"provider": "openai", "model": "gpt-6-sol", "api_key": "sk-bad"},
    )
    assert response.status_code == 502
    assert "bad key" in response.json()["detail"]


def test_verify_llm_allows_blank_model_for_cursor(monkeypatch) -> None:
    async def fake_call_model(config, prompt, *, max_tokens, temperature=0):
        assert config.provider == "cursor"
        from forge_dashboard.llm import Completion

        return Completion(text="OK", model="cursor-default")

    monkeypatch.setattr("forge_dashboard.app.call_model", fake_call_model)
    client = TestClient(app)

    response = client.post(
        "/api/llm/verify",
        json={"provider": "cursor", "model": "", "api_key": "cursor-key"},
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "model": "cursor-default"}


def test_llm_config_requires_model_for_direct_providers(monkeypatch) -> None:
    client = _client(monkeypatch)
    response = client.post(
        "/api/llm/verify",
        json={"provider": "anthropic", "model": "", "api_key": "sk-test"},
    )
    assert response.status_code == 422


def test_assess_reports_model_failures_as_502(monkeypatch) -> None:
    from forge_dashboard.llm import LLMCallError

    async def failing_call_model(config, prompt, *, max_tokens, temperature=0):
        raise LLMCallError("openai model call failed: AuthenticationError: bad key")

    monkeypatch.setattr("forge_dashboard.runner.call_model", failing_call_model)
    client = TestClient(app)

    upload = client.post(
        "/api/documents",
        files={"file": ("prd.md", b"Some content.", "text/markdown")},
    )
    document_id = upload.json()["document_id"]

    response = client.post(
        "/api/assessments",
        json={
            "document_id": document_id,
            "llm": {"provider": "openai", "model": "gpt-4o", "api_key": "sk-bad"},
        },
    )
    assert response.status_code == 502
    assert "bad key" in response.json()["detail"]
