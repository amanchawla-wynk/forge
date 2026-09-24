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
async def test_run_assessment_calls_extractor_three_times_and_detects_framing(
    tmp_path, monkeypatch
):
    path = tmp_path / "prd.md"
    path.write_text("A short and incomplete product note.")
    calls: list[str] = []

    async def fake_call_model(config, prompt, *, max_tokens, temperature=0):
        calls.append(prompt)
        assert config.provider == "anthropic"
        assert "UNTRUSTED DATA" in prompt
        if "OPTIONS:" in prompt:
            return Completion(text='{"framing": 2}', model="claude-test")
        return Completion(text='{"criteria": []}', model="claude-test")

    monkeypatch.setattr("forge_dashboard.runner.call_model", fake_call_model)

    result = await run_assessment(str(path), _llm_config())

    assert len(calls) == 4
    assert sum("strict information extractor" in prompt for prompt in calls) == 3
    assert sum("OPTIONS:" in prompt for prompt in calls) == 1
    assert result.run_count == 3
    assert result.client_models == ["claude-test", "claude-test", "claude-test"]
    assert result.assessment.band == "not_a_prd"
    assert result.next_question is not None
    assert result.framing == "opportunity_bet"
    assert "opportunity is this going after" in result.next_question.question


@pytest.mark.anyio
async def test_run_assessment_includes_accumulated_supplemental_answers(
    tmp_path, monkeypatch
):
    path = tmp_path / "prd.md"
    path.write_text("A short product note.")

    seen_prompts: list[str] = []

    async def fake_call_model(config, prompt, *, max_tokens, temperature=0):
        seen_prompts.append(prompt)
        if "OPTIONS:" in prompt:
            return Completion(text='{"framing": 0}', model="claude-test")
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

    extraction_prompts = [
        prompt for prompt in seen_prompts if "strict information extractor" in prompt
    ]
    assert len(extraction_prompts) == 3
    assert all(
        "Finance administrators cannot export invoices." in prompt
        for prompt in extraction_prompts
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
        if "OPTIONS:" in prompt:
            return Completion(text='{"framing": 1}', model="claude-test")
        assert "one exhaustive document batch" in prompt
        return Completion(
            text=json.dumps({"criteria": _criteria(prompt)}), model="claude-test"
        )

    monkeypatch.setattr("forge_dashboard.runner.call_model", fake_call_model)

    result = await run_assessment(str(path), _llm_config())

    extraction_prompts = [
        prompt for prompt in seen_prompts if "one exhaustive document batch" in prompt
    ]
    assert len(extraction_prompts) % 3 == 0
    assert len(extraction_prompts) > 3  # more than one batch
    assert len(seen_prompts) == len(extraction_prompts) + 1
    assert result.run_count == 3
    problem = next(
        item for item in result.assessment.criteria if item.criterion_id == "problem_statement"
    )
    assert problem.verdict.value == "partial"
    assert problem.missing == ["affected_users", "evidence"]


@pytest.mark.anyio
async def test_run_assessment_reuses_supplied_framing_without_redetecting(
    tmp_path, monkeypatch
):
    path = tmp_path / "prd.md"
    path.write_text("A short product note.")
    calls: list[str] = []

    async def fake_call_model(config, prompt, *, max_tokens, temperature=0):
        calls.append(prompt)
        assert "OPTIONS:" not in prompt
        return Completion(text='{"criteria": []}', model="claude-test")

    monkeypatch.setattr("forge_dashboard.runner.call_model", fake_call_model)

    result = await run_assessment(
        str(path), _llm_config(), framing="opportunity_bet"
    )

    assert len(calls) == 3
    assert result.framing == "opportunity_bet"
    assert result.next_question is not None
    assert "opportunity is this going after" in result.next_question.question


@pytest.mark.anyio
async def test_run_assessment_discovers_anchored_edge_case_when_it_is_next(
    tmp_path, monkeypatch
):
    rubric = load_rubric("prd")
    quotes: list[str] = []
    criteria: list[dict[str, object]] = []
    for criterion in rubric.criteria:
        fields: list[dict[str, object]] = []
        for field in criterion.required_fields:
            if (
                criterion.id == "edge_cases_and_states"
                and field.name == "transitional_or_degraded_states"
            ):
                fields.append({"name": field.name, "value": None, "evidence": None})
                continue
            text = (
                f"1 WCAG dashboard retention {criterion.id} {field.name}"
                if field.value_pattern
                else f"verified {criterion.id} {field.name}"
            )
            quotes.append(text)
            fields.append(
                {"name": field.name, "value": text, "evidence": {"quote": text}}
            )
        criteria.append({"criterion_id": criterion.id, "fields": fields})

    path = tmp_path / "stored-id.md"
    path.write_text("\n".join(quotes))
    calls: list[str] = []

    async def fake_call_model(config, prompt, *, max_tokens, temperature=0):
        calls.append(prompt)
        if "Classify coverage for every listed" in prompt:
            pair_lines = prompt.split("PAIRS:\n", 1)[1].split(
                "\n\nEVIDENCE OPTIONS:", 1
            )[0].splitlines()
            return Completion(
                text=json.dumps(
                    {
                        "items": [
                            {"pair": index, "status": 2, "evidence": 0}
                            for index, _ in enumerate(pair_lines, start=1)
                        ]
                    }
                ),
                model="claude-test",
            )
        return Completion(
            text=json.dumps({"criteria": criteria}), model="claude-test"
        )

    monkeypatch.setattr("forge_dashboard.runner.call_model", fake_call_model)

    result = await run_assessment(
        str(path),
        _llm_config(),
        framing="opportunity_bet",
        display_name="Micro Dramas",
    )

    assert len(calls) == 4
    assert result.next_question is not None
    assert result.next_question.target_field == "edge_case_coverage"
    assert result.next_question.edge_case_id == "interruption_recovery"
    assert result.next_question.question.startswith(
        'For "Micro Dramas", the PRD says:'
    )
    assert "interrupted after it starts" in result.next_question.question
    assert result.report.next_step == result.next_question.question


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
