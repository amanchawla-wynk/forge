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
      -> source-backed claim ledger and bounded requirement graph
      -> advisory cross-section consistency analysis
      -> extraction prompt and JSON schema
      -> client's LLM through MCP sampling, when supported
      -> evidence verification and extraction validation
      -> deterministic scoring and gates
      -> deep-review findings, deterministic audit, and remediation question
```

The target deep-review path does not collapse each rubric field to one value
before analysis. It retains verified claims with their exact quote, source
location, scope, phase, modality, and extraction-run identity. A bounded graph
links requirements, actors, metrics, dependencies, states, rollout rules, and
sections. Deterministic candidate generation and closed-set model
classification may identify possible contradictions, precedence conflicts,
undefined boundaries, stale requirements, or non-testable formulas. Python
verifies every cited source span before a finding reaches the user.

The graph is an advisory analysis structure, not a retrieval eligibility filter
or scoring authority. Exhaustive batching remains the basis for evidence
coverage, and only versioned rubric rules may affect readiness points or bands.
This bounded per-document graph does not require embeddings, community
summaries, or a general GraphRAG store.

The implemented deterministic path retains every verified field claim before
batch consolidation, records quote-local source offsets, and supplements model
extraction with a bounded source scan. It projects claims into an in-process
graph containing claim, milestone, metric, and event nodes with source-backed
schedule, declaration, and formula edges. It publishes mechanically provable
impossible ranges, conflicting named skip thresholds, conflicting exact or
post-launch timelines, and metric formulas that reference undeclared events.
The same structured source scan retains flattened table rows that sentence
splitting would destroy. Exact classification labels plus tier rows/domains can
prove incompatible enum mappings, while exact machine field names plus explicit
array/table/inline type declarations can prove schema-type conflicts. Explicit
product, variant, phase, surface, or fallback scopes partition declarations;
different scopes are not compared. These checks use no fuzzy matching or model
classification.

Exact machine identifiers additionally support three same-scope checks:
opposite polarity for one subject on one decision axis, duplicate ranks in one
named ordering, and cycles in explicit precedence edges. Timeline analysis
compares only commensurable values: two exact dates, or two relative windows
that do not overlap. Overlapping ranges and mixed absolute/relative schedules
abstain, because neither is a provable contradiction.

Every merged claim also receives a deterministic `ClaimInterpretation` carrying
its subject, scope, phase, and modality keys with `provenance: deterministic`.
It is explicit-language projection only and never a model's reading of intent.
`AssessmentResponse.deep_review` is presented before the readiness audit in the
dashboard, and the same baseline review is retained in remediation state.

Conflicts that Python cannot prove are handled by `forge.score.consistency`
under versioned taxonomy `1.1` (D-046, extended by D-050). Python enumerates bounded candidate
pairs from named subjects, the model returns only one relation index per pair,
three runs consolidate by strict majority with ties resolving to `unclear`, and
both quotes are re-verified before a finding is rendered from a fixed template.
MCP clients obtain the ledger through the `consistency` advisory kind and pass
it back to `score_prd_extraction`; the resulting findings are marked
`classified` and remain outside scoring.

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

Confirmed in practice: OpenCode and Cursor 3.22.7 do not support MCP sampling,
so `assess_prd` fails in both and the two-step fallback is the working path.
Cursor's public MCP documentation describes server and tool integration but
does not claim support for `sampling/createMessage`.

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
`contextualize_next_question` also expose the unified
`prepare_prd_advisory`/`apply_prd_advisory` agent fallback. Coverage requires
three independent completions; the other closed-set enrichments require one.

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

LangGraph remains an implementation option for durable execution, resumable
human interrupts, and multi-step orchestration. Adoption requires a spike
against the existing SQLite state machine and must preserve Forge's opaque
`review_session_id`, optimistic versioning, idempotency, ownership checks, and
event audit. If adopted, LangGraph's `thread_id` maps to `review_session_id`,
never to a vendor chat id.

LangChain is an optional adapter for tool invocation and structured model
output, not a domain boundary. Forge continues to own prompts, extraction
schemas, source verification, claim consolidation, and deterministic scoring.
A framework must not introduce provider credentials or direct model calls into
the MCP/core path.

General GraphRAG remains outside session identity and scoring-state persistence.
A Graphify-like static requirement graph may be built directly from Forge's
verified source blocks for advisory cross-section discovery. A larger graph or
property-graph framework should be adopted only if a measured prototype
outperforms that bounded design on representative PRDs.

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

`forge.review_eval` applies the same boundary to D-045 deep-review findings. It
is a separate offline developer workflow because finding detection and readiness
scoring have different labels and error costs. Reviewer sheets identify one
case, contain exact source fragments, and exclude Forge's prediction. Two
distinct reviewers are required before an internal case enters headline
metrics; strict-majority defects define recall, while contested defects remain
visible. Predictions are matched one-to-one using normalized quote containment,
optionally constrained by finding kind. The report exposes precision, recall,
blocker recall, false positives per case, human quote alignment, evidence
completeness, duplicate rate, per-kind metrics, and inter-reviewer agreement.
Thresholds are applied only after they are preregistered; this workflow never
changes scoring or review output.

`forge.proxy_diagnostics` runs the deterministic deep review against a proxy
artifact and reports finding recall, blocker recall, candidate coverage,
unmatched findings, and hard-negative violations. Its report is permanently
`calibration_eligible: false`, so it can guide detector work without being
mistaken for accuracy evidence. Candidate generation supports it with category
pairing that requires a shared trigger category plus at least two shared content
words, reserved budget so category pairs are not starved by exact-subject pairs,
quote-text deduplication, and exclusion of pairs already proved in Python.

`forge.proxy_labels` defines a separate closed schema for public-guidance AI
proxy panels. Every artifact is permanently typed as
`external_proxy_diagnostic`, `synthetic_ai_proxy`, calibration-ineligible,
headline-ineligible, advisory, and no-score-effect. It stores a source hash and
verified block-local evidence spans plus supported, hard-negative, compatible,
contested, and unclear labels. It is intentionally not convertible to the human
label DTOs above; both schemas forbid unknown fields. Proxy artifacts may drive
regression and transfer diagnostics or motivate a versioned expert-baseline
field change, but never weight, gate, band, severity, or organization-validity
tuning.

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
- Uploaded documents, generated artifacts, and revision plans are written to a
  durable local, gitignored dashboard directory with a SQLite index and opaque
  ids. Dashboard DTOs do not expose raw filesystem paths or internal extraction
  state to the browser.
- Dashboard inference is concurrency-limited and time-bounded, uploads have a
  configurable byte limit, SQLite uses secure local permissions and a busy
  timeout, and the server refuses non-loopback binding.

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
