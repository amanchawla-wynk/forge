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
      -> normalized text blocks and detected visual assets
      -> exhaustive, source-mapped extraction batches
      -> extraction prompt and JSON schema
      -> client's LLM through MCP sampling, when supported
      -> evidence verification and extraction validation
      -> deterministic scoring and gates
      -> deterministic narrative report, audit, and remediation question
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
- Product terminology context is untrusted, non-evidence background and cannot
  satisfy a rubric field.
- LLM extraction is untrusted until schema and evidence validation pass.
- Rubric configuration is trusted project configuration but must pass Pydantic
  validation.
- The bundled rubric carries a calibration status and versioned published-source
  list. This metadata is returned to clients and never changes evidence credit.
- Scoring code is the authority for verdicts and bands.

## MCP Tool Direction

The target public surface is:

- `assess_prd`: single-batch assessment using MCP sampling; subsequent calls
  include the accumulated supplemental answers.
- `list_prd_batches`: enumerate the exhaustive extraction batches.
- `assess_prd_batch`: sample the client model three times for one batch and
  return its fragments.
- `list_prd_visuals`: enumerate detected images and diagrams.
- `observe_prd_visual`: describe one rendered image through client sampling.
- `prepare_prd_assessment`: create a sampling-independent extraction request.
- `score_prd_extraction`: verify and score submitted extraction JSON.
- `write_prd_revision`: materialize approved supplemental answers into a new
  editable PRD copy without overwriting the source.
- `describe_prd_rubric`: explain the active rubric without exposing a prompt
  that encourages point gaming.

Assessment responses return one highest-impact remediation question. The client
keeps the conversation state and resubmits accumulated answers on each turn.
Forge marks those answers as supplemental user evidence and includes them in
normalization and quote verification without rewriting the source PRD.

The selected question names one `target_field`, one concise field-specific
prompt, and one answer requirement. It also retains all `missing_fields` for the
criterion audit. Rescoring after the answer determines whether the next turn
stays on that criterion or advances; the planner never presents a batch of
subquestions in one turn.

The response places a concise `report` before the detailed `assessment`. Report
generation is deterministic and consumes only scored verdicts, failed gates,
consumer blockers, remediation ordering, and extraction-run agreement. It does
not invoke an LLM or alter the audit result.

The report also exposes exhaustive structured gap records and groups criterion
ids by affected consumer. This provides technical, UX, data, risk, leadership,
and go-to-market views without chaining specialist agents or allowing generated
critique to change the score. A gap record is derived from a failed verified
criterion and names its missing fields, affected consumers, gate status, and
configured rationale.

Each supplemental answer contains a rubric `criterion_id` and answer text. It
is rendered as a distinct normalized block, and evidence verification rejects
attempts to use that block for another criterion. Responses echo the accumulated
answers and return `next_question` as either one question or `null` when the
assessment has no remaining failed criterion.

Questions include the configured descriptions of their missing required fields.
`write_prd_revision` supports DOCX, Markdown, and text sources, requires a new
same-format output path, and refuses to overwrite an existing file. PDF remains
read-only because appending text would not preserve an editable source or its
layout semantics.

Assessment responses expose disputed criteria and recommend up to two more
complete runs after initial disagreement. The fallback scorer already accepts
additional complete runs; native sampling remains a fixed three-call baseline.

Assessment and batching tools accept optional `ProductContextTerm` records.
They are carried separately on `NormalizedDocument`, rendered into a clearly
marked non-evidence prompt section, and included in the batch-plan fingerprint.
They are never rendered as `SourceBlock`s, so `locate_quote` cannot verify a
context-only claim. Changing context invalidates prior extraction fragments.

Server-side session persistence remains deferred until the stateless
conversation proves cumbersome.

`prepare_prd_assessment` returns `extraction_batches` rather than a single
`extraction_prompt`, because a long document requires several exhaustive
batches. Each independent run submits one fragment per batch, and scoring
rejects a run whose fragment set is incomplete or whose criteria and fields do
not match the rubric exactly.

Resolver-based sampling is declared statically, so one tool cannot vary its
sampling count per document. `assess_prd` therefore covers single-batch
documents only. Long documents keep native client-model inference through
`assess_prd_batch`, which uses the same fixed three-resolver shape for one batch
at a time while the calling agent iterates the batch list. Forge stays stateless
and performs consolidation and scoring in `score_prd_extraction`.

Generating dynamic tool signatures per document was rejected as unnecessary
metaprogramming for the same capability.

Because orchestration is client-side, fragments are bound to their inputs. Each
plan has a fingerprint over its batch text and rubric version, and every
fragment carries that fingerprint plus its `run_index`. Scoring rejects stale
plans, repeated run indexes, and mixed runs, so a new supplemental answer
requires re-running the batch flow instead of silently scoring outdated
extractions.

