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

## Immutable Source Baseline

Acquisition, parsing, projection, and scoring are separate operations. A source
adapter first acquires exact bytes plus origin metadata. A versioned parser then
produces normalized blocks and canonical nodes. Forge binds those outputs into
an immutable `DocumentSnapshot` identified by source SHA-256, source type,
parser fingerprint, normalized-schema version, and normalized-content hash.
Origin path and display metadata are deliberately excluded from content identity:
identical bytes parsed by identical code share a snapshot id, while each review
retains its own origin metadata.

SQLite review sessions persist the complete snapshot, including source bytes,
before the session is created. Reload revalidates the snapshot and rebinds its
origin-facing metadata to that session's source path. Checkpoints project
supplemental answers and product terminology onto the persisted normalized
document; they do not reopen or reparse the source. Discovery and resume compare
the current source type, parser fingerprint, normalized hash, snapshot id, and
rubric id/version. Sessions created before durable snapshots remain visible for
audit but are not resumable as exact matches.

`PreparedAssessmentInput` is the operation-local boundary shared by service,
MCP advisory, and dashboard paths. It holds one snapshot, rubric, projected
document, exhaustive batches, and extraction-plan fingerprint. The fingerprint
is versioned and binds snapshot id, parser fingerprint, normalized hash, rubric
id/version, product context, batch ids, and rendered batch text. A fragment from
a different parser, normalized baseline, rubric, context, or batch plan is
therefore rejected rather than scored against current evidence.

## Criterion Evaluation Shadow

Phase 2 adds a score-neutral criterion-evaluation representation beside legacy
field extraction. `forge.evaluate` separates strict model submissions from
verified records. The model may propose claims, support relations, gaps,
ambiguities, and contradictions, but Python resolves every citation within its
named source block, converts split-block offsets to canonical parent offsets,
and mints all evidence, claim, set, gap, issue, run, and evaluation identities.
The model cannot submit confidence, scores, weights, gates, bands, or verified
identifiers.

Each current field is projected into a versioned criterion assertion with
supporting, counterevidence, and context roles, hard negatives, and a
rubric-owned answer contract. Custom rubrics may declare the same contract
explicitly. `prepare_prd_evaluation` returns one prompt per criterion and source
batch. `apply_prd_evaluation` rejects missing, repeated, unknown, or stale
fragments; only exhaustive coverage can establish global unsupported status.
It preserves every verified support and counterevidence set, then consolidates
each assertion across independent runs by strict majority before deriving the
criterion status. Ties become `unclear`, including ties about contradictions.
Minority evidence remains auditable but cannot make a majority-supported
assertion contradictory.

Legacy verified extraction runs are also projected reversibly into evaluation
artifacts. This adapter is covered by score-parity tests and remains the only
evaluation origin that can be translated back into score inputs. Native
semantic evaluations are shadow audit records and cannot affect verdicts,
weights, gates, bands, consumer readiness, or remediation priority. New review
sessions transactionally persist their per-run artifacts in content-addressed
SQLite rows linked to the review; state schema version `3` reloads those records
without embedding them in mutable `state_json`.

`forge.evaluate.diagnostics` is an offline-only measurement boundary. Its suites
and reports are permanently `calibration_eligible: false` and
`score_effect: none`. It verifies source/rubric identity, reruns the production
evaluation verifier, measures abstention/agreement/evidence duplication, and may
cross-tab native and legacy statuses symmetrically. Legacy extraction is not a
ground-truth label. D-055 records why criterion-level agreement is not yet high
enough for evaluation gaps to drive Phase 3 questions.

Semantic identity excludes model-authored paraphrase. Support sets are keyed by
criterion/assertion, verified evidence ids, role, and relation; ambiguities are
keyed by assertion, verified evidence ids, and issue kind. Claims and alternative
wording remain visible audit fields. `forge.evaluate.labels` creates blinded
assertion sheets without predictions or scoring configuration and preserves
reviewer disagreement unless a strict majority exists.

When humans are unavailable, the same sheets may be completed by isolated agents
only if they are permanently typed `synthetic_ai_proxy` and
`calibration_eligible: false`. Proxy consensus can open an engineering shadow
experiment but cannot establish product quality or organization validity. D-058
allows Phase 3 question generation only for strict-majority native assertion
outcomes with verified evidence ids, bounded validation, deterministic fallback,
and no score effect.

