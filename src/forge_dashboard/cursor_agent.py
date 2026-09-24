"""Cursor Cloud Agents as an alternative BYOK inference path.

A Cursor API key (generated at https://cursor.com/dashboard/api) is *not* an
LLM provider key, so it cannot go through LiteLLM. It authenticates to
Cursor's Cloud Agents API (`api.cursor.com/v1/agents`), which creates a
short-lived, no-repo cloud coding agent per call rather than returning a
synchronous chat completion. This module creates one such agent per
extraction prompt, polls its single run to completion, and returns the
agent's final reply as the completion text.

This is slower than a direct provider call (cloud VM boot plus reasoning
time), is billed against the caller's Cursor plan/agent quota rather than raw
token pricing, and sends the PRD text to Cursor's cloud infrastructure for
that run — the same trust boundary as any other BYOK provider in this
package, just proxied through Cursor. See `docs/DECISIONS.md` D-034.

The API key is forwarded per-request only and never written to disk, a
database, or a log, exactly like every other provider in this package.
"""

from __future__ import annotations

import asyncio
import time

import httpx

from forge_dashboard.llm import Completion, LLMCallError

_API_BASE = "https://api.cursor.com"
_CREATE_TIMEOUT_SECONDS = 30.0
_POLL_TIMEOUT_SECONDS = 15.0
_POLL_INTERVAL_SECONDS = 2.0
_MAX_WAIT_SECONDS = 240.0
_TERMINAL_STATUSES = {"FINISHED", "ERROR", "CANCELLED", "EXPIRED"}

# Told explicitly not to use tools: a no-repo agent has no filesystem or
# shell to act on, and extraction requires a clean text reply, not an
# agentic trace.
_AGENT_PREAMBLE = (
    "Reply with plain text only. Do not use any tools, do not search for or "
    "modify files, and do not assume a repository is attached. Respond with "
    "exactly the requested content below and nothing else.\n\n"
)


async def call_cursor_agent(
    api_key: str, prompt: str, *, model: str | None = None
) -> Completion:
    auth = (api_key, "")
    body: dict[str, object] = {"prompt": {"text": _AGENT_PREAMBLE + prompt}}
    if model:
        body["model"] = {"id": model}

    try:
        async with httpx.AsyncClient(base_url=_API_BASE) as client:
            agent_id, run_id = await _create_agent(client, auth, body)
            try:
                return Completion(
                    text=await _wait_for_run(client, auth, agent_id, run_id),
                    model=model or "cursor-default",
                )
            finally:
                await _archive_best_effort(client, auth, agent_id)
    except LLMCallError:
        raise
    except Exception as error:  # noqa: BLE001 - normalize every failure mode
        raise LLMCallError(
            f"cursor agent call failed: {type(error).__name__}: {error}"
        ) from error


async def _create_agent(
    client: httpx.AsyncClient, auth: tuple[str, str], body: dict[str, object]
) -> tuple[str, str]:
    try:
        response = await client.post(
            "/v1/agents", auth=auth, json=body, timeout=_CREATE_TIMEOUT_SECONDS
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        raise LLMCallError(
            "cursor agent creation failed: "
            f"{error.response.status_code} {error.response.text[:200]}"
        ) from error
    payload = response.json()
    return payload["agent"]["id"], payload["run"]["id"]


async def _wait_for_run(
    client: httpx.AsyncClient, auth: tuple[str, str], agent_id: str, run_id: str
) -> str:
    deadline = time.monotonic() + _MAX_WAIT_SECONDS
    while True:
        try:
            response = await client.get(
                f"/v1/agents/{agent_id}/runs/{run_id}",
                auth=auth,
                timeout=_POLL_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise LLMCallError(
                "cursor agent run check failed: "
                f"{error.response.status_code} {error.response.text[:200]}"
            ) from error
        run = response.json()
        status = run.get("status")
        if status == "FINISHED":
            result = run.get("result")
            if not result:
                raise LLMCallError("cursor agent finished with an empty result")
            return result
        if status in _TERMINAL_STATUSES:
            raise LLMCallError(f"cursor agent run ended with status {status!r}")
        if time.monotonic() >= deadline:
            raise LLMCallError(
                f"cursor agent run did not finish within {_MAX_WAIT_SECONDS:.0f}s"
            )
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)


async def _archive_best_effort(
    client: httpx.AsyncClient, auth: tuple[str, str], agent_id: str
) -> None:
    """Clean up the cloud agent; failure here must not fail the extraction."""
    try:
        await client.post(f"/v1/agents/{agent_id}/archive", auth=auth, timeout=10.0)
    except httpx.HTTPError:
        pass
