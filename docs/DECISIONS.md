# Decision Log

Material decisions are append-only. If a decision changes, add a new entry that
supersedes the old one.

## D-001: Begin With PRDs

- Status: accepted
- Decision: Build and validate PRD readiness first. Defer BRDs to a separate
  rubric and theory.
- Reason: PRDs and BRDs serve different downstream decisions; combining them
  would weaken validity.

## D-002: Measure Completeness And Actionability

- Status: accepted
- Decision: V1 does not judge whether the product bet is correct. It judges
  whether downstream consumers can act from the document.
- Reason: This is bounded, observable, and substantially more defensible.

## D-003: Advisory, Not Approval Gate

- Status: accepted
- Decision: Results guide authors and reviewers and do not automatically block
  work.
- Reason: Calibration does not yet justify governance authority, and hard gates
  create stronger gaming incentives.

## D-004: Fixed, Versioned Rubric With Advisory Output

- Status: accepted
- Decision: Although the assessment is advisory, each score uses an explicit,
  versioned rubric. Company tuning occurs through configuration.
- Reason: A rubric that changes per document cannot support reproducibility or
  meaningful comparison.

## D-005: Extraction, Evidence, Then Deterministic Scoring

- Status: accepted
- Decision: The LLM extracts structured facts and quotes. Python verifies and
  scores them. The LLM never assigns points.
- Reason: Reduces subjectivity, verbosity bias, and score hallucination.

## D-006: Client LLM Only

- Status: accepted
- Decision: Forge borrows the connected client's LLM. It will not include API
  keys, provider SDKs, or direct Anthropic/OpenAI/Bedrock/Ollama calls.
- Reason: Local setup should reuse the model the user already selected and
  avoid additional credentials and billing paths.
- Consequence: Cross-client model consistency cannot be assumed. Model metadata
  and extraction agreement must be visible.

## D-007: MCP Sampling Plus Agent Fallback

- Status: accepted
- Decision: Use MCP sampling when the host supports it and preserve a two-step
  prepare/submit workflow for hosts that do not.
- Reason: Sampling capability support varies among Cursor, Copilot, and other
  hosts. Requiring it exclusively would undermine portability.

## D-008: Local First, Dashboard Later

- Status: accepted
- Decision: Ship a local stdio MCP server first. Keep domain code independent
  so a dashboard can reuse it later.

## D-009: No Generic "Superpowers" Skill

- Status: accepted
- Decision: Use `AGENTS.md` plus canonical repository documents rather than a
  broad project skill.
- Reason: Repository instructions are portable across coding agents and avoid
  duplicating mutable project state. A focused distributable Forge skill may
  be reconsidered after the MCP workflow stabilizes.

## D-010: Conversation First, One Question Per Turn

- Status: accepted
- Decision: The primary V1 experience is an initial PRD assessment followed by
  exactly one highest-impact clarification question per turn. Each answer is
  retained as supplemental user evidence, the assessment is recomputed, and
  only then is the next question selected.
- Reason: A focused adaptive loop is less overwhelming and more useful than a
  one-shot list of every possible question.
- Consequence: The current top-five question response is transitional and the
  supplemental-answer rescore flow is the next product-critical capability.

## D-011: Treat The Broad Review Prompt As Coverage, Not A Scoring Model

- Status: accepted
- Decision: Use the supplied requirement, gap, risk, testability, operations,
  security, and performance categories as input to rubric and report design.
  Do not adopt its fixed percentages, numeric risk formula, project-health
  estimates, or status labels as authoritative V1 scoring rules.
- Reason: Those numbers have no supplied definitions, evidence model, or
  calibration data. Adopting them would add false precision and allow the LLM
  to make unsupported judgments.

## D-012: Remain Advisory And Avoid Predictive Claims

- Status: accepted
- Decision: Forge may identify evidence-linked gaps and risks, but it does not
  issue Go/No-Go or Block Development decisions and does not estimate rework,
  production risk, testing risk, or defect leakage without a separately
  validated model.
- Reason: These claims exceed PRD completeness assessment and cannot currently
  be defended from source-document evidence.

## D-013: Defer Excel And SharePoint To Output Adapters

- Status: accepted
- Decision: Conversation is the first-class V1 output. Excel workbook export
  and SharePoint publication are deferred optional adapters over the same
  structured result.
- Reason: Reporting automation should not delay validation of the assessment
  and remediation loop or leak integration concerns into scoring code.

## D-014: Criterion-Bound Stateless Supplemental Evidence

- Status: accepted
- Decision: Each conversational answer is submitted as a criterion identifier
  plus answer text. The client resubmits the accumulated list every turn; the
  server does not persist a session. Supplemental evidence may receive credit
  only for its named criterion and retains distinct provenance in verification.
