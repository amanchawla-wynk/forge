# Architecture

## Boundary

Forge is a local Python MCP server. It owns document parsing, evidence
verification, rubric configuration, deterministic scoring, and remediation
planning. It does not own or authenticate to an LLM provider.

`forge-setup-cursor` and `forge-setup-opencode` (`src/forge/setup_cursor.py`,
`src/forge/setup_opencode.py`, sharing `src/forge/_client_setup.py`) are
separate, narrowly scoped CLIs that only write/merge a client's own MCP
config file (Cursor's `mcp.json`, OpenCode's `opencode.json`). Neither runs,
imports the server process, or touches document/domain code.

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

Confirmed in practice: OpenCode does not support MCP sampling, so `assess_prd`
fails there and the two-step fallback is the only working path. Cursor's
sampling support has not yet been confirmed either way in a live session (see
`docs/ROADMAP.md`).

Every sampling resolver checks the connected client's declared capabilities
itself (via the injected `Context`, see D-039) before building a `Sample`
request, and raises a plain, catchable error naming the fallback tool when
`sampling` isn't declared. Without this check, the SDK's own capability guard
fires first and raises a bare protocol-level error (`MCP error -32021:
Client did not declare the sampling capability...`) that bypasses Forge's
normal `ToolError` handling entirely, leaving the agent nothing useful to
read. `assess_prd`/`assess_prd_batch` point the agent at
`prepare_prd_assessment`; `detect_prd_framing`,
`discover_edge_case_question`, `assess_edge_case_coverage`, and
`contextualize_next_question` have no non-sampling fallback yet, so their
error says so explicitly and tells the agent to continue without that
enrichment rather than block the assessment.

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
- `contextualize_next_question`: optionally phrase the current `next_question`
  using facts already verified elsewhere in the same assessment, through one
  guardrailed, closed-set model choice (see below and D-035). Advisory only;
  never changes scoring.
- `detect_prd_framing`: classify the document as a problem fix, opportunity
  bet, compliance mandate, or migration/replatform through one closed-set
  model choice, then return the rubric-authored next-question variant.
- `discover_edge_case_question`: select one source-verified fact and one fixed
  edge-case type, then have Python render a concrete follow-up question. The
  model never authors the question and the selection never affects scoring.
- `assess_edge_case_coverage`: classify every deterministically applicable
  requirement/taxonomy pair through three closed-set sampling runs, verify
  positive evidence, consolidate pessimistically, and return the versioned
  ledger plus its next uncovered question.

Assessment responses return one highest-impact remediation question. The
checkpoint workflow keeps a `RemediationState` containing the source/rubric identity,
immutable verified baseline extraction, last assessment, framing, queued
questions, accepted answers, pending answers, and any edge-case ledger. MCP and
dashboard adapters persist that state in local SQLite behind a Forge-owned opaque
review id; the domain workflow remains independent of transport and model provider.

Submitting an answer records the user's exact text and returns the next queued
question without invoking extraction or scoring. By default, a checkpoint runs
after five answers, after collecting the remaining fields of a failed gate, or
when the user requests a rescore. The checkpoint sends only pending answer
blocks and affected criterion schemas to the connected model. It verifies and
merges criterion-local patches, deterministically rescores, and replaces the
question queue. The unchanged source PRD is not re-extracted.

The selected question names one `target_field`, one concise field-specific
prompt, and one answer requirement. It also retains all `missing_fields` for the
criterion audit. The planner may queue multiple missing fields internally, but
the client presents only one at a time. A checkpoint rescore removes questions
already satisfied by broader answers and determines the next queue; no batch of
subquestions is presented to the user.

That field-specific prompt is `base_question`, always the plain rubric text.
`question` may additionally carry a deterministic, filename-derived document
name (always on, no model call) and, only if the caller invokes
`contextualize_next_question`, one guardrailed model-selected fact already
verified elsewhere in the assessment. That tool's only valid model output is
a single integer choosing among an enumerated, pre-verified candidate list, or
`0`; anything else — malformed output, an out-of-range integer, extra
prose — mechanically falls back to the plain document-named question. No
model-authored sentence ever reaches the user; every word in an enriched
question was already checked against the source document before the tool ran.
Because Forge is stateless, this tool takes the same `extraction_json` already
submitted to `score_prd_extraction` and recomputes the assessment rather than
reading anything cached from a prior call.

Framing selection follows the same boundary. `detect_prd_framing` gives the
client model a rubric-declared option list and already-verified document facts;
the model returns only `{"framing": <int>}`. Python maps that index to an id
and chooses the corresponding `FieldSpec.framing_questions` string. Unknown or
invalid output uses `Rubric.default_framing`. MCP clients retain and resubmit
the resolved framing; the optional dashboard detects it once after initial
extraction and reuses it for subsequent turns so wording does not drift.

