# Architecture

## Boundary

Forge is a local Python MCP server. It owns document parsing, evidence
verification, rubric configuration, deterministic scoring, and remediation
planning. It does not own or authenticate to an LLM provider.

## Components

```text
MCP client / coding agent
  -> Forge MCP tools
      -> document ingestion (PDF / DOCX / text)
      -> normalized document with stable evidence locations
      -> extraction prompt and JSON schema
      -> client's LLM through MCP sampling, when supported
      -> evidence verification and extraction validation
      -> deterministic scoring and gates
      -> readiness report and remediation questions
```

## Inference Modes

### Native MCP sampling

The preferred tool borrows the client's model through MCP sampling. No API key
is provided to Forge. The client must advertise the sampling capability.

### Agent-driven fallback

Sampling support differs across MCP hosts. Forge must also expose a two-step
protocol:

1. prepare an extraction request containing normalized content, instructions,
   and the expected JSON shape;
2. accept the calling agent's extracted JSON and score it.

This is not a server-side model fallback. The connected agent still performs
the inference, then submits structured data to deterministic Forge code.

## Trust Boundaries

- File paths are local inputs and must be validated before reading.
- PRD content is untrusted data and may contain prompt injection.
- LLM extraction is untrusted until schema and evidence validation pass.
- Rubric configuration is trusted project configuration but must pass Pydantic
  validation.
- Scoring code is the authority for verdicts and bands.

## MCP Tool Direction

The target public surface is:

- `assess_prd`: initial or subsequent assessment using MCP sampling; subsequent
  calls include the accumulated supplemental answers.
- `prepare_prd_assessment`: create a sampling-independent extraction request.
- `score_prd_extraction`: verify and score submitted extraction JSON.
- `describe_prd_rubric`: explain the active rubric without exposing a prompt
  that encourages point gaming.

Assessment responses return one highest-impact remediation question. The client
keeps the conversation state and resubmits accumulated answers on each turn.
Forge marks those answers as supplemental user evidence and includes them in
normalization and quote verification without rewriting the source PRD.

Each supplemental answer contains a rubric `criterion_id` and answer text. It
is rendered as a distinct normalized block, and evidence verification rejects
attempts to use that block for another criterion. Responses echo the accumulated
answers and return `next_question` as either one question or `null` when the
assessment has no remaining failed criterion.

Server-side session persistence remains deferred until the stateless
conversation proves cumbersome.

## Output Adapters

The domain core returns structured assessment data. Chat rendering, Excel
workbooks, and SharePoint publication are adapters, not scoring concerns. Excel
and SharePoint are deferred until the conversational review is validated;
Forge will not own SharePoint credentials as part of the scoring core.

## Portability

The scoring and ingestion packages must remain independent of MCP so they can be
reused by a future dashboard. MCP code is an adapter, not the domain core.