- Reason: This provides an auditable conversational loop without introducing a
  database, silently modifying the PRD, or allowing one broad answer to inflate
  unrelated criteria.

## D-015: Derive Narrative Reports Deterministically

- Status: accepted
- Decision: The concise report shown before audit detail is generated in Python
  from the final assessment and remediation ordering. The LLM does not write a
  second review narrative.
- Reason: A generated interpretation could contradict verified verdicts, add
  unsupported claims, or obscure why the deterministic result was reached.

## D-016: Reuse Open-Source Document Infrastructure First

- Status: accepted
- Decision: Before writing parsing or chunking infrastructure, evaluate a
  maintained open-source component and prefer a dependency or narrow attributed
  fork when it meets Forge's requirements. Use `semchunk` for oversized text
  splitting with exact source offsets. Evaluate Docling directly for future
  structured and multimodal ingestion. Do not adopt RAG-Anything or LightRAG in
  the readiness-scoring path.
- Reason: Commodity splitting and format parsing should not be rebuilt. Forge's
  custom code should be limited to its differentiating guarantees: exhaustive
  coverage, stable provenance, criterion extraction consolidation, exact quote
  verification, and deterministic scoring.
- Evidence: RAG-Anything delegates text chunking to LightRAG and flattens text
  blocks before insertion. Its full pipeline requires model and embedding
  callbacks plus persistent graph/vector storage. A local spike confirmed that
  `semchunk` returns exact source offsets on Python 3.14, while Docling exposes
  modular conversion and hybrid chunking under an MIT license.

## D-017: Separate Text Evidence From Visual Interpretation

- Status: accepted
- Decision: `semchunk` handles text only. Forge detects and preserves embedded
  visual assets through parser adapters. Verifiable text recovered from images
  may receive scoring credit with explicit visual provenance; model-derived
  interpretations of diagrams remain advisory and cannot change the readiness
  score.
- Reason: Diagram semantics cannot satisfy the existing exact-quote evidence
  rule. Silently ignoring visuals is also unsafe, so assessments must expose the
  limitation until multimodal extraction and validation are implemented.

## D-018: Require Complete, Schema-Exact Extraction Fragments

- Status: accepted
- Decision: A batched run must submit one fragment per prepared batch, and each
  fragment must contain every rubric criterion and every field exactly once.
  Incomplete, duplicated, or unknown fragments, criteria, and fields are
  rejected rather than silently treated as absent. A `not_applicable` claim is
  also evidence-checked: its reason must be locatable in that batch.
- Reason: Without these checks, an empty or sparse submission would look like a
  complete run, produce high apparent agreement, and let unsupported
  `not_applicable` claims remove criteria from the scoring denominator.
- Consequence: `prepare_prd_assessment` now returns `extraction_batches`
  instead of a single `extraction_prompt`. This is a breaking pre-release
  change to the fallback tool response.

## D-019: Per-Batch Native Sampling Instead Of Dynamic Tool Signatures

- Status: accepted
- Decision: Keep native MCP sampling for long documents by exposing
  `list_prd_batches` and `assess_prd_batch`, where one tool call samples the
  client model three times for a single batch. The calling agent iterates the
  batches and submits the collected fragments to `score_prd_extraction`.
- Reason: The MCP Python SDK resolves sampling dependencies from a statically
  analyzed signature, so one tool cannot vary its sampling count per document.
  Generating per-document tool signatures would add fragile metaprogramming for
  no additional capability, and Forge still never contacts an LLM provider.
- Consequence: `assess_prd` remains the single-call path for small documents.
  Batch orchestration is client-side, which keeps the server stateless.

## D-020: Bind Fragments To A Plan Fingerprint And Run Index

- Status: accepted
- Decision: A batch plan is identified by a fingerprint over its batch text and
  rubric version. Native sampling stamps every fragment with that fingerprint
  and its `run_index`. Scoring rejects fragments from a stale plan, a repeated
  `run_index`, or fragments from different runs submitted as one run.
- Reason: Client-side orchestration is stateless, so nothing else prevents an
  agent from scoring extractions taken before the latest supplemental answer,
  or from submitting one run three times and reporting fabricated test/retest
  agreement.
- Consequence: Recording a new supplemental answer invalidates an existing
  batch plan, and the agent must re-run the batch extraction flow.

## D-021: Report Anticipated Tool Failures To The Agent

- Status: accepted
- Decision: Expected failures in MCP tools and sampling resolvers are raised as
  `ToolError` so the agent receives the message, including unknown batch ids,
  stale plans, schema mismatches, and the redirect from `assess_prd` to the
  batched flow.