Anticipated failures are raised as `ToolError` so their messages reach the
agent; the SDK would otherwise collapse them into "Error executing tool".

## Output Adapters

The domain core returns structured assessment data. Chat rendering, Excel
workbooks, and SharePoint publication are adapters, not scoring concerns. Excel
and SharePoint are deferred until the conversational review is validated;
Forge will not own SharePoint credentials as part of the scoring core.

## Offline Calibration

`forge.calibration` is a domain-side developer workflow, not an MCP assessment
tool. It creates exhaustive reviewer-label templates from an `Assessment`
without retaining source-document text or exposing Forge's prediction, and
compares fixed-version predictions with one or more human labels only after the
completed blinded sheets are merged. Reports include band and criterion agreement,
inter-reviewer agreement, ordinal band error, false-ready and false-not-ready
rates, contested labels, source mix, and low-sample warnings.

Calibration suites are bound to an exact rubric id and version. Mismatched
criteria, duplicate reviewers, unknown bands, and cross-version predictions are
rejected rather than silently compared. Tied human votes remain contested; the
system does not resolve disagreement in its own favour.

Headline calibration metrics include only `internal` cases. Public and
synthetic examples remain robustness diagnostics because implementation status,
popularity, or template provenance is not an independent readiness label.

## Portability

The scoring and ingestion packages must remain independent of MCP so they can be
reused by a future dashboard. MCP code is an adapter, not the domain core.

## Dashboard Mode (Optional, BYOK)

`forge_dashboard` (`src/forge_dashboard/`) is a second, optional adapter around
the same domain core, exposed as a small local FastAPI service for the Next.js
UI in `web/`. It exists because a browser has no MCP client to borrow a model
from. See D-033 for the full decision and rationale; this section only records
the resulting boundary.

- The dashboard is not installed or run by default. It lives behind the
  `dashboard` optional dependency group so `forge-mcp` and its default install
  never gain a provider SDK.
- The dashboard accepts a per-request LLM provider, model, and API key from the
  browser and calls it through `litellm`. The key is never written to disk, a
  database, or a log by the backend; it is held client-side for the browser
  session and resent with each request.
- Everything after the model call is identical to the MCP path: the same
  `build_extraction_prompt`, `parse_extraction`, evidence verification in
  `forge.extract.batch`, and deterministic scoring in `forge.score` are reused
  unmodified through `forge.service`. The dashboard backend only replaces MCP
  sampling with a direct LiteLLM call as the source of extraction completions.
- The dashboard keeps Forge's stateless supplemental-answer design (D-014):
  the browser accumulates `supplemental_answers` and resubmits the full list
  on every turn; the backend does not persist a conversation session.
- Uploaded documents are written to a local, gitignored working directory for
  the lifetime of the process only, addressed by an opaque document id; the
  backend does not expose raw filesystem paths to the browser.

A fourth provider option, `cursor`, does not call an LLM provider at all: it
authenticates to Cursor's Cloud Agents API with a Cursor-issued key and runs
extraction through a short-lived cloud agent instead of a direct model call.
See D-034 for the full rationale, cost/latency tradeoffs, and why it is
represented as a `provider` value rather than a separate concept.

## Dependency Strategy

Forge reuses maintained open-source parsing and chunking components before
implementing equivalent infrastructure. Dependencies or small, attributable
forks are preferred to copied code; modifications must retain upstream license
notices and stay narrow enough to rebase.

The evidence-specific orchestration remains Forge-owned: stable source block
identity, page and section provenance, exhaustive batch coverage, extraction
consolidation, and quote verification. These guarantees are domain behavior,
not generic chunking.

For long text, the initial integration target is `semchunk`, using returned
source offsets when an individual block must be split. Forge groups the
resulting blocks into bounded extraction batches and processes every batch.
Docling will be evaluated directly as a future structured or multimodal parser
adapter rather than importing a RAG stack.

`semchunk` is text-only and has no responsibility for images or diagrams.
Visual assets are a parallel input stream. Ingestion adapters detect PDF pages
containing raster or vector content and DOCX image relationships, and retain
only their source metadata.

Image bytes are produced on demand by `forge.ingest.visuals`, which renders a
PDF page or extracts an embedded DOCX image and enforces a size limit before
sampling. `observe_prd_visual` sends that render as `ImageContent` to the
client's model and returns a description carrying an explicit advisory note.
Observations never enter the evidence corpus or the score; a user-confirmed
fact must be resubmitted as a supplemental answer to become verifiable.

OCR-derived text may join the evidence corpus later, but only with explicit
image provenance and exact quote verification.

RAG-Anything is not used in the scoring path. Its text ingestion delegates
chunking to LightRAG, its retrieval is relevance-ranked rather than exhaustive,
and its full pipeline adds model, embedding, graph, and persistent-storage
boundaries that Forge deliberately assigns to the MCP client or does not need.
