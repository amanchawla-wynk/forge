"""Thin async LiteLLM wrapper. The only place this package calls a provider.

The API key is passed through per-call and never logged, cached, or written
anywhere. See `docs/DECISIONS.md` D-033.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from forge_dashboard.models import LLMConfig


class LLMCallError(RuntimeError):
    """Raised when the provider call fails; message excludes the API key."""


@dataclass(frozen=True)
class Completion:
    text: str
    model: str


_INFERENCE_LIMIT = int(os.environ.get("FORGE_DASHBOARD_MAX_INFERENCE_CONCURRENCY", "3"))
_INFERENCE_TIMEOUT = float(os.environ.get("FORGE_DASHBOARD_INFERENCE_TIMEOUT", "120"))
_inference_slots = asyncio.Semaphore(_INFERENCE_LIMIT)


def _litellm_model_id(config: LLMConfig) -> str:
    if config.model.startswith(f"{config.provider}/"):
        return config.model
    return f"{config.provider}/{config.model}"


async def call_model(
    config: LLMConfig, prompt: str, *, max_tokens: int, temperature: float = 0
) -> Completion:
    try:
        async with _inference_slots, asyncio.timeout(_INFERENCE_TIMEOUT):
            return await _call_model(config, prompt, max_tokens=max_tokens, temperature=temperature)
    except TimeoutError as error:
        raise LLMCallError(
            f"{config.provider} model call timed out after {_INFERENCE_TIMEOUT:g} seconds"
        ) from error


async def _call_model(
    config: LLMConfig, prompt: str, *, max_tokens: int, temperature: float = 0
) -> Completion:
    if config.provider == "cursor":
        # Not an LLM provider call; see forge_dashboard/cursor_agent.py and
        # docs/DECISIONS.md D-034. Imported lazily to avoid importing httpx
        # at module load for the common LiteLLM path.
        from forge_dashboard.cursor_agent import call_cursor_agent

        return await call_cursor_agent(
            config.api_key, prompt, model=config.model.strip() or None
        )

    # Imported lazily so the base `forge` package never needs `litellm`
    # installed; only `forge_dashboard` (the `dashboard` extra) does.
    import litellm

    try:
        response = await litellm.acompletion(
            model=_litellm_model_id(config),
            api_key=config.api_key,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except Exception as error:  # noqa: BLE001 - normalize every provider error
        raise LLMCallError(
            f"{config.provider} model call failed: {type(error).__name__}: {error}"
        ) from error

    choice = response.choices[0]
    text = choice.message.content
    if not text:
        raise LLMCallError(f"{config.provider} model returned an empty completion")
    return Completion(text=text, model=response.model or config.model)
