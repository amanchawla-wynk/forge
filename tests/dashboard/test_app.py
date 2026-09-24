from __future__ import annotations

from fastapi.testclient import TestClient

from forge_dashboard.app import app
from forge_dashboard.llm import Completion


def _client(monkeypatch) -> TestClient:
    async def fake_call_model(config, prompt, *, max_tokens, temperature=0):
        return Completion(text='{"criteria": []}', model="claude-test")

    # runner.py and app.py each import `call_model` by reference, so both
    # bindings need patching independently.
    monkeypatch.setattr("forge_dashboard.runner.call_model", fake_call_model)
    monkeypatch.setattr("forge_dashboard.app.call_model", fake_call_model)
    return TestClient(app)


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
    session_id = assessment.json()["remediation_session_id"]
    calls_after_assessment = calls

    recorded = client.post(
        f"/api/remediation/{session_id}/answers",
        json={"answer": "GenZ viewers need short-form stories."},
    )

    assert recorded.status_code == 200
    assert recorded.json()["turn"]["pending_answer_count"] == 1
    assert recorded.json()["turn"]["score_is_current"] is False
    assert calls == calls_after_assessment


def test_revision_preview_materializes_copy_and_reassesses(monkeypatch) -> None:
    client = _client(monkeypatch)
    original = b"# PRD\n\n## Success Metrics\n\nDAU is monitored.\n"
    upload = client.post(
        "/api/documents",
        files={"file": ("prd.md", original, "text/markdown")},
    ).json()
    answer = "Repeat usage should increase from 20% to 30% within 90 days."
    preview = client.post(
        f"/api/documents/{upload['document_id']}/revisions/preview",
        json={
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