Edge-case discovery adds a second closed axis rather than opening generation.
The first axis contains independently verified source quotes; the second is a
fixed taxonomy of operational failure modes. `verify_run` separately locates
each item in list-valued fields before that item can become a candidate. Python
rejects any response outside the candidate/taxonomy product and uses the normal
rubric question instead. The returned question stays advisory until the user
answers it and that answer passes the standard supplemental-evidence flow.

The coverage ledger is the state carried across remediation turns. Each item
is keyed by an original-document requirement quote and taxonomy id. The
dashboard builds it after initial extraction; MCP clients use
`assess_edge_case_coverage`. A question copies that identity into the user's
`SupplementalAnswer`. On rescore, Python updates only matching cells, verifies
the answer in the criterion-bound supplemental block, and derives the edge-case
verdict from ledger completion plus platform/accessibility fields. The ledger
is echoed in every response because the server remains stateless.

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
attempts to use that block for another criterion. Pending answers do not affect
the displayed score until checkpoint verification. Responses expose collection
progress, the reason for the next checkpoint, accumulated verified answers, and
`next_question` as either one question or `null` when the verified assessment
has no remaining failed criterion.

Questions include the configured descriptions of their missing required fields.
`write_prd_revision` supports DOCX, Markdown, and text sources,
requires a new same-format output path, refuses to overwrite an existing file,
and appends a clarification section. `preview_prd_revision` and
`write_integrated_prd_revision` add source-bound section placement, explicit
per-edit approval, conflict resolution, and an audit appendix. The dashboard
fully reassesses the generated copy without supplemental answers; MCP callers
are instructed to run the same final assessment because writing itself never
borrows a model. PDF remains read-only because revision would not preserve an
editable source or its layout semantics.

Assessment responses expose disputed criteria and recommend up to two more
complete runs after initial disagreement. The fallback scorer already accepts
additional complete runs; native sampling remains a fixed three-call baseline.

Assessment and batching tools accept optional `ProductContextTerm` records.
They are carried separately on `NormalizedDocument`, rendered into a clearly
marked non-evidence prompt section, and included in the batch-plan fingerprint.
They are never rendered as `SourceBlock`s, so `locate_quote` cannot verify a
context-only claim. Changing context invalidates prior extraction fragments.

The one-answer/full-re-extraction loop proved cumbersome and expensive on a
real long PRD. A lightweight SQLite review-session repository now backs the MCP
and dashboard checkpoint APIs instead of a general workflow framework. Sessions
contain no provider keys, are addressed by opaque ids, bind state to the source
hash, rubric version, workspace, and local user, and have explicit expiry and
deletion behavior. It separates three identities:

- `review_session_id`: Forge-owned, opaque, and authoritative for workflow
  state;
- MCP transport session or optional host conversation id: advisory binding and
  audit metadata only, because MCP does not standardize a client chat id in
  `tools/call`;
- authenticated subject and tenant: mandatory ownership boundary if Forge gains
  remote or multi-user transport.

Every mutation carries `review_session_id`, `session_version`, and an idempotent
`operation_id`. SQLite updates the session and event log in one transaction.
Stale versions, duplicate operations, source/rubric/workspace mismatches, and
illegal workflow transitions are rejected with the current state and allowed
actions. A model or MCP client never chooses a session by filename or recency.

New conversations use a discovery/resume protocol. `find_prd_reviews` receives
an exact source path or dashboard document id, computes the current source hash,
and returns only matching session summaries. `resume_prd_review` requires the
chosen id and explicit confirmation when the client binding changed. With one
match Forge still offers **Resume**, **Start new**, and **Cancel**; multiple
matches are never resolved automatically. `start_prd_review` supports an
explicit `start_new` flag so two independent reviews of the same PRD remain
separate. A successful resume records a `client_binding_changed` event when
applicable and returns the authoritative `next_action` and next question.

LangGraph remains deferred. If adopted later, its `thread_id` maps to
`review_session_id`, never to a vendor chat id. GraphRAG has no role in session
identity or scoring-state persistence.

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

Initial and final full-document orchestration remains bound to its inputs. Each
plan has a fingerprint over its batch text and rubric version, and every
fragment must carry that fingerprint plus its `run_index`; scoring rejects
stale plans, repeated run indexes, and mixed runs. Remediation deltas use a
separate fingerprint over the baseline extraction identity, affected criterion
schemas, and pending answer blocks. A new answer invalidates only an unprocessed
delta plan, not the immutable full-document baseline.

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
- The dashboard uses the same durable SQLite review repository as MCP. The
  browser retains `review_session_id`, `session_version`, workflow state, and
  `next_action` in per-tab `sessionStorage`; it never persists the provider key
  server-side. A newly uploaded exact document triggers explicit review
  discovery and Resume / Start new / Cancel choices rather than auto-resume.
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
