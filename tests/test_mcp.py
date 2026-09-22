from __future__ import annotations

import anyio
import pytest
from mcp import Client
from mcp.types import CreateMessageResult, TextContent

from forge.mcp.server import mcp


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_mcp_exposes_sampling_and_fallback_tools():
    tools = anyio.run(mcp.list_tools)
    names = {tool.name for tool in tools}

    assert names == {
        "assess_prd",
        "prepare_prd_assessment",
        "score_prd_extraction",
        "describe_prd_rubric",
    }
    assess = next(tool for tool in tools if tool.name == "assess_prd")
    assert set(assess.input_schema["properties"]) == {
        "source_path",
        "rubric_name",
        "supplemental_answers",
    }
    prepare = next(tool for tool in tools if tool.name == "prepare_prd_assessment")
    score = next(tool for tool in tools if tool.name == "score_prd_extraction")
    assert "supplemental_answers" in prepare.input_schema["properties"]
    assert "supplemental_answers" in score.input_schema["properties"]


@pytest.mark.anyio
async def test_assess_prd_borrows_client_model_three_times(tmp_path):
    path = tmp_path / "prd.md"
    path.write_text("A short and incomplete product note.")
    calls = 0

    async def sample(context, params):
        nonlocal calls
        calls += 1
        assert "UNTRUSTED DATA" in params.messages[0].content.text
        assert "Finance administrators are affected." in params.messages[0].content.text
        assert "provenance=supplemental_answer" in params.messages[0].content.text
        return CreateMessageResult(
            role="assistant",
            content=TextContent(text='{"criteria": []}'),
            model="test-client-model",
            stopReason="endTurn",
        )

    async with Client(
        mcp,
        raise_exceptions=True,
        sampling_callback=sample,
    ) as client:
        result = await client.call_tool(
            "assess_prd",
            {
                "source_path": str(path),
                "supplemental_answers": [
                    {
                        "criterion_id": "problem_statement",
                        "answer": "Finance administrators are affected.",
                    }
                ],
            },
        )

    assert calls == 3
    assert result.structured_content["run_count"] == 3
    assert result.structured_content["assessment"]["band"] == "not_a_prd"
    assert result.structured_content["report"]["headline"] == "Not a PRD"
    assert result.structured_content["report"]["next_step"] == (
        result.structured_content["next_question"]["question"]
    )
    assert "across 3 extraction runs" in (
        result.structured_content["report"]["confidence_note"]
    )
    assert result.structured_content["next_question"] is not None
    assert result.structured_content["supplemental_answers"] == [
        {
            "criterion_id": "problem_statement",
            "answer": "Finance administrators are affected.",
        }
    ]
    assert result.structured_content["client_models"] == [
        "test-client-model",
        "test-client-model",
        "test-client-model",
    ]
