"""Orchestrates extraction through a user-supplied model instead of MCP sampling.

Everything downstream of the raw completion text is identical to the MCP path:
`forge.extract.parse.parse_extraction`, `forge.extract.batch` evidence
verification, and `forge.score` deterministic scoring are reused unmodified
through `forge.service`. This module's only job is "get extraction JSON out of
the user's chosen model," mirroring what `forge.mcp.server`'s sampling
resolvers do for an MCP client.
"""

from __future__ import annotations

import asyncio

from forge.extract.batch import ExtractionBatch, ExtractionFragment, ExtractionRun
from forge.extract.parse import parse_extraction
from forge.extract.prompt import build_extraction_prompt
from forge.ingest.models import ProductContextTerm, SupplementalAnswer
from forge.rubric.models import Rubric
from forge.score.contextualize import (
    build_candidates,
    build_coverage_pairs,
    build_coverage_prompt,
    build_framing_prompt,
    build_requirement_candidates,
    parse_coverage_classification,
    parse_framing_choice,
)
from forge.score.edge_coverage import (
    EdgeCaseCoverageLedger,
    consolidate_coverage_ledgers,
)
from forge.remediation import RemediationState, begin_remediation_prepared
from forge.service import (
    AssessmentResponse,
    assess_prepared_extractions,
    prepare_assessment,
)

from forge_dashboard.llm import LLMCallError, call_model
from forge_dashboard.models import LLMConfig

MAX_EXTRACTION_TOKENS = 12_000


class ExtractionFailed(RuntimeError):
    """One or more model calls failed; message lists every failure."""


async def run_assessment(
    source_path: str,
    llm: LLMConfig,
    *,
    rubric_name: str = "prd",
    supplemental_answers: list[SupplementalAnswer] | None = None,
    product_context: list[ProductContextTerm] | None = None,
    framing: str | None = None,
    display_name: str | None = None,
    edge_case_coverage: EdgeCaseCoverageLedger | None = None,
) -> AssessmentResponse:
    response, _ = await run_assessment_with_remediation(
        source_path,
        llm,
        rubric_name=rubric_name,
        supplemental_answers=supplemental_answers,
        product_context=product_context,
        framing=framing,
        display_name=display_name,
        edge_case_coverage=edge_case_coverage,
    )
    return response


async def run_assessment_with_remediation(
    source_path: str,
    llm: LLMConfig,
    *,
    rubric_name: str = "prd",
    supplemental_answers: list[SupplementalAnswer] | None = None,
    product_context: list[ProductContextTerm] | None = None,
    framing: str | None = None,
    display_name: str | None = None,
    edge_case_coverage: EdgeCaseCoverageLedger | None = None,
) -> tuple[AssessmentResponse, RemediationState | None]:
    answers = supplemental_answers or []
    context = product_context or []
    prepared = prepare_assessment(
        source_path, rubric_name, answers, context
    )
    rubric = prepared.rubric
    batches = prepared.batches
    run_count = rubric.extraction_runs

    if len(batches) == 1:
        batch, models = await _run_single_batch(batches[0].document, rubric, llm, run_count)
    else:
        batch, models = await _run_multi_batch(
            batches, rubric, llm, run_count, prepared.plan_fingerprint
        )

    # Framing affects question wording only. Detect it once from already-
    # verified facts; a failed or malformed call safely leaves the rubric's
    # default phrasing in place. The response echoes the resolved framing so
    # the browser can resubmit it on later remediation turns without drift.
    resolved_framing = framing
    if resolved_framing is None and rubric.framings:
        preliminary = assess_prepared_extractions(
            prepared,
            batch,
            client_models=models,
            display_name=display_name,
        )
        resolved_framing = await _detect_framing(preliminary, rubric, llm)

    preliminary = assess_prepared_extractions(
        prepared,
        batch,
        client_models=models,
        framing=resolved_framing,
        display_name=display_name,
    )
    coverage = edge_case_coverage or await _classify_edge_case_coverage(
        preliminary, rubric, llm
    )
    response = (
        preliminary
        if coverage is None
        else assess_prepared_extractions(
            prepared,
            batch,
            client_models=models,
            framing=resolved_framing,
            display_name=display_name,
            edge_case_coverage=coverage,
        )
    )
    if answers:
        # Compatibility path for existing dashboard clients. New sessions use
        # answer collection and checkpoint deltas instead.
        return response, None
    extraction_json = batch.model_dump_json()
    turn = begin_remediation_prepared(
        prepared,
        extraction_json,
        framing=resolved_framing,
        edge_case_coverage=coverage,
        client_models=models,
        display_name=display_name,
    )
    return response, turn.state