- Reason: The SDK reduces other exceptions to "Error executing tool", which
  hides the information an agent needs to self-correct and makes the documented
  batched workflow undiscoverable.

## D-022: Advisory Visual Observations Through Client Vision Sampling

- Status: accepted
- Decision: Forge renders a detected visual on demand and sends it as
  `ImageContent` through MCP sampling. The returned description is advisory,
  carries an explicit scoring note, and never enters the evidence corpus or the
  readiness score. A fact confirmed from an image must be resubmitted as a
  supplemental answer to become scoreable.
- Reason: This closes the multimodal blind spot without weakening the
  exact-quote evidence rule or letting model interpretation of a diagram move a
  score.
- Consequence: Image bytes stay out of the normalized document and are produced
  only for an explicit observation request, subject to a size limit. Clients
  without image sampling lose only this tool.

## D-023: Permit Objective Field Constraints In Rubrics

- Status: accepted
- Decision: A rubric field may declare a regular-expression constraint and a
  plain-language extraction requirement. Python awards credit only when both
  the extracted value and its verified evidence quote match the constraint.
  The generic rubric initially uses this for quantified metric baselines and
  targets and concrete measurement windows.
- Reason: A fluent but hollow PRD filled every field and received the same
  score as the complete corpus anchor. Exact quote verification proves that
  words exist, but not that phrases such as "improve meaningfully" are
  measurable. Objective constraints close that specific gap without asking the
  LLM to judge quality or hardcoding company-specific prose rules in scoring.
- Consequence: The bundled rubric advances to `0.2.0-untuned`. Constraints must
  remain mechanically checkable and configurable. They do not solve generic
  filler in requirements and other qualitative fields, and they are not
  calibrated until tested against human-labelled company PRDs.

## D-024: Calibrate Only Against Independent Human Labels

- Status: accepted
- Decision: Weights, gates, and bands may be tuned only against representative
  PRDs with independent document-level human readiness labels. Public and
  synthetic PRDs without those labels may expand format and adversarial test
  coverage but cannot serve as calibration truth. Calibration suites contain
  predictions and reviewer verdicts, not source-document text, and are bound to
  an exact rubric version. Reviewers receive blinded sheets without Forge's
  prediction; labels are merged with predictions only after review.
- Reason: The evaluated Kaggle corpus is combinatorial synthetic structured data
  with no per-document quality label and contradictory license metadata. The
  evaluated Hugging Face corpus is repetitive generated prompt/response text
  with one text column, no quality labels, and no declared license. Treating
  either as ground truth would tune Forge toward generator conventions rather
  than downstream-team actionability.
- Evidence: `karmukilandk/prd-synthetic-data` on Kaggle and
  `Sajjadcube/PRD_dataset_new` on Hugging Face, reviewed on 2026-09-22.
- Consequence: Forge provides an offline calibration evaluator that measures
  model-to-human and inter-reviewer agreement, band distance, false-ready and
  false-not-ready rates, and per-criterion agreement. Until enough internal
  labels exist, `prd.v0.yaml` remains explicitly untuned.

## D-025: Derive Specialist Views Instead Of Chaining Specialist Judges

- Status: accepted
- Decision: Forge reports exhaustive structured gaps grouped by affected
  downstream consumer. These technical, UX, data, risk, leadership, and
  go-to-market views are deterministic projections of failed criteria and do
  not invoke additional specialist agents or change scoring.
- Reason: Review of `dimospapadopoulos/multi-agent-prd-reviewer` found useful
  role-specific presentation, but its sequential technical, UX, and legal
  critiques are unconstrained prose passed from one model call to the next. Its
  validator uses keyword presence, can exceed 100 points, requires a provider
  API key, and does not evidence-check specialist findings. Copying that
  architecture would weaken Forge's trust boundary.
- Consequence: Each Forge gap names the criterion, verdict, missing fields,
  affected consumers, gate status, and configured rationale. Richer advisory
  checks such as performance, observability, accessibility, retention, and
  consent may be added as configurable coverage later, but cannot affect the
  readiness band without evidence rules and human-labelled calibration.

## D-026: Escalate Disagreement Without Inflating Confidence

- Status: accepted
- Decision: Keep three native sampling runs as the baseline. If their criterion
  verdicts disagree, report the disputed criteria and recommend up to two
  additional complete fallback runs. Confidence remains observed agreement and
  may decrease when broader sampling reveals instability.
- Reason: Repeating a call solely to produce a larger number would manufacture
  confidence. Five independent runs provide a more robust majority and expose
  ambiguous extraction, but cannot establish correctness without external
  labels.
- Consequence: Forge never selects favourable runs or rounds confidence upward.
  The user-answer loop is the preferred way to turn ambiguous implicit content
  into explicit, consistently extractable evidence.