`forge.questions` implements the first Phase 3 vertical slice without entering
the live remediation path. `prepare_question_generation` ranks eligible native
assertion outcomes deterministically and packages only verified issue/evidence
ids, exact evidence spans, the assertion description, and its rubric-owned
answer contract. The host may return one strict object containing the plan id,
one allowed issue id, and one question. `apply_question_generation` accepts the
wording only when it is one bounded question, uses no substantive tokens outside
the verified context, and contains no quoted phrase absent from exact evidence;
otherwise it emits the answer contract as a fallback. `apply_prd_evaluation`
exposes the preparation, while `apply_prd_question_generation` re-verifies the
entire submitted evaluation batch before applying the completion. The resulting
artifact is marked shadow and `score_effect: none`; `Question`, remediation
queues, sessions, dashboards, and scoring do not consume it.

`forge.questions.diagnostics` replays frozen completions through the production
apply boundary and measures accepted generation, fallback, unsupported-text
rejection, within-document duplication, deterministic preparation, and repeated
wording stability. `forge.questions.labels` creates prediction-free synthetic
proxy sheets for relevance, answerability, smallest scope, and unsupported
assumptions. D-060 records that the first internal study passed mechanical safety
but failed question quality. The live path remains blocked until plans are keyed
and deduplicated by issue, unresolved antecedents suppress dependent questions,
and gap records retain enough bounded decision detail to ask something narrower
than the field fallback.

D-061 adds bounded missing-decision detail to gap audit records while excluding
that wording from `gap_id`. Consolidation retains all distinct descriptions for
question experiments. The planner groups multi-run issue variants, deduplicates
shared ids across sibling assertions, defers later gaps in a criterion, and uses
verified evidence to render safe ambiguity/contradiction fallbacks. A fresh
three-run internal study showed that this improves relevance but not atomicity.
The next schema boundary is therefore the rubric evaluation contract: composite
legacy fields may project into several score-neutral atomic assertions with
explicit prerequisite edges and resolution contracts. Scoring continues to read
only legacy field extraction.

Rubric `0.8.0-atomic-evaluation-shadow` implements the first complete atomic
vertical slice for dependency readiness. `AssertionSpec` carries a bounded
resolution contract and same-criterion prerequisite ids. Rubric validation
rejects duplicates, unknown ids, self-dependencies, and cycles. Native
verification and consolidation enumerate evaluation assertions rather than
legacy fields. The legacy adapter fans one verified field value out to every
mapped shadow assertion and retains the untouched extraction for round-trip
scoring, so atomic evaluation cannot alter a verdict or band. Question planning
requires every prerequisite to have a three-run strict-majority supported
outcome before a dependent issue is eligible.

Operational readiness is the second contract `1.1` slice (D-063). A required
scope atom selects applicable service-expectation dimensions; dimension atoms are
optional and become question-eligible only when the evaluator reports a verified
gap after that scope is supported. Monitoring, support, and incident ownership
are separate required atoms. Recovery procedure and optional degraded-mode or
restore behavior depend on a supported diagnostic-method atom. This pattern
avoids pretending that every service needs every SLO dimension while preserving
atomic remediation when a dimension does apply.

Rollout is the third contract `1.1` slice (D-064). The rollout mechanism gates
threshold and rollback-trigger atoms; promotion additionally depends on entry
criteria and an observation window, and rollback procedure depends on its
trigger. Decision ownership, pause/stop authority, and rollback execution are
separate required atoms. A communication-impact scope gates optional audience
actions. This keeps the dependency graph explicit without treating every launch
channel as applicable.

Instrumentation is the fourth contract `1.1` slice (D-065). Event declarations
gate optional properties. A local metric-definition reference plus declared
events gate the metric formula; optional filters and dimensions follow that
formula. Operational-signal scope gates one required named failure signal, its
diagnostic use, and optional channel-specific atoms. Prerequisites remain within
one criterion, avoiding hidden cross-criterion consolidation state.

Acceptance criteria are the fifth contract `1.1` slice (D-066). Static atoms
represent completion, pass, fail, applicability scope, requirement inventory,
mapping, and completeness; requirement names remain document data inside those
records rather than becoming dynamic schema ids. Requirement mapping depends on
the launch-critical set plus pass/fail conditions, and completeness depends on
the mapping. Optional boundary mappings depend on both an applicable boundary set
and failure/boundary scope. The legacy gate continues to read only field
extraction.

