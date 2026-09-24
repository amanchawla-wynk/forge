from __future__ import annotations

import httpx
import pytest

from forge_dashboard.cursor_agent import call_cursor_agent
from forge_dashboard.llm import LLMCallError


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.anyio
async def test_call_cursor_agent_creates_polls_and_archives(monkeypatch):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        assert request.headers["authorization"].startswith("Basic ")
        if request.url.path == "/v1/agents":
            body = request.content.decode()
            assert "Do not use any tools" in body
            assert "extract the criteria" in body
            return httpx.Response(
                200,
                json={
                    "agent": {"id": "bc-1"},
                    "run": {"id": "run-1", "status": "CREATING"},
                },
            )
        if request.url.path == "/v1/agents/bc-1/runs/run-1":
            # First poll: still running. Second poll: finished.
            if calls.count("GET /v1/agents/bc-1/runs/run-1") == 1:
                return httpx.Response(200, json={"status": "RUNNING"})
            return httpx.Response(
                200, json={"status": "FINISHED", "result": '{"criteria": []}'}
            )
        if request.url.path == "/v1/agents/bc-1/archive":
            return httpx.Response(200, json={"id": "bc-1"})
        raise AssertionError(f"unexpected request: {request.url}")

    monkeypatch.setattr(
        "forge_dashboard.cursor_agent._POLL_INTERVAL_SECONDS", 0.001
    )

    real_async_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs["transport"] = _transport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("forge_dashboard.cursor_agent.httpx.AsyncClient", fake_async_client)

    completion = await call_cursor_agent(
        "sk-cursor-test", "extract the criteria please", model="composer-2.5"
    )

    assert completion.text == '{"criteria": []}'
    assert completion.model == "composer-2.5"
    assert "POST /v1/agents" in calls
    assert "GET /v1/agents/bc-1/runs/run-1" in calls
    assert "POST /v1/agents/bc-1/archive" in calls


@pytest.mark.anyio
async def test_call_cursor_agent_reports_creation_failure(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="invalid api key")

    real_async_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs["transport"] = _transport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("forge_dashboard.cursor_agent.httpx.AsyncClient", fake_async_client)

    with pytest.raises(LLMCallError) as excinfo:
        await call_cursor_agent("sk-bad", "extract the criteria please")

    assert "401" in str(excinfo.value)
    assert "invalid api key" in str(excinfo.value)


@pytest.mark.anyio
async def test_call_cursor_agent_reports_terminal_error_status(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/agents":
            return httpx.Response(
                200,
                json={"agent": {"id": "bc-2"}, "run": {"id": "run-2", "status": "CREATING"}},
            )
        if request.url.path == "/v1/agents/bc-2/runs/run-2":
            return httpx.Response(200, json={"status": "ERROR"})
        return httpx.Response(200, json={"id": "bc-2"})

    real_async_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs["transport"] = _transport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("forge_dashboard.cursor_agent.httpx.AsyncClient", fake_async_client)

    with pytest.raises(LLMCallError) as excinfo:
        await call_cursor_agent("sk-test", "extract the criteria please")

    assert "ERROR" in str(excinfo.value)