## D-027: Materialize Approved Answers Into A New Revision

- Status: accepted
- Decision: Conversational answers remain supplemental evidence during review.
  On explicit request, Forge may append them to a new DOCX, Markdown, or text
  revision grouped by criterion. It refuses to overwrite the source or an
  existing output and does not modify PDFs.
- Reason: Rescoring answers is useful, but authors also need the improved PRD as
  a durable artifact. An explicit new-copy operation preserves provenance and
  avoids silently pretending the original contained later clarification.

## D-028: Adopt Expert-Prior Coverage, Not External Weights

- Status: accepted
- Decision: Advance the bundled rubric to `0.3.0-expert-prior` with required
  evidence for transitional/degraded and platform/accessibility states,
  operational monitoring/support signals, and data-lifecycle controls. Retain
  Forge's deterministic verdict credits and existing criterion weights.
- Reason: These dimensions from `multi-agent-prd-reviewer` directly affect
  whether design, engineering, QA, operations, and risk can act. Its keyword
  matching, severity weights, passing score, and specialist-generated judgments
  remain too gameable and unsupported to borrow.
- Consequence: The new version is a stronger expert prior, not a calibrated
  rubric. Its behavior is locked by adversarial fixtures and must be revisited
  when representative labels become available.

## D-029: Keep Implementation Context Outside PRD Evidence

- Status: accepted
- Decision: Callers may provide a small terminology glossary grounded in an
  implementation repository. The extractor may use it only to disambiguate
  product names and internal terms. Context is excluded from source blocks,
  quote verification, and score credit, and changes the batch-plan fingerprint.
- Reason: The `movies_ios` repository establishes that both sample PRDs concern
  Xstream Play's Rush/Microdrama product and clarifies terms such as Sampling,
  My Shows, package/collection, and Data Saver. It also exposes contradictions
  that code cannot resolve as product intent. Crediting implementation facts
  would turn PRD completeness into implementation archaeology and hide missing
  decisions from authors.
- Consequence: Context can improve extraction stability and produce more
  relevant questions, but business evidence, targets, acceptance rules, and
  conflict resolution must still appear in the PRD or an explicit supplemental
  answer before receiving credit.

## D-030: Ask One Missing Field Per Turn

- Status: accepted
- Decision: Remediation selects the highest-priority failed criterion but asks
  only for its first missing required field. Every question exposes a
  `target_field` and one answer requirement while retaining the complete
  criterion gap in `missing_fields`. The document is rescored after every turn.
- Reason: Criterion-level prompts such as “state the problem, affected users,
  evidence, and cost” are cognitively heavy and encourage incomplete answers.
  Field-sized questions are easier to answer and let the next turn adapt when
  one response happens to cover multiple fields.
- Consequence: `band_if_answered` simulates only the targeted field. A
  multi-field gate remains active until its final missing field is answered.
  The bundled rubric advances to `0.3.1-expert-prior`.

## D-031: Keep Remediation Questions Plain And Specific

- Status: accepted
- Decision: Every required bundled-rubric field has an explicit conversational
  question. Questions ask for the missing fact or decision directly, avoid
  internal identifiers and document-centric wording, and retain qualifiers
  needed for deterministic validation. `answer_requirements` includes both the
  field description and any configured value requirement.
- Reason: Generic prompts such as “What should the PRD say about metric link?”
  sound mechanical and make users translate implementation terminology before
  answering. Plain, field-sized questions reduce that friction without changing
  scoring semantics.
- Evidence: Wording principles were informed by Humanizer v3.0.0 by Siqi Chen
  (MIT), reviewed on 2026-09-23. Forge independently authors its PRD-specific
  questions and does not bundle the external skill or runtime.
- Consequence: The fallback remains defensive behavior for external rubrics;
  tests require every required field in the bundled rubric to configure its own
  question. The bundled rubric advances to `0.3.2-expert-prior`.

## D-032: Ship A Source-Backed Expert Baseline

- Status: accepted
- Decision: Forge ships a cross-industry expert baseline that is usable without
  company templates or labels. The rubric versions its published sources,
  exposes `calibration_status: expert_baseline`, asks atomic evidence-checked
  questions, and reserves `organization_validated` for later independent
  internal review. The top readiness band requires every applicable criterion
  to be present, not merely a high weighted average.
- Reason: Users need a working reviewer before an organization can assemble a
  labelled corpus. Published PRD templates alone omit material accessibility,
  privacy, rollout, and operational concerns, so the baseline also uses GOV.UK
  service standards, ICO lifecycle guidance, and Google SRE launch practice.
  No reviewed public corpus combined real PRDs, clear reuse rights, and
  independent quality labels; treating workflow status or synthetic examples as
  calibration truth would manufacture confidence.