D-067 makes deterministic question rendering an explicit generation mode rather
than reporting it as model fallback. The atomic diagnostic runner records gate
thresholds before review, verifies three fresh evaluation runs, renders one
stable rubric/evidence question per eligible plan, and creates prediction-free
proxy sheets. The first 0.8 run passed unsupported-text, duplication, and
stability gates but failed relevance, answerability, atomicity, and assumption
gates. No deterministic question artifact is consumed by live remediation.

D-068 advances this shadow contract to
`0.8.1-atomic-question-corrections-shadow`. Consolidation still records every
verified contradiction for audit, but a question target receives only canonical
relation/evidence-pair variants supported by a strict majority of independent
runs. A gap target may carry one exact verified subject span from a supported
prerequisite or same-field sibling; this context is represented separately from
issue evidence so it cannot be mistaken for proof of absence. Optional framing
can select only an explicit rubric-owned field variant and never changes target
eligibility or scoring. These corrections remain outside remediation/session
state.

D-069 makes evidence-set relations a required integrity boundary. Exact quotes
and claims are not semantic support by themselves: every claim must be referenced
by an evidence set, and that set must include the claim's assertion id. Invalid
runs fail before consolidation. Python still does not infer a support relation.

D-070 and D-071 advance the current shadow rubric to
`0.9.1-applicability-contracts-shadow`. Remaining composite criteria use explicit
contract `1.1` assertions and criterion-local prerequisite DAGs. Applicability
roots precede conditional behavior for transitional states, instrumentation, and
sensitive data. Acceptance subject, open-question identity, alternative
disposition, and assumption identity are explicit prerequisite evidence sources.
Only declared prerequisites may contextualize a gap; an arbitrary same-field
sibling cannot. These additions remain reversible through the untouched legacy
extraction adapter and are not persisted into remediation state.

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
- `prepare_prd_evaluation`: create exhaustive criterion-by-batch semantic
  evaluation prompts for optional shadow review.
- `apply_prd_evaluation`: verify and conservatively consolidate those shadow
  evaluations without changing readiness scoring.
- `write_prd_revision`: materialize approved supplemental answers into a new
  editable PRD copy without overwriting the source.
- `complete_prd_review`: verify extraction from the exact generated revision,
  persist its full no-supplemental assessment, and atomically complete the
  originating durable review.
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

Every scored projection carries one `evaluation_revision`. Applying a
checkpoint increments it and rebuilds the assessment, narrative report,
deterministic deep review, and question queue together. Per-item evidence for
list-valued fields is serialized in review state but omitted from model-facing
JSON schemas. Edge-case remediation materializes one queue item per uncovered
requirement/taxonomy cell, so advancing one cell does not depend on mutating an
unrelated broad field question.

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
and appends a clarification section. The MCP revision tools are session-bound:
they require `review_session_id`, optimistic `session_version`, and idempotent
`operation_id`; derive source and answers from verified durable state; enforce
`REVISION_READY -> AWAITING_REVISION_APPROVAL -> FINAL_ASSESSMENT_REQUIRED`;
and reject plans whose exact answer multiset differs from the session. The
dashboard follows the same workflow states and fully reassesses the generated
copy without supplemental answers. PDF remains read-only because revision would
not preserve an editable source or its layout semantics.

Revision writes stage a same-filesystem temporary artifact, persist its digest
in operation metadata, and publish without overwriting. A retry can recover a
crash between publication and the SQLite transition. Deleting or expiring a
session removes only temp paths that match Forge's deterministic revision-temp
name and parent directory. The generated artifact path and hash remain bound to
the session; `complete_prd_review` refuses a missing or changed artifact and
accepts only a full extraction of that copy without supplemental answers.

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
Pending answer UUIDs are also copied into the durable supplemental-answer record,
so evidence block identity survives checkpointing, restart, and later document
reconstruction. Loading a version-1 session repairs this nested identity from
the existing pending-answer id without claiming that the stored state schema was
already upgraded.

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
- Edge-case coverage uses the rubric-declared repeated-run count and the same
  pessimistic modal consolidation as MCP/fallback coverage. A failed or malformed
  run fails the dashboard assessment rather than silently omitting the ledger.
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
`spikes/parser_benchmark.py` compares the current parser with optional direct
Docling and PyMuPDF4LLM controls without adding either package to Forge. It emits
repeat timing, deterministic-output, text-retention, structure, image, page, and
provenance measurements. Docling remains a future structured or multimodal
parser candidate rather than an adopted dependency. The representative PDF and
DOCX measurements in `reports/parser benchmark 2026-09-26.md` justify a bounded
adapter prototype, but manual quote, table-order, and provenance review is still
required before that parser can supply score-eligible evidence.

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