async def _detect_framing(
    response: AssessmentResponse, rubric: Rubric, llm: LLMConfig
) -> str | None:
    candidates = build_candidates(response.assessment, "", limit=8)
    prompt = build_framing_prompt(rubric, candidates)
    try:
        completion = await call_model(llm, prompt, max_tokens=50, temperature=0)
    except LLMCallError:
        return None
    return parse_framing_choice(completion.text, rubric)


async def _classify_edge_case_coverage(
    response: AssessmentResponse, rubric: Rubric, llm: LLMConfig
) -> EdgeCaseCoverageLedger | None:
    requirements = build_requirement_candidates(response.assessment)
    if not requirements:
        return None
    evidence_candidates = build_candidates(
        response.assessment,
        "edge_cases_and_states",
        limit=20,
        per_field_limit=4,
    )
    pairs = build_coverage_pairs(requirements)
    if not pairs:
        return None
    prompt = build_coverage_prompt(requirements, evidence_candidates, pairs)
    completions = await _gather_completions(
        llm, [prompt] * rubric.extraction_runs, max_tokens=4_000
    )
    ledgers = []
    for completion in completions:
        ledger = parse_coverage_classification(
            completion.text,
            requirements,
            evidence_candidates,
            pairs,
        )
        if ledger is None:
            raise ExtractionFailed(
                "model returned invalid edge-case coverage JSON; expected every "
                "declared pair exactly once with closed-set status/evidence indexes"
            )
        ledgers.append(ledger)
    consolidated, _ = consolidate_coverage_ledgers(ledgers)
    return consolidated


async def _run_single_batch(document, rubric, llm: LLMConfig, run_count: int):
    prompt = build_extraction_prompt(document, rubric)
    completions = await _gather_completions(llm, [prompt] * run_count)
    runs = [parse_extraction(completion.text) for completion in completions]
    models = [completion.model for completion in completions]
    return ExtractionBatch(runs=runs), models


async def _run_multi_batch(
    batches, rubric, llm: LLMConfig, run_count: int, fingerprint: str
):
    prompts = [
        build_extraction_prompt(batch.document, rubric, batch_id=batch.id)
        for batch in batches
        for _ in range(run_count)
    ]
    completions = await _gather_completions(llm, prompts)

    models: list[str] = []
    runs: list[ExtractionRun] = [ExtractionRun(fragments=[]) for _ in range(run_count)]
    index = 0
    for batch in batches:
        for run_index in range(run_count):
            completion = completions[index]
            index += 1
            models.append(completion.model)
            parsed = parse_extraction(completion.text)
            runs[run_index].fragments.append(
                ExtractionFragment(
                    batch_id=batch.id,
                    criteria=parsed.criteria,
                    run_index=run_index + 1,
                    plan_fingerprint=fingerprint,
                )
            )
    return ExtractionBatch(runs=runs), models


async def _gather_completions(
    llm: LLMConfig,
    prompts: list[str],
    *,
    max_tokens: int = MAX_EXTRACTION_TOKENS,
):
    results = await asyncio.gather(
        *(
            call_model(llm, prompt, max_tokens=max_tokens)
            for prompt in prompts
        ),
        return_exceptions=True,
    )
    errors = [str(result) for result in results if isinstance(result, LLMCallError)]
    if errors:
        raise ExtractionFailed("; ".join(errors))
    other_errors = [result for result in results if isinstance(result, Exception)]
    if other_errors:
        raise other_errors[0]
    return list(results)