- Evidence: Atlassian's PRD template; 37signals' worked Shape Up pitches;
  GOV.UK Service Standard points 1, 5, 9, 10, and 14; Google SRE's reliable
  launch guidance; and ICO data-principle guidance, reviewed 2026-09-23. The
  exact URLs and contributions are recorded in `docs/EXPERT_BASELINE.md` and
  `prd.v0.yaml`.
- Consequence: The bundled rubric advances to `0.4.0-expert-baseline` with 15
  criteria. Public and synthetic cases are excluded from headline calibration
  metrics, while internal labels can later validate or tune the baseline.

## D-033: Optional Local Dashboard With Bring-Your-Own-Key Inference

- Status: accepted
- Decision: Add an optional, separately packaged local dashboard
  (`forge_dashboard`, a FastAPI service, plus a Next.js UI in `web/`) as a
  second, non-default way to run Forge's existing ingestion, extraction, and
  deterministic scoring core. Unlike the MCP server, the dashboard has no
  connected MCP client to borrow a model from, so it accepts a user-supplied
  LLM API key (Anthropic, OpenAI, or Gemini through LiteLLM) for the sole
  purpose of driving extraction calls for that user's own local session.
  - The MCP server (`forge-mcp`, `src/forge/mcp/`) and the core domain
    packages (`ingest`, `extract`, `rubric`, `score`) are unchanged and remain
    exactly as governed by D-006: no API key, no provider SDK, no direct
    provider calls anywhere in that path or its default install.
  - The key is never persisted to disk, a database, or a log by the
    dashboard backend. It is held in the browser for the session and sent
    per-request to the local FastAPI process, which forwards it to LiteLLM
    for that call only and does not write it anywhere.
  - `litellm` and the dashboard's web dependencies live behind a `dashboard`
    optional dependency group (`pip install forge[dashboard]` /
    `uv sync --extra dashboard`), so installing or running the MCP server
    never pulls in a provider SDK.
  - The dashboard reuses `forge.service`, `forge.ingest`, `forge.extract`,
    `forge.rubric`, and `forge.score` unmodified; it only replaces the
    "borrow the MCP client's model" step with "call the user's own key
    through LiteLLM," using the same extraction prompts, the same evidence
    verification, and the same deterministic scoring engine.
- Reason: The user explicitly asked for a local web dashboard that supports
  Claude, OpenAI, and Gemini directly, which structurally requires accepting a
  key somewhere outside an MCP client. Confining that exception to a clearly
  labelled, opt-in, separately installed surface preserves D-006 for the
  primary MCP distribution instead of quietly weakening it project-wide.
- Consequence: `AGENTS.md`'s "never require, store, or accept an API key" rule
  now has one documented, narrow exception: the optional dashboard's
  per-request, browser-held BYOK flow. Any future change that stores a key on
  disk, logs it, or adds it to the default install must be treated as a new
  decision, not a natural extension of this one.

## D-034: Cursor Cloud Agents As A Second Dashboard Inference Path

- Status: accepted
- Decision: The dashboard accepts a fourth `provider` option, `cursor`, for
  people who want to avoid configuring Forge as an MCP server entirely. A
  Cursor API key (generated at `cursor.com/dashboard/api`) is not an LLM
  provider key and cannot go through LiteLLM, so `forge_dashboard.cursor_agent`
  calls Cursor's Cloud Agents API directly: it creates one short-lived,
  no-repo cloud agent per extraction call, polls its single run to
  completion, reads the agent's final reply as the extraction JSON, and
  best-effort archives the agent afterward.
- Reason: The user asked for a way to reuse a key generated from Cursor
  instead of a per-provider key, for dashboard users who don't want MCP.
  Cursor's public API for this purpose is the Cloud Agents API, not a
  synchronous completion endpoint; representing it as a fourth "provider" in
  the same BYOK flow was simpler than inventing a separate concept for it.
