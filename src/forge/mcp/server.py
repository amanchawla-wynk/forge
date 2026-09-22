from __future__ import annotations

from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver import Resolve, Sample
from mcp.types import CreateMessageResult, SamplingMessage, TextContent
from pydantic import BaseModel

from forge.extract.batch import ExtractionBatch
from forge.extract.parse import parse_extraction
from forge.extract.prompt import build_extraction_prompt
from forge.ingest.models import SupplementalAnswer
from forge.rubric.loader import load_rubric
from forge.service import (
    AssessmentResponse,
    assess_extraction_json,
    assess_extractions,
    prepare_assessment_input,
)


mcp = MCPServer(
    "forge",
    description="Evidence-based PRD completeness and actionability assessment.",
    instructions=(
        "Use assess_prd when the client supports MCP sampling. Otherwise call "
        "prepare_prd_assessment, complete the returned extraction task yourself, "
        "then pass the JSON to score_prd_extraction. Return next_question to the "
        "user and resubmit accumulated supplemental_answers after each reply. "
        "Forge is advisory."
    ),
)


class PreparedAssessment(BaseModel):
    source_path: str
    rubric_id: str
    rubric_version: str
    expected_runs: int
    supplemental_answers: list[SupplementalAnswer]
    extraction_prompt: str
    instructions: str


class RubricDescription(BaseModel):
    id: str
    version: str
    description: str
    criteria: list[dict[str, object]]
    warning: str


def _sample(
    source_path: str,
    rubric_name: str = "prd",
    supplemental_answers: list[SupplementalAnswer] | None = None,
) -> Sample:
    document, rubric = prepare_assessment_input(
        source_path, rubric_name, supplemental_answers
    )
    prompt = build_extraction_prompt(document, rubric)
    return Sample(
        [
            SamplingMessage(
                role="user", content=TextContent(type="text", text=prompt)
            )
        ],
        max_tokens=12_000,
        temperature=0,
    )


# Distinct resolver identities prevent the framework from deduplicating the
# three requests. The prompts remain identical so modern MCP retries are stable.
def _sample_run_one(
    source_path: str,
    rubric_name: str = "prd",
    supplemental_answers: list[SupplementalAnswer] | None = None,
) -> Sample:
    return _sample(source_path, rubric_name, supplemental_answers)


def _sample_run_two(
    source_path: str,
    rubric_name: str = "prd",
    supplemental_answers: list[SupplementalAnswer] | None = None,
) -> Sample:
    return _sample(source_path, rubric_name, supplemental_answers)


def _sample_run_three(
    source_path: str,
    rubric_name: str = "prd",
    supplemental_answers: list[SupplementalAnswer] | None = None,
) -> Sample:
    return _sample(source_path, rubric_name, supplemental_answers)


def _completion_text(result: CreateMessageResult) -> str:
    if isinstance(result.content, TextContent):
        return result.content.text
    raise ValueError("client model returned non-text sampling content")


@mcp.tool(structured_output=True)
async def assess_prd(
    source_path: str,
    run_one: Annotated[CreateMessageResult, Resolve(_sample_run_one)],
    run_two: Annotated[CreateMessageResult, Resolve(_sample_run_two)],
    run_three: Annotated[CreateMessageResult, Resolve(_sample_run_three)],
    rubric_name: str = "prd",
    supplemental_answers: list[SupplementalAnswer] | None = None,
) -> AssessmentResponse:
    """Assess a local PRD by borrowing the MCP client's model three times."""
    completions = [run_one, run_two, run_three]
    runs = [parse_extraction(_completion_text(result)) for result in completions]
    models = [result.model for result in completions if result.model]
    return assess_extractions(
        source_path,
        ExtractionBatch(runs=runs),
        rubric_name=rubric_name,
        client_models=models,
        supplemental_answers=supplemental_answers,
    )


@mcp.tool(structured_output=True)
def prepare_prd_assessment(
    source_path: str,
    rubric_name: str = "prd",
    supplemental_answers: list[SupplementalAnswer] | None = None,
) -> PreparedAssessment:
    """Prepare the extraction task for a client that lacks MCP sampling."""
    answers = supplemental_answers or []
    document, rubric = prepare_assessment_input(source_path, rubric_name, answers)
    return PreparedAssessment(
        source_path=document.source_path,
        rubric_id=rubric.id,
        rubric_version=rubric.version,
        expected_runs=rubric.extraction_runs,
        supplemental_answers=answers,
        extraction_prompt=build_extraction_prompt(document, rubric),
        instructions=(
            "Complete the extraction prompt with the connected agent model. "
            "For stronger confidence, repeat it independently and submit "
            '{"runs": [<run 1>, <run 2>, <run 3>]}. A single run is accepted '
            "but cannot establish test/retest stability."
        ),
    )


@mcp.tool(structured_output=True)
def score_prd_extraction(
    source_path: str,
    extraction_json: str,
    rubric_name: str = "prd",
    supplemental_answers: list[SupplementalAnswer] | None = None,
) -> AssessmentResponse:
    """Verify and score extraction JSON produced by the connected agent."""
    return assess_extraction_json(
        source_path,
        extraction_json,
        rubric_name=rubric_name,
        supplemental_answers=supplemental_answers,
    )


@mcp.tool(structured_output=True)
def describe_prd_rubric(rubric_name: str = "prd") -> RubricDescription:
    """Describe what the active PRD rubric examines, without scoring a file."""
    rubric = load_rubric(rubric_name)
    return RubricDescription(
        id=rubric.id,
        version=rubric.version,
        description=rubric.description.strip(),
        criteria=[
            {
                "id": criterion.id,
                "name": criterion.name,
                "rationale": criterion.rationale.strip(),
                "consumers": [consumer.value for consumer in criterion.consumers],
                "required_fields": [field.name for field in criterion.required_fields],
            }
            for criterion in rubric.criteria
        ],
        warning="This bundled rubric is generic, untuned, and uncalibrated.",
    )


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
