from __future__ import annotations

import json

import pytest

from forge.rubric.loader import load_rubric
from forge_dashboard.llm import Completion, LLMCallError
from forge_dashboard.models import LLMConfig
from forge_dashboard.runner import ExtractionFailed, run_assessment


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _llm_config() -> LLMConfig:
    return LLMConfig(provider="anthropic", model="claude-3-5-sonnet", api_key="sk-test")


@pytest.mark.anyio
async def test_run_assessment_calls_the_configured_model_three_times(
    tmp_path, monkeypatch
):
    path = tmp_path / "prd.md"
    path.write_text("A short and incomplete product note.")
    calls: list[str] = []

    async def fake_call_model(config, prompt, *, max_tokens, temperature=0):
        calls.append(prompt)
        assert config.provider == "anthropic"
        assert "UNTRUSTED DATA" in prompt
        return Completion(text='{"criteria": []}', model="claude-test")

    monkeypatch.setattr("forge_dashboard.runner.call_model", fake_call_model)

    result = await run_assessment(str(path), _llm_config())

    assert len(calls) == 3
    assert result.run_count == 3
    assert result.client_models == ["claude-test", "claude-test", "claude-test"]
    assert result.assessment.band == "not_a_prd"
    assert result.next_question is not None


@pytest.mark.anyio
async def test_run_assessment_includes_accumulated_supplemental_answers(
    tmp_path, monkeypatch
):
    path = tmp_path / "prd.md"
    path.write_text("A short product note.")

    seen_prompts: list[str] = []

    async def fake_call_model(config, prompt, *, max_tokens, temperature=0):
        seen_prompts.append(prompt)
        return Completion(text='{"criteria": []}', model="claude-test")

    monkeypatch.setattr("forge_dashboard.runner.call_model", fake_call_model)

    from forge.ingest.models import SupplementalAnswer

    await run_assessment(
        str(path),
        _llm_config(),
        supplemental_answers=[
            SupplementalAnswer(
                criterion_id="problem_statement",
                answer="Finance administrators cannot export invoices.",
            )
        ],
    )

    assert all(
        "Finance administrators cannot export invoices." in prompt
        for prompt in seen_prompts
    )


@pytest.mark.anyio
async def test_run_assessment_assembles_multi_batch_fragments_per_run(
    tmp_path, monkeypatch
):
    problem_quote = "Finance administrators cannot export invoices."
    path = tmp_path / "long-prd.md"
    path.write_text(problem_quote + (" Neutral context." * 9_000))
    rubric = load_rubric("prd")

    def _criteria(prompt: str) -> list[dict[str, object]]:
        return [
            {
                "criterion_id": criterion.id,
                "fields": [
                    {
                        "name": field.name,
                        "value": problem_quote
                        if criterion.id == "problem_statement"
                        and field.name == "problem"
                        and problem_quote in prompt
                        else None,
                        "evidence": {"quote": problem_quote}
                        if criterion.id == "problem_statement"
                        and field.name == "problem"
                        and problem_quote in prompt
                        else None,
                    }
                    for field in criterion.fields
                ],
            }
            for criterion in rubric.criteria
        ]

    seen_prompts: list[str] = []

    async def fake_call_model(config, prompt, *, max_tokens, temperature=0):
        seen_prompts.append(prompt)
        assert "one exhaustive document batch" in prompt
        return Completion(
            text=json.dumps({"criteria": _criteria(prompt)}), model="claude-test"
        )

    monkeypatch.setattr("forge_dashboard.runner.call_model", fake_call_model)

    result = await run_assessment(str(path), _llm_config())

    assert len(seen_prompts) % 3 == 0
    assert len(seen_prompts) > 3  # more than one batch
    assert result.run_count == 3
    problem = next(
        item for item in result.assessment.criteria if item.criterion_id == "problem_statement"
    )
    assert problem.verdict.value == "partial"
    assert problem.missing == ["affected_users", "evidence"]


@pytest.mark.anyio
async def test_run_assessment_raises_extraction_failed_on_model_error(
    tmp_path, monkeypatch
):
    path = tmp_path / "prd.md"
    path.write_text("A short product note.")

    async def failing_call_model(config, prompt, *, max_tokens, temperature=0):
        raise LLMCallError("anthropic model call failed: AuthenticationError: bad key")

    monkeypatch.setattr("forge_dashboard.runner.call_model", failing_call_model)

    with pytest.raises(ExtractionFailed) as excinfo:
        await run_assessment(str(path), _llm_config())

    assert "bad key" in str(excinfo.value)