- Consequence: This path is slower (cloud VM boot plus reasoning time before
  the run reaches `FINISHED`), billed against the caller's Cursor plan/agent
  quota rather than raw token pricing, and sends PRD text to Cursor's cloud
  infrastructure for that run rather than staying fully local — the dashboard
  UI states this explicitly when `cursor` is selected. The key still follows
  D-033: forwarded per request only, never written to disk, a database, or a
  log. Model selection is optional for this provider (Cursor resolves the
  caller's configured default when omitted); the exact `model.id` values in
  Cursor's catalog are user-supplied free text rather than a fixed list,
  since they are internal to Cursor's account/team configuration.

## D-035: Guardrailed, Closed-Set Contextualization Of Remediation Questions

- Status: accepted
- Decision: Remediation questions gain two additive layers on top of D-031's
  plain rubric-owned text, neither of which lets the model author free
  user-facing prose. Level 0, always on, no model call: every
  `Question.question` is deterministically prefixed with the document's
  filename-derived display name (`Question.base_question` keeps the original
  static string for audit and backward compatibility). Level 1, exposed
  through a new `contextualize_next_question` tool: the connected model
  performs exactly one closed-set choice among up to five already-verified
  `SatisfiedFieldEvidence` facts pulled from the same scored assessment
  (same-criterion fields first, then other satisfied criteria); the model's
  only legal output is `{"choice": <int>}`, where the integer is one of the
  enumerated indices or `0`. `parse_choice` mechanically rejects anything
  else — malformed JSON, extra keys, non-integers, booleans, out-of-range
  values, or any prose — and falls back to the Level 0 question with no error
  surfaced to the caller. When a choice is accepted, Python, never the model,
  renders the final sentence by concatenating the rubric's `base_question`,
  the display name, the chosen field's rubric-owned description, and its
  already source-verified quote.
- Reason: The user asked for questions that read as specific to the document
  under review, citing typed-decision "System 1" models such as Laya
  (https://laya.convaiinnovations.com/) as a reference for guardrails strong
  enough to make model generation predictable. Forge cannot bundle a separate
  non-autoregressive classifier without breaking D-006 (client-LLM-only, no
  bundled models or provider keys), but the same core guarantee — the output
  space is closed, so hallucination has nowhere to hide — is achievable by
  restricting the *borrowed* client model to a bounded classification task
  over facts Forge already verified, instead of a free-text generation task.
  This keeps D-005's "LLM extracts, Python judges" boundary intact: the model
  never sees criterion weights, never writes a sentence that reaches the
  user, and every word available for reuse was already checked against the
  document by `document.locate_quote` before this module ever saw it.
- Consequence: `CriterionResult` gains `satisfied_fields` (verified value,
  quote, and field description per already-satisfied field); this is
  read-only audit data and never re-enters `score()`. `Question` gains
  `base_question`; existing exact-string assertions on `Question.question`
  were updated to expect the Level 0 prefix. `contextualize_next_question` is
  stateless like every other tool: callers resupply the same
  `extraction_json` already submitted to `score_prd_extraction`, since Forge
  retains no session between calls. The tool is advisory phrasing only,
  documented as never able to change `missing_fields`, `answer_requirements`,
  gates, weights, or the band.

## D-036: Select Question Phrasing By Document Framing

- Status: accepted
- Decision: The bundled rubric declares four closed-set document framings:
  `problem_fix`, `opportunity_bet`, `compliance_mandate`, and
  `migration_replatform`. A required field may provide a rubric-authored
  `framing_questions` variant while retaining its D-031
  `remediation_question` as the safe default. The connected model may select
  only one declared framing index through `detect_prd_framing`; malformed,
  extra-keyed, non-integer, or out-of-range output resolves to the rubric's
  `default_framing`. Framing changes wording only. It never changes required
  fields, evidence rules, verdicts, weights, gates, band thresholds, question
  ordering, or `band_if_answered`.
- Reason: A single "problem" phrasing is not coherent across product bets.
  The Micro Dramas PRD describes an emerging-format and audience opportunity,
  not an existing user failure, so asking "what goes wrong for users today?"
  is a category error even though the underlying rubric field — why this is
  worth doing — is still missing. A reviewer with document context should ask
  what opportunity is being pursued and the cost of waiting. Closed-set
  framing preserves predictability: the model classifies; rubric authors
  still write every sentence shown to the user.
- Consequence: `FieldSpec` gains `framing_questions`; `Rubric` gains declared
  `framings` and `default_framing`; `Question` and `AssessmentResponse` expose
  the resolved framing for audit and stateless resubmission. The optional
  dashboard performs one framing-classification call after its first complete
  extraction and reuses that framing on subsequent remediation turns. MCP
  clients call `detect_prd_framing` with the first native assessment JSON or
  fallback extraction JSON, then resubmit its `framing` to
  `score_prd_extraction`, `assess_prd`, and
  `contextualize_next_question`. The rubric advances to
  `0.4.1-expert-baseline`. Evidence-anchored discovery of specific missing
  edge cases remains separate follow-up work because it changes question
  granularity rather than just phrasing.

## D-037: Discover Edge Cases Through Verified Anchors And A Fixed Taxonomy

- Status: accepted
- Decision: Add `discover_edge_case_question` for assessments whose
  `edge_cases_and_states` criterion still lacks `error_states`,
  `empty_or_edge_states`, or `transitional_or_degraded_states`. The connected
  model may select exactly one fact index from up to 15 source-verified
  candidates and one index from a fixed ten-entry edge-case taxonomy
  (interruption/recovery, connectivity loss, time or entitlement expiry,
  eligibility change, duplicate/retry, concurrent state change, partial
  completion, empty/exhausted state, app lifecycle, stale/conflicting state).
  Its only legal output is `{"fact": <int>, "edge_case": <int>}`. Python
  renders the question from the exact verified quote and rubric-owned taxonomy
  text. Invalid, mixed-zero, extra-keyed, or out-of-range output falls back to
  the normal field question. The discovery never changes a score; only a
  later user answer, submitted as `edge_cases_and_states` supplemental
  evidence, can receive credit.
- Reason: A field-level prompt such as "what happens while offline?" detects a
  category gap but does not review the document deeply enough to expose the
  concrete decision an author must make. For Micro Dramas, Forge can anchor to
  the verified requirement "Progress should also sync with the backend server
  at an interval of every 10/X seconds" and ask what happens when connectivity
  is lost and restored. This is materially more useful while preserving the
  closed-output-space safety boundary established by D-035 and D-036.
- Consequence: List-valued extracted fields now receive per-item evidence in
  `verify_run`; only list items independently found in normalized source text
  may become question anchors. Candidate selection limits repeated values from
  one field so broad metric lists cannot crowd out functional requirements.
  Discovery remains advisory because a closed-set selection can identify a
  plausible omission but cannot prove that no other document passage resolves
  it. The caller shows the question, records the user's answer against
  `edge_cases_and_states`, and lets normal evidence verification and scoring
  determine whether the field is satisfied.

## D-038: Score Edge Cases From A Versioned Coverage Ledger

- Status: accepted
- Decision: Replace "one discovered edge-case answer satisfies the broad
  field" with a versioned requirement-by-taxonomy coverage ledger. Verified
  functional requirement atoms are crossed with applicable entries from edge
  taxonomy `1.0` using deterministic keyword/rule mappings. The client model
  classifies every declared pair as `covered`, `missing`, `not_applicable`, or
  `unclear` and may cite only an enumerated verified evidence quote. Native MCP
  coverage uses three independent runs, modal status, and pessimistic tie
  resolution. Python rejects incomplete pair sets, duplicate pairs, unknown
  taxonomy entries, malformed statuses, and unsupported positive claims.
  `covered` and `not_applicable` count only when their evidence quote can be
  located in the current document or criterion-bound supplemental evidence.
- Reason: D-037 made questions concrete but still allowed one answer to make
  `transitional_or_degraded_states` present while unrelated requirements and
  failure modes remained unspecified. A ledger gives each decision a stable
  identity, supports a deterministic question queue, and provides an honest
  stopping claim: all applicable pairs in taxonomy `1.0` are covered or
  explicitly not applicable. It does not claim that every imaginable real-
  world edge case has been discovered.
- Consequence: `AssessmentResponse` carries `edge_case_coverage`; each
  taxonomy-led `Question` carries `requirement_quote`, `edge_case_id`, and
  `taxonomy_version`; and `SupplementalAnswer` may bind an answer to that
  exact cell. Resubmitting the ledger plus accumulated answers updates only
  matching cells before evidence verification, so coverage cannot drift
  between turns. The `edge_cases_and_states` verdict combines ledger coverage
  with the existing `supported_platforms` and `accessibility_approach`
  requirements: all three components are required for `PRESENT`. The dashboard
  builds the ledger automatically and reuses it; MCP clients call
  `assess_edge_case_coverage` and pass its ledger to later assessment calls.
  The rubric advances to `0.5.0-expert-baseline`. This changes scoring behavior
  when a coverage ledger is supplied and therefore requires organization data
  before thresholds or applicability mappings can be considered calibrated.

## D-039: Check The Sampling Capability Before Sending A Request

- Status: accepted
- Decision: Every `Resolve`-based sampling resolver (`_sample`, `_sample_batch`,
  `_sample_visual`, `_sample_context_choice`, `_sample_framing`,
  `_sample_edge_case_choice`, `_sample_edge_case_coverage`, and their per-run
  wrappers) now takes the injected `Context` and calls a shared
  `_require_sampling` guard before building or returning a `Sample` marker.
  If the connected client has not declared the `sampling` capability, this
  raises a plain `ValueError` naming the tool and, when one exists, the
  non-sampling fallback tool to use instead. `@_anticipated` turns that into a
  normal `ToolError` the same way it already handles a missing file or a
  stale batch plan.
- Reason: Without this guard, a client lacking `sampling` never reaches our
  code at all — the SDK's own `_require_capability` fires first and raises a
  bare `MCPError` (`MISSING_REQUIRED_CLIENT_CAPABILITY`, wire code `-32021`),
  surfaced to users verbatim as e.g. "MCP error -32021: Client did not declare
  the sampling capability required by resolver
  'forge.mcp.server:_sample_framing'". This is confirmed to happen in
  practice: a user reported it while calling `detect_prd_framing` on a client
  (OpenCode) already confirmed by D-038-era testing not to support sampling.
  For `assess_prd`/`assess_prd_batch` this only produced a cryptic error the
  agent had to interpret before self-correcting to the documented fallback;
  for `detect_prd_framing`, `discover_edge_case_question`,
  `assess_edge_case_coverage`, and `contextualize_next_question` — which have
  no fallback tool at all — it was a dead end with no actionable next step.
- Consequence: Every sampling tool now fails the same understandable way on
  every host, including hosts not yet tested (this directly addresses the
  user's "this could happen in Cursor as well"). The four advisory tools
  still have no non-sampling fallback; their error explicitly says so and
  tells the agent to continue with `score_prd_extraction`/`assess_prd` alone
  rather than blocking the whole assessment. Building real fallbacks for
  those four tools (mirroring `prepare_prd_assessment` +
  `score_prd_extraction`) remains open in `docs/ROADMAP.md`. Separately, this
  investigation surfaced that the installed MCP SDK marks the entire
  `sampling` capability `@deprecated` as of protocol revision 2026-07-28
  (SEP-2577); Forge has not yet investigated what SEP-2577 proposes in its
  place, and D-006/D-007's reliance on sampling should be revisited once that
  replacement is understood.

## D-040: Checkpoint Remediation And Extract Only Answer Deltas

- Status: implemented
- Supersedes: D-010 and D-030 only where they require recomputation after every
  answer, D-014's exclusively stateless transport, and D-020's consequence that
  every answer invalidates the full-document extraction plan. One question per
  user turn and criterion-bound evidence remain unchanged.
- Decision: Ask one field-sized question at a time while collecting exact user
  answers in a remediation session. Do not invoke a model or change the score
  merely to advance to the next queued question. Process pending answers at a
  bounded checkpoint: five answers by default, completion of the remaining
  fields in a failed gate, or an explicit user request. A checkpoint extracts
  only pending answer blocks against the affected criterion schemas and prior
  verified values, verifies their quotes, merges criterion-local patches into
  an immutable source/rubric-bound baseline, deterministically rescores, and
  rebuilds the queue. One answer may satisfy multiple fields of its criterion
  but cannot affect another criterion. Full exhaustive extraction is reserved
  for an initial assessment, a changed source or rubric, and final verification
  of a materialized revision.
- Reason: A real OpenCode fallback run generated an extraction prompt of roughly
  83,000 characters for the Micro Dramas PRD. Repeating the full document for
  every atomic question multiplies latency and input tokens while the source is
  unchanged. The evidence boundary needs criterion-local verification, not
  repeated ingestion of unrelated sections.
- Consequence: Add a domain `RemediationState`, deterministic internal question
  queue, pending/verified answer separation, checkpoint policy, criterion-delta
  extraction schema, merge validation, and separate initial/remediation/final
  token accounting. Prefer a small Forge-owned state machine and lightweight
  local session store over LangGraph; revisit a workflow framework only if
  durable branching, background execution, or multi-party approvals become
  concrete requirements. Full-document fragments must require fingerprints;
  omitting one must not bypass stale-plan protection.

## D-041: Preview Integrated Revisions And Verify A New Copy

- Status: implemented
- Supersedes: D-027 only where revision materialization is limited to appending
  a clarification section. Its explicit approval, provenance, and no-overwrite
  guarantees remain unchanged.
- Decision: After remediation, map verified answers to proposed insertions or
  replacements in existing PRD sections and show that revision plan to the user.
  Detect conflicts with current text and require an explicit resolution. Only
  after approval may Forge create a same-format editable copy; it never modifies
  the source or an existing output. The copy includes an audit appendix of
  accepted clarifications. Forge then runs one full assessment of the new copy
  without supplemental evidence and reports that artifact's readiness.
- Reason: Supplemental answers improve a conversational score but downstream
  teams need one durable, internally coherent PRD. Appending every decision at
  the end preserves provenance but leaves readers to reconcile sections and can
  retain contradictions. A new-copy preview keeps the user as author while the
  final reassessment verifies what will actually circulate.
- Consequence: Keep the current appendix-only mode as a low-risk option and add
  an integrated-revision mode. Generated placement or connective wording is a
  proposal, never scored evidence before approval and materialization. Revision
  generation runs once per approved batch, not after every question, and its
  model usage is reported separately.
