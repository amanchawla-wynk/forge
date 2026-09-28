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

## D-042: Forge Owns Review Identity And New Chats Resume Explicitly

- Status: implemented
- Decision: Persist review workflows in local SQLite under a cryptographically
  random Forge `review_session_id`. Bind each session to the exact source hash,
  rubric id/version, workspace fingerprint, and local user. Record client name,
  version, MCP transport session, and a host conversation id when available, but
  never use those vendor-specific values as the primary identity. Every mutation
  also requires an optimistic `session_version` and idempotent `operation_id`.
  New OpenCode, Cursor, Claude Code, or dashboard conversations discover reviews
  by exact source/workspace binding and must explicitly choose **Resume review**,
  **Start a new review**, or **Cancel**. Even one matching review is not resumed
  automatically. Cross-client resume requires confirmation and records a client
  binding change event. Missing or ambiguous identity is an error, never a cue
  to select the most recent session.
- Reason: MCP identifies a client application and may identify a transport
  session, but `tools/call` does not standardize the host's chat/conversation id.
  One MCP process can serve several chats, while one product review may
  intentionally move between clients. Binding workflow state directly to either
  side would cause accidental answer mixing or prevent legitimate resume.
- Consequence: Add a SQLite session/event repository, explicit workflow-state
  enum and transition guards, `find_prd_reviews`, `resume_prd_review`,
  `start_prd_review`, and `get_prd_review_status`. Every response exposes one
  machine-readable `next_action`; agents no longer infer the legal next tool from
  prose. The dashboard retains its review id in browser `sessionStorage`, but a
  new tab uses the same explicit discovery flow. For remote transport, session
  ownership must additionally bind to the authenticated subject and tenant; a
  session id alone is not authorization. If LangGraph is adopted later, its
  `thread_id` equals the Forge review id. GraphRAG remains outside workflow and
  scoring state.

## D-043: Harden Durable Review Integrity Before Expanding Scope

- Status: implemented
- Decision: Verify edge-case ledgers before session scoring; persist dashboard
  documents, revision plans, and artifact links; bind operation ids to request
  digests and reserve external inference; distinguish source-run agreement from
  single remediation deltas; provide agent fallbacks for advisory sampling; and
  enforce local resource, retention, path-redaction, and loopback safeguards.
- Reason: Durable identity is insufficient if unverified coverage can alter a
  score, process restart loses the source, retries duplicate paid work, one
  delta looks like repeated agreement, or local adapter details leak to the
  browser. These failures would undermine the evidence boundary and make later
  validation results uninterpretable.
- Consequence: Dashboard state is locally persistent and explicitly deletable;
  revision/final-assessment provenance is linked to the originating review;
  advisory features work without MCP sampling through prepare/apply tools; DOCX
  headers, footers, and body table order are covered; and organization-validity
  claims remain gated by the preregistered holdout protocol in
  `docs/VALIDATION_PROTOCOL.md`.

## D-044: Treat Cursor As A Non-Sampling Client

- Status: accepted
- Decision: Treat Cursor 3.22.7 as not supporting MCP sampling and direct its
  documented Forge workflow to `prepare_prd_assessment` and
  `score_prd_extraction`, rather than probing `assess_prd` first. Continue to
  retain the runtime capability guard because a future Cursor release may add
  and advertise sampling.
- Reason: A live Cursor 3.22.7 test produced Forge's proactive error that the
  MCP client had not declared the `sampling` capability. This is the same
  protocol condition already confirmed in OpenCode. Cursor's public MCP
  documentation describes connecting and invoking MCP tools but does not claim
  support for the distinct server-to-client `sampling/createMessage` flow.
- Consequence: Cursor and OpenCode use the agent-driven fallback by default.
  This changes where extraction inference is orchestrated, not Forge's evidence
  verification, deterministic scoring, or no-provider-key boundary. Native
  sampling remains available to clients that declare the capability.

## D-045: Make Evidence-Backed Deep Review The Primary Experience

- Status: accepted
- Supersedes: D-015 and the product experience only where the concise readiness
  narrative was the primary user-facing result. Deterministic scoring,
  evidence verification, advisory status, and one-question remediation remain
  unchanged.
- Decision: Forge's primary response answers: "What specifically prevents
  downstream teams from implementing this PRD correctly, where does the
  document conflict with itself, and what decisions must the author make?"
  Lead with prioritized, source-backed findings covering contradictions,
  ambiguities, precedence conflicts, non-testable requirements, stale or
  superseded statements, undefined fallbacks, and missing operational
  decisions. Each finding must cite verified source locations, explain the
  downstream implementation consequence, and state the author decision needed.
  The readiness band and criterion audit remain supporting deterministic
  evidence rather than the primary review narrative.
- Reason: The MicroDrama recommendations PRD contained implementability defects
  more consequential than its missing rubric fields: incompatible skip
  thresholds, an impossible interval, conflicting mood-picker state and
  frequency rules, inconsistent launch timelines, and unclear ranking
  precedence. The existing report reduced these to generic omissions because
  extraction retained only one value per field and the deterministic narrative
  was designed for concise remediation, not cross-section review. More model
  runs or conventional RAG would not repair that representation loss.
- Consequence: Add a multi-claim evidence ledger and a bounded, per-document
  requirement graph before consolidation. Add a quote-verified advisory
  consistency ledger and a deep-review output schema. Keep exhaustive batching;
  the graph may discover relationships but cannot decide which source text is
  eligible for evidence or assign numeric scores. Initially, deep-review
  findings remain outside the readiness band until representative human review
  establishes their precision, recall, priority usefulness, and acceptable
  false-positive rate. Evaluate LangGraph and LangChain only as replaceable
  orchestration adapters, and compare any property-graph dependency against a
  smaller Forge-owned static graph before adoption.

## D-046: Classify Statement Conflicts Through A Verified Closed-Set Ledger

- Status: implemented
- Decision: Semantic conflicts that Python cannot prove are classified through
  the same closed-output boundary as D-035, D-036, and D-038. Forge
  deterministically enumerates candidate statement pairs from named subjects it
  already parses (event identifiers, milestone aliases, skip classifications),
  bounded per subject and in total. The connected model may return only one
  enumerated relation index per candidate from a fixed taxonomy:
  `precedence_conflict`, `scoped_contradiction`, `superseded_requirement`,
  `compatible`, or unclear. Three independent runs are consolidated by strict
  majority; any tie or plurality resolves to `unclear`. Python re-locates both
  quotes in the normalized document before publication and renders every
  user-facing word from a fixed template plus verified quotes. Findings are
  advisory, marked `confidence: classified`, and cannot change verdicts,
  weights, gates, or bands.
- Reason: The MicroDrama PRD's most expensive defects included rules that were
  individually well-formed but jointly unimplementable, such as two mood-picker
  trigger rules and ranking orders that differ between sections. Deterministic
  numeric checks cannot decide whether two differently worded rules govern the
  same situation, and free-text model review would reintroduce exactly the
  unverifiable critique D-025 rejected.
- Consequence: Adds `forge.score.consistency` with versioned taxonomy `1.0`,
  a `consistency` kind on `prepare_prd_advisory`/`apply_prd_advisory`, and an
  optional `consistency_ledger` input to `score_prd_extraction`. Conservative
  resolution means Forge will miss real conflicts rather than invent them;
  recall improvements require the human-labelled golden case before any
  threshold or scoring effect is considered.

## D-047: Validate Deep Review With Blinded Finding Labels

- Status: implemented
- Decision: Measure D-045 deep-review findings in a separate offline developer
  workflow rather than reusing criterion calibration labels. Reviewers identify
  defects from the source document without seeing Forge's findings and attach
  exact source fragments. At least two distinct reviewers are required for an
  internal case to enter headline metrics. Strict-majority defects define the
  expected set; ties and minority findings remain contested. Python matches
  predictions one-to-one by normalized quote containment and, when supplied,
  finding kind. Public and synthetic cases remain robustness diagnostics.
  Preregistered thresholds fail closed when a required metric is undefined.
- Reason: Deep-review precision and recall cannot be inferred from readiness
  band agreement, synthetic regression cases, or Forge's own quote verifier.
  Showing predictions before labelling would anchor reviewers, while treating a
  single reviewer as truth or averaging away false positives would overstate
  reliability. False accusations of contradiction are especially damaging to
  author trust and therefore need an explicit per-case measure.
- Consequence: Add `forge.review_eval` and the `forge-review-eval` CLI for
  prediction cases, blinded label templates, label merging, holdout evaluation,
  and threshold decisions. Reports include precision, recall, blocker recall,
  false positives per case, human quote alignment, evidence completeness,
  duplicate rate, per-kind metrics, contested expectations, and inter-reviewer
  agreement. The harness does not validate the feature by itself; representative
  human-labelled internal cases are still required. Priority agreement and
  actionability remain a separate post-prediction study so the discovery labels
  stay blind.

## D-048: Use Public-Guidance AI Panels Only As Proxy Diagnostics

- Status: implemented
- Decision: When independent reviewers are unavailable, use separate AI agents
  grounded in distinct public first-party guidance families to propose synthetic
  proxy labels, hard negatives, disagreements, and generic rubric hypotheses.
  Store the result in a closed artifact type that is permanently marked
  `synthetic_ai_proxy`, `external_proxy_diagnostic`, calibration-ineligible,
  headline-ineligible, advisory, and no-score-effect. Proxy agreement is not
  human inter-reviewer agreement. It may support field wording and regression
  coverage, but never weights, gates, bands, severity calibration, legal claims,
  or organization validation.
- Reason: The MicroDrama recommendations PRD provides useful, source-verifiable
  transfer cases while human reviewers are unavailable, and public Google,
  Microsoft, LinkedIn, Atlassian, GitLab, GOV.UK, and related guidance supplies
  a broader content basis than one template. However, agents share model and
  prompt biases, cannot represent the cited companies, and cannot supply an
  independent readiness label. Treating their agreement as calibration would
  violate D-024 and D-047.
- Consequence: Add `forge.proxy_labels` and a 29-label MicroDrama proxy artifact
  with 75 verified source spans, hard negatives, compatible cases, and preserved
  disagreement. Advance the bundled rubric to `0.6.0-expert-baseline` by adding
  `functional_requirements.decision_rules_and_precedence`, adding
  `acceptance_criteria.requirement_coverage`, and refining
  `dependencies.dependency_readiness`. Every existing criterion weight, gate,
  band threshold, and verdict credit remains unchanged. The new fields are
  content-validity hypotheses until representative blinded human review exists.

## D-049: Prove Exact-Key Structured Contract Conflicts In Python

- Status: implemented
- Decision: Extend the deterministic deep-review source scan to preserve
  structured snippets that PDF table flattening separates across lines. Publish
  an enum-domain finding only when one exact classification label maps to
  incompatible tier values or an assigned value falls outside an explicitly
  declared matching domain. Publish a schema-type finding only when one exact
  machine field name has incompatible explicit array, table, or inline type
  declarations. Partition declarations by explicit product, variant, phase,
  surface, or fallback scope and abstain across different scopes. Continue to
  render consequence and required-decision text from fixed Python templates.
- Reason: Proxy labels `PXY-MD-004` and `PXY-MD-011` are mechanically provable
  from the MicroDrama source: hard skip maps to tiers 3 and 1 while the stored
  tier domain is 0-2, and `genre_tags[]` conflicts with a scalar `string`
  declaration. Sending these exact contracts to a semantic classifier would
  add model variance without adding judgment. At the same time, similarly named
  fields or enum values can legitimately differ by product or variant, so an
  exact scope boundary is required before comparison.
- Consequence: Add deterministic `enum_domain_conflict` and
  `schema_type_conflict` finding kinds, structured source-span extraction, fixed
  evidence/consequence/decision projections, and positive plus hard-negative
  tests. Findings remain advisory and cannot change rubric verdicts, weights,
  gates, or bands. State lifetime, activation, dependency-status, precedence,
  and implicit scope conflicts still require closed-set classification.

## D-050: Complete The Deterministic Core, Extend The Taxonomy, And Defer Both Frameworks

- Status: implemented
- Decision: (1) Timeline analysis compares only commensurable values. Two exact
  dates may conflict, and two relative post-launch windows conflict only when
  they are disjoint. Overlapping windows and exact-versus-relative comparisons
  abstain. (2) Every merged claim gains a `ClaimInterpretation` recording
  subject, scope, phase, and modality keys with `provenance: deterministic`;
  it is an explicit-language projection, not a model's reading of intent.
  (3) Add same-scope `opposite_polarity`, `duplicate_rank`, and
  `precedence_cycle` checks over exact machine identifiers. (4) Advance the
  consistency taxonomy to `1.1` with `implied_exception` and `ambiguous_scope`.
  (5) After executable spikes, do not adopt LangGraph or a property-graph
  index now.
- Reason: The prior timeline rule reported `2-4 weeks` against `2-3 weeks` as a
  conflict, contradicting proxy hard negative `PXY-MD-HN-010`, which records
  overlap as ambiguity rather than contradiction. Polarity, duplicate ranks, and
  cycles are mechanically decidable and should not consume model classification.
  Forcing an unbounded exception or an unreconcilable scope into
  `scoped_contradiction` or `compatible` either overstates a conflict or hides a
  real decision the author must make. The measured spikes showed LangGraph
  provides working SQLite checkpoints, interrupts, and replay but no native
  source/rubric/workspace binding or operation-digest idempotency, and that a
  property-graph store can hold the bounded graph without improving exact
  evidence verification.
- Evidence: `spikes/graph_framework_comparison.py`, run 2026-09-25 with
  `langgraph` 1.0.8 and `llama-index-core` 0.14.6. LangGraph exposed
  `__interrupt__`, resumed from `Command(resume=...)`, wrote 3 checkpoints, and
  mapped `thread_id` to a Forge review id. The property graph stored 100 nodes
  and 99 relations with no duplicates on re-upsert, but `get_triplets()` returns
  an empty list unless a filter is supplied, so an unfiltered read is not a
  graph dump. Forge's static graph built the same shape with no dependency.
- Consequence: Deep review adds five deterministic finding kinds and two
  classified kinds, all advisory and still outside scoring. Neither framework
  enters production dependencies; the spike stays runnable through `uv run
  --with` so the comparison can be repeated rather than trusted from prose.
  Revisit LangGraph only for concrete durable branching, background execution,
  or multi-party approval requirements.

## D-051: Measure Deep-Review Recall Before Adding More Detectors

- Status: implemented
- Decision: Add `forge.proxy_diagnostics` and `forge-proxy-diagnostics`, which
  run the deterministic deep review against a synthetic proxy artifact and
  report finding recall, blocker recall, candidate-or-finding coverage,
  findings per kind, unmatched findings, and hard-negative violations. The
  report is permanently marked `calibration_eligible: false`. Broaden candidate
  generation with category pairing (`lifetime`, `status`, `ranking`) that
  requires the same trigger category plus at least two shared content words,
  after removing words common to a quarter of that category's statements.
  Reserve candidate budget for category pairs, deduplicate pairs by normalized
  quote text, and skip pairs a deterministic finding already cites together.
- Reason: Every detector so far was added on judgment. Running the measurement
  showed the honest position: finding recall against the 29-label proxy ledger
  is 3/19 (0.158) and blocker recall is 3/9 (0.333), with 0 hard-negative
  violations. Without this number, further detectors would be justified by
  intuition, and the conservative bias could be mistaken for good coverage.
- Evidence: `forge-proxy-diagnostics fixtures/proxy/microdrama-recommendations.proxy-panel.v1.json`
  on 2026-09-25: 5 findings, 29 candidates, recall 0.158, blocker recall 0.333,
  coverage 0.211, hard-negative violations 0. Matched labels are `PXY-MD-003`,
  `PXY-MD-004`, and `PXY-MD-011`. Deduplication removed repeated identical
  `feed_position` and `genre_tags` pairs that had consumed classification budget.
- Consequence: Low recall is now a recorded, reproducible fact rather than an
  assumption, and precision-style counts here are diagnostic only because the
  labels are synthetic (D-048). The measurement also isolated the next
  blocker: PDF line splitting fragments one statement into several claims, so
  the p16 mood rule survives only as `"last 30 days window (top 5"` and can
  never pair with the p5 session rule. Claim granularity for multi-line source
  units must be fixed before further semantic detectors are worth adding.

## D-052: Harden The Existing Review Contract Before The Representation Migration

- Status: implemented
- Decision: Complete a bounded correctness phase before introducing source
  snapshots, criterion-evaluation ledgers, retrieval, or generated contextual
  questions. Enforce exact rubric schemas for direct and fragmented extraction;
  persist verifier-produced list-item evidence while excluding it from
  model-facing schemas; stamp assessment, report, deep review, and questions
  with one checkpointed `evaluation_revision`; rebuild deterministic deep review
  after answer deltas; represent every uncovered edge-case ledger cell as a real
  queue item; use repeated pessimistic coverage consolidation in the dashboard;
  and bind MCP revision preview/materialization to durable session identity,
  optimistic versioning, idempotent operations, verified answers, and legal
  workflow transitions.
- Reason: The architecture audit found that correctness defects in current state
  could invalidate later parser, evaluation, and question-generation work. A
  sparse direct extraction could bypass the fragment contract; restart discarded
  per-item provenance; post-checkpoint outputs mixed old deep review with a new
  score; one synthetic edge field could strand uncovered cells; dashboard and
  MCP coverage had different confidence bases; and stateless MCP revision tools
  could write answers not owned by the authoritative review. Adding richer
  semantic representations on those foundations would preserve hidden drift.
- Consequence: Direct extraction is now a strict schema contract, including for
  fixtures and offline diagnostics. Review-session schema version `2` and
  `evaluation_revision` are persisted in SQLite with migration defaults.
  Dashboard coverage costs the configured repeated-run count and fails visibly
  on malformed classification. MCP revision tool signatures are intentionally
  breaking pre-release changes: callers provide review/session/operation
  identity, while Forge derives source and verified answers. The next migration
  phase may add immutable source snapshots without changing these guarantees.
  Revision publication is recoverable through staged artifact metadata, the
  exact preview plan is persisted in the review, and generated artifact path and
  hash are retained until `complete_prd_review` performs a full assessment with
  no supplemental evidence and advances the session to `COMPLETE`. Durable
  supplemental-answer ids preserve evidence block identity across checkpoints;
  version-1 pending sessions are repaired on load without relabelling their
  schema version.

## D-053: Bind Reviews And Extractions To Immutable Parser-Versioned Snapshots

- Status: implemented
- Decision: Separate local-file acquisition from parsing and represent one parse
  as an immutable `DocumentSnapshot`. Its content identity combines exact source
  SHA-256, source type, an explicit parser fingerprint, normalized-schema
  version, and normalized-content hash; origin path and display metadata do not
  change that identity. Persist complete snapshots in the review SQLite database,
  reload them for checkpoints without reparsing, and require exact snapshot,
  parser, normalized, and rubric compatibility for resume. Keep pre-snapshot
  sessions visible but audit-only. Bind extraction-plan and remediation-baseline
  fingerprints to the same identities. Use one `PreparedAssessmentInput` within
  each service, dashboard, or MCP advisory operation. Add a developer-only
  parser benchmark that can load Docling and PyMuPDF4LLM through `uv --with`, but
  do not add either as a production dependency or choose a replacement parser.
- Reason: Raw file hashes alone cannot prove that two extractions saw the same
  evidence when parser behavior or normalization changes. Reopening the source at
  every advisory and checkpoint also permits intra-review drift and wastes parse
  work. Content identity must remain stable when identical bytes are reached by
  different paths, while each session still needs correct origin metadata.
  Candidate parser adoption requires measured text, structure, provenance,
  determinism, and runtime behavior on representative documents rather than a
  library-feature comparison.
- Consequence: New review creation transactionally stores the exact source bytes,
  normalized blocks, and canonical nodes. Restarted checkpoints use that stored
  baseline and fail closed when it is missing or incompatible. Equal content at
  different paths shares one snapshot id and stored content row, but hydration
  rebinds origin metadata to the owning session. Version-2 plan fingerprints
  reject fragments prepared with another parser, normalized result, rubric,
  product context, or batch plan. The legacy parser is now explicitly identified
  as `forge.legacy-document-parser/1.0`. `spikes/parser_benchmark.py` is runnable,
  and was run against the two DOCX and one PDF samples in `sampleDoc/` using
  Docling 2.130.0 and PyMuPDF4LLM 1.28.2. Docling retained 98.26-99.41% of the
  current parser's token multiset while recovering 12-46 headings and 2-29
  tables; its warm conversions took 0.417-63.958 seconds versus Forge's
  0.029-0.101 seconds. On the PDF, PyMuPDF4LLM retained 98.34% of baseline tokens,
  rendered 21 headings and 152 table rows, and took 6.321-9.601 seconds. All
  repeated outputs were deterministic. These measurements justify a bounded
  Docling adapter prototype but not production adoption: candidate-only text,
  table order, quote alignment, OCR, and provenance still require manual review.
  Full results are in `reports/parser benchmark 2026-09-26.md`.

## D-054: Introduce Criterion Evaluation In Score-Neutral Shadow Mode

- Status: implemented; quality validation pending
- Decision: Add strict criterion-evaluation submissions and Python-verified
  artifacts beside current field extraction. Represent multiple claims and
  evidence sets, explicit support/counterevidence relations, gaps, ambiguities,
  contradictions, applicability, exact evidence ids, exhaustive batch coverage,
  and repeated-run confidence. Derive the initial version-1.0 assertion contract
  from each versioned rubric field and its remediation answer contract, while
  allowing a rubric to declare an explicit contract. Expose agent-driven
  `prepare_prd_evaluation` and `apply_prd_evaluation` tools. Keep native semantic
  evaluations out of scoring. Project verified legacy extraction into the new
  representation with a reversible adapter, and persist those per-run artifacts
  transactionally when a durable review starts.
- Reason: Selecting one satisfied field witness discards compatible support,
  counterevidence, and conflicting spans before a criterion can be reviewed for
  coherence. Asking a model for numeric quality would weaken Forge's trust
  boundary, while allowing model-authored evidence ids or batch-level absence
  would weaken provenance and exhaustiveness. A shadow path permits measurement
  of the richer representation without changing established readiness behavior.
- Consequence: The bundled rubric advances to `0.7.0-evaluation-shadow`; its
  weights, gates, bands, verdict credits, and required fields are unchanged.
  Python mints every authoritative identifier and rejects stale/incomplete batch
  plans. Strict-majority repeated-run consolidation resolves ties to `unclear`.
  Only `legacy_field_adapter` evaluations can round-trip into scoring, with
  regression tests proving exact assessment parity. Native evaluations are
  auditable output only. Review state schema version `3` adds a plan fingerprint
  and reloads immutable artifacts from `criterion_evaluation_artifacts` plus
  `review_evaluation_artifacts`; pre-v3 sessions continue without synthesized
  artifacts. Phase 2 does not pass its quality exit gate until shadow runs improve
  human/proxy evidence alignment without new hard-negative violations.

## D-055: Hold Phase 3 Until Assertion-Level Evaluation Agreement Improves

- Status: implemented diagnostic; Phase 3 blocked
- Decision: Add `forge-evaluation-diagnostics` and retain three independent
  native evaluation runs for every authored corpus criterion plus ignored runs
  for the two internal DOCX samples. Report quote verification, duplicate
  references, status distributions, abstention, full run agreement, optional
  call metadata, and a symmetric native/legacy status matrix. Treat neither the
  authored corpus nor legacy extraction as semantic truth. Do not make native
  gaps user-facing or start generated question plans while internal full status
  agreement remains at the measured 56.67%. The next slice must consolidate
  assertion-level support/gap/conflict/ambiguity states by strict majority before
  deriving criterion status.
- Reason: The first shadow study verified all 541 submitted citations and found
  no duplicate references, so provenance is behaving correctly. The authored
  corpus reached 88% full run agreement, 5.33% abstention, and 81.33%
  native/legacy agreement; native evaluation also correctly downgraded many
  fluent-but-hollow gaming fields and unanimously rejected placeholders.
  However, the internal documents reached only 17/30 full-agreement criteria.
  Micro Dramas had nine disputed criteria and 40% full agreement. Whole-criterion
  status voting conflates several independently variable assertion judgments and
  is not stable enough to choose a user-facing gap.
- Consequence: `fixtures/evaluation/corpus.run{1,2,3}.json` become synthetic,
  calibration-ineligible regression inputs. `spikes/run_corpus_evaluation_diagnostics.py`
  and `spikes/run_internal_evaluation_diagnostics.py` reproduce the measurements;
  internal runs remain gitignored. Diagnostics have no thresholds and no score
  effect. Full results and the gate rationale are recorded in
  `reports/criterion evaluation shadow diagnostics 2026-09-26.md`. Phase 3
  remains explicitly blocked pending assertion-level reconciliation and blinded
  review of disputed internal criteria and proxy hard negatives.

## D-056: Reconcile Assertions Before Deriving Shadow Criterion Status

- Status: implemented; Phase 3 remains blocked
- Decision: Derive a per-run state for each rubric assertion (`supported`,
  `gap`, `contradictory`, `ambiguous`, or `unclear`), consolidate that state by
  strict majority across independent runs, and only then derive the criterion's
  shadow status. Retain minority evidence and issue records for audit. Report
  assertion-level full agreement separately from raw criterion-status agreement
  so an implementation change cannot rewrite the D-055 baseline metric.
- Reason: Support and conflict are asserted at the assertion/evidence-set level,
  while the first Phase 2 implementation voted on a whole criterion. One
  minority contradiction could remain attached to a majority-supported
  criterion, and several independently variable fields were compressed into one
  unstable vote. Assertion reconciliation is the smallest conservative unit and
  preserves abstention without discarding source spans.
- Consequence: Re-running the unchanged three-agent study yields 243/255
  assertion outcomes in full agreement (95.29%) on the authored corpus and
  76/102 (74.51%) on the two internal PRDs. Raw criterion-status agreement
  remains 88% and 56.67%, respectively. Consolidated internal abstention falls
  from 20% to 16.67%. These are diagnostic improvements, not a quality claim;
  74.51% internal assertion agreement plus missing human adjudication is still
  insufficient for native gaps to drive Phase 3 questions.

## D-057: Normalize Semantic Identity And Blind Internal Adjudication

- Status: implementation complete; waiting for reviewers
- Decision: Exclude model-authored claim values and alternative wording from
  support-set and ambiguity identity. Bind semantic records to the criterion,
  assertion ids, verified evidence ids, evidence role, relation, and issue kind;
  retain the model wording only as audit content. Add prediction-free reviewer
  sheets covering every assertion in both internal documents, plus a strict
  agreement/consensus evaluator. Do not preselect only disputed criteria, expose
  Forge predictions, or resolve two-reviewer disagreement.
- Reason: Independent models can express the same supported fact or ambiguity
  with different paraphrases. Including those strings in identity prevents
  deterministic deduplication even when citations and assertion semantics are
  identical. Human review is the remaining Phase 3 gate, but showing reviewers
  predictions or only Forge-disputed rows would anchor the labels and overstate
  agreement.
- Consequence: Equivalent support and ambiguity observations can merge without
  deleting their claims or alternatives. Generated sheets live under ignored
  `sampleDoc/.forge/evaluation-reviewer-{1,2}.json`; they include all assertions,
  blank labels, exact-quote fields, and no scoring configuration or predictions.
  `spikes/evaluate_evaluation_reviewer_sheets.py` reports no result until both
  reviewers label an assertion, keeps disagreement contested, and publishes
  consensus only with strict majority. Phase 3 remains blocked on completion of
  those independent sheets.

## D-058: Use Isolated AI Proxy Consensus To Open Phase 3 In Shadow Only

- Status: implemented diagnostic; Phase 3 shadow prototype allowed
- Decision: When human reviewers are unavailable, use three isolated connected
  agents as explicitly synthetic proxy reviewers. Each agent reads only source
  documents and its own prediction-free sheet; it cannot read native shadow
  runs, legacy assessments, reports, or peer labels. Consolidate assertion labels
  by strict majority, keep every disagreement contested, and compare consensus
  with native assertion outcomes symmetrically. Permit Phase 3 implementation
  only in shadow mode: a generated question may target a strict-majority native
  assertion outcome, must use verified evidence ids, must pass bounded output
  validation, and must have a deterministic rubric-owned fallback. It remains
  advisory and score-neutral.
- Reason: The user has no available human reviewers, but runtime development does
  not require a human-labelled calibration set. Three proxy reviewers completed
  all 102 internal assertions with 79 unanimous labels (77.45%), strict-majority
  consensus for 100, and two unresolved three-way splits. Native evaluation
  matched 81/100 proxy consensus labels. Inspection of the most expensive
  apparent mismatch found real conflicting source spans but a taxonomy boundary:
  proxies credited the presence of discrete requirements and attached the
  conflict to precedence, while native evaluation attached conflict to both.
  This supports a guarded question-generation experiment, not a quality claim.
- Consequence: AI proxy sheets and comparison outputs remain gitignored,
  `synthetic_ai_proxy`, calibration-ineligible, and no-score-effect. Phase 3 may
  now be built behind the shadow boundary, but it cannot replace current
  rubric-authored questions by default until bounded-question diagnostics and
  independent human validation pass. D-057's wait for human reviewers remains a
  blocker for calibration claims, not for this explicitly provisional runtime
  experiment.

## D-059: Start Phase 3 With A Lexically Bounded Shadow Question Slice

- Status: implemented in shadow; live remediation unchanged
- Decision: Derive at most one shadow question target from verified native
  criterion evaluations. Eligibility requires exhaustive coverage, at least
  three runs, strict-majority agreement, an outcome of `gap`, `ambiguous`, or
  `contradictory`, and verified issue identities. Rank targets deterministically
  using the existing gate/weight/consumer ordering, then issue status and rubric
  assertion order. Let the host model return only the plan id, one allowed issue
  id, and one question. Accept the wording only when it is one bounded question,
  every substantive token comes from the assertion, answer contract, selected
  verified evidence, or a small question-language allowlist, and every quoted
  phrase occurs exactly in verified evidence. Otherwise use the assertion's
  rubric-owned answer contract.
- Reason: Free question generation would reintroduce unsupported claims at the
  point closest to the user. A lexical closed-world check is deliberately
  conservative and measurable: false rejections safely increase fallback use,
  while source-specific terms and exact quotations remain available. Requiring
  the apply MCP tool to re-verify the original exhaustive evaluation batch avoids
  trusting a caller-supplied question plan as evidence authority.
- Consequence: `apply_prd_evaluation` may now include a bounded
  `question_generation` prompt, and `apply_prd_question_generation` returns a
  stable shadow artifact with `score_effect: none`. This artifact does not enter
  `Question`, remediation state, user answer binding, dashboard behavior, or
  scoring. Relevance, answerability, fallback, duplication, and unsupported-text
  diagnostics must pass before proposing a live-path migration.

## D-060: Keep Phase 3 Shadowed After Question-Quality Diagnostics Fail

- Status: implemented diagnostic; live integration blocked
- Decision: Measure every eligible D-059 target with three independent bounded
  generation runs, then submit every unique rendered candidate to three isolated
  prediction-free synthetic proxy reviewers. Keep generated questions out of
  live remediation because the first frozen internal study fails the
  smallest-scope and unsupported-assumption gates. Correct the representation at
  issue level before changing prompts or relaxing validation: retain a bounded
  missing-decision description, deduplicate shared issue ids, suppress questions
  whose antecedent is unresolved, and use verified-evidence resolution templates
  for ambiguities and contradictions.
- Reason: Across 198 completions, production validation allowed no unsupported
  text to reach output, fallback was only 0-4.55% per run, and 63/66 targets were
  wording-stable. Mechanical safety therefore passed. Quality did not: proxy
  consensus found only 29/71 candidates to be the smallest single-decision
  question and found unsupported assumptions in 13/71. One gap id often spans
  several assertions, later metric fields presuppose a missing primary metric,
  and contradiction fallbacks can ask for content that already exists. Prompt
  tuning cannot restore detail the evaluation record does not retain.
- Consequence: `forge.questions.diagnostics` and `forge.questions.labels` remain
  offline, calibration-ineligible boundaries. The ignored internal artifacts and
  `reports/question generation shadow diagnostics 2026-09-28.md` freeze the
  baseline. `Question`, remediation/session state, scoring, and dashboard output
  remain unchanged. Human validation is still required after the engineering
  gate eventually passes.

## D-061: Atomize Shadow Assertions Before Further Question Tuning

- Status: corrective experiment implemented; live integration remains blocked
- Decision: Retain bounded `missing_decision` descriptions on verified gap
  records without including wording in semantic identity. Group multi-run issue
  variants into one outcome plan, deduplicate shared issue ids across sibling
  assertions, expose at most the first unresolved gap per criterion, and use
  verified-evidence templates for ambiguity and contradiction fallback. Do not
  continue tuning free question wording after the enriched rerun. The next
  representation change must split composite shadow assertions into atomic
  resolution contracts with explicit prerequisite edges. Several atomic shadow
  assertions may map to one legacy field; scoring remains unchanged.
- Reason: Three new isolated evaluation runs produced 90 verified criterion
  artifacts and bounded detail for 98 gap variants. The planner reduced active
  targets from 66 to 28 and improved synthetic proxy relevance to 44/46 and
  answerability to 46/46. It did not solve question scope: only 15/46 candidates
  were single-decision questions, 8/46 retained unsupported assumptions, exact
  wording stability was 14/28, and 39-46% of completions fell back. Composite
  assertions such as dependency owner/readiness/fallback or
  availability/latency/capacity/recovery cannot be made atomic by phrasing alone.
- Consequence: Phase 3 remains shadow-only. The v2 internal evaluation and
  question artifacts remain ignored, synthetic, calibration-ineligible, and
  score-neutral. Rubric evaluation schema work may add explicit atomic assertions
  and dependencies, but it cannot change legacy fields, verdicts, weights, gates,
  bands, or live remediation until the frozen diagnostics and human review pass.

## D-062: Introduce Atomic Evaluation Contracts Without Changing Scoring

- Status: first atomic vertical slice implemented; live integration blocked
- Decision: Advance the bundled rubric to
  `0.8.0-atomic-evaluation-shadow` and evaluation contract `1.1`. Each shadow
  assertion may declare a bounded resolution contract and prerequisite assertion
  ids. Validate references and reject duplicate edges, self-dependencies, and
  cycles. Derive and consolidate native outcomes over evaluation assertions, not
  scoring fields. Allow several atomic assertions to map to one legacy field.
  Fan a verified legacy field witness into all mapped assertions only inside the
  reversible legacy adapter; scoring continues to consume the original field
  extraction. Implement dependency readiness as the first vertical slice:
  dependency owner, readiness proof, freshness/availability expectation, and
  stale/unavailable fallback all require the dependency itself to be named.
- Reason: D-061 showed that question wording cannot atomize a contract combining
  owner, proof, availability, impact, and fallback. The dependency criterion is
  a bounded representative slice that exercises one-to-many field mapping and a
  prerequisite DAG while leaving deterministic scoring untouched.
- Consequence: Existing `0.7.0-evaluation-shadow` diagnostic submissions contain
  the removed composite assertion id and remain historical artifacts; Forge does
  not silently reinterpret them as atomic judgments. Fresh evaluation runs under
  the new rubric fingerprint are required. Other composite contracts still need
  migration before D-060 is rerun, and generated questions remain shadow-only.

## D-063: Atomize Operational Readiness With Explicit Applicability Scope

- Status: implemented in shadow; scoring unchanged
- Decision: Convert `operational_readiness` to evaluation contract `1.1` without
  changing its three legacy scoring fields. Require one
  `service_expectation_scope` assertion that identifies which production
  expectation dimensions apply; represent availability, latency, capacity,
  data-integrity, and recovery objectives as optional atoms gated by that scope.
  Split the owner field into monitoring, support, and incident-response owners.
  Split recovery into a diagnostic method and recovery procedure, with recovery
  and any optional degraded-mode/backup/restore contingency gated by diagnosis.
- Reason: Treating every possible service-level dimension as universally required
  would manufacture gaps, while leaving availability, latency, capacity,
  integrity, recovery, ownership, diagnosis, and restoration in three composite
  assertions reproduces the D-061 scope failure. A required applicability atom
  lets the document select relevant dimensions before Forge asks for their
  values.
- Consequence: Native operational evaluation can now identify one unresolved
  production decision at a time. The reversible legacy adapter maps each original
  field witness to its shadow atoms and round-trips the untouched extraction, so
  verdicts, weights, gates, bands, and live remediation remain unchanged. Fresh
  0.8 evaluation runs are still deferred until the remaining priority composites
  are migrated.

## D-064: Atomize Rollout Decisions And Gate Promotion On Observation

- Status: implemented in shadow; scoring unchanged
- Decision: Convert `rollout` to evaluation contract `1.1` without changing its
  five legacy scoring fields. Make the rollout mechanism the prerequisite for
  entry, observation, pause, stop, and rollback-trigger decisions. Require both
  entry criteria and an observation window before promotion criteria become
  question-eligible. Require a rollback trigger before asking for the executable
  rollback procedure. Split rollout ownership into decision owner,
  pause/stop authority, and rollback execution owner. Use a required
  communication-impact scope before optional customer, support,
  documentation/migration, or go-to-market actions.
- Reason: The prior fields combined opposing thresholds, timing, authority, and
  execution into broad questions. Those decisions are independently answerable,
  but their order matters: promotion has no meaning before initial exposure and
  observation, and rollback procedure should resolve a named trigger. Audience
  actions are conditional, so making every channel universally required would
  manufacture gaps.
- Consequence: Native rollout evaluation can expose one ordered decision at a
  time. The legacy adapter still round-trips the original field extraction, so
  rollout verdicts, weight, gates, bands, and live remediation do not change.
  Fresh 0.8 diagnostic runs remain deferred until instrumentation and requirement
  coverage complete the priority atomic slices.

## D-065: Atomize Instrumentation Without Cross-Criterion Dependencies

- Status: implemented in shadow; scoring unchanged
- Decision: Convert `instrumentation` to evaluation contract `1.1` without
  changing its three legacy scoring fields. Split event declarations from
  optional event properties. Add a local metric-definition reference and require
  both that reference and declared events before the event-to-metric formula is
  question-eligible; optional filters or dimensions follow the formula. Require
  an operational-signal scope, one named failure-detection signal, and its
  diagnostic use, with additional log, dashboard, alert, monitoring, and support
  channels represented as optional scoped atoms.
- Reason: Prerequisite edges are deliberately criterion-local, so directly
  coupling instrumentation to `success_metrics` would make rubric contracts and
  consolidation cross-criterion state machines. A local metric reference keeps
  the dependency graph bounded while still preventing formula questions before
  events and the intended metric are named. Optional channel atoms avoid
  requiring every observability mechanism for every product.
- Consequence: Native instrumentation evaluation can distinguish missing events,
  properties, metric linkage, detection, and diagnosis. The legacy adapter still
  preserves list evidence and objective operational-signal constraints while
  round-tripping the original extraction with exact score parity. Live scoring
  and remediation remain unchanged.

## D-066: Keep Dynamic Requirements Inside Atomic Coverage Contracts

- Status: implemented in shadow; acceptance gate and scoring unchanged
- Decision: Convert `acceptance_criteria` to evaluation contract `1.1` without
  changing its three legacy scoring fields or gate. Split the core into
  completion outcome, observable pass condition, and observable fail condition.
  Use a required failure/boundary scope before optional failure, invalid-input,
  permission, or boundary-value criteria. Represent requirement coverage with a
  launch-critical requirement set, optional decision-rule boundary set,
  requirement-to-case mapping, optional boundary-to-case mapping, and coverage
  completeness. Gate requirement mapping on the requirement set plus pass/fail
  conditions, and gate completeness on that mapping.
- Reason: Requirement identities are document data and cannot safely become
  dynamic rubric assertion ids without destabilizing contracts, persistence, and
  consolidation. Bounded mapping assertions retain atomic resolution while
  allowing one document to contain any number of requirements. Applicability
  scope avoids requiring every failure category for every product.
- Consequence: Native acceptance evaluation can ask for one missing coverage
  decision at a time. The legacy adapter round-trips the original extraction, and
  the `caps_at_ready_with_gaps` gate behaves exactly as before. The four priority
  D-061 composite slices are now migrated, so fresh 0.8 evaluation and D-060
  question diagnostics are the next gate before further rubric atomization.

## D-067: Deterministic Atomic Questions Pass Safety But Fail The Semantic Gate

- Status: measured; live integration remains blocked
- Decision: Make deterministic rubric/evidence rendering the primary Phase 3
  diagnostic mode and predeclare the D-060 engineering thresholds before proxy
  review. Preserve model-authored wording as optional shadow comparison only.
  Keep live remediation unchanged because the fresh rubric-0.8 run fails every
  semantic threshold despite passing every mechanical threshold.
- Reason: Three fresh isolated evaluation runs produced 90 verified artifacts and
  29 currently eligible deterministic questions. Rendering was 100% stable, with
  zero unsupported output and zero within-document duplicates. Proxy review
  measured 99.14% consensus coverage, 82.76% relevance, 86.21% answerability,
  58.62% smallest scope, and 82.76% no-unsupported-assumption, below the
  predeclared 100%/90%/90%/80%/95% gates. Remaining failures come from unatomized
  lower-priority contracts, generic gap templates without verified subject
  context, incomplete instrumentation ordering, category framing, and one
  source-disproved contradiction.
- Consequence: `Question`, remediation/session state, scoring, and dashboard
  behavior remain unchanged. The frozen artifacts under `sampleDoc/.forge/` and
  `reports/atomic question gate 2026-09-28.md` become the new comparison baseline.
  The next rerun must retain the same thresholds; synthetic results remain
  calibration-ineligible and human review remains required.

## D-068: Issue-Level Consensus Improves Semantics But Does Not Open The Gate

- Status: implemented and measured in shadow; live integration remains blocked
- Decision: Advance the rubric to
  `0.8.1-atomic-question-corrections-shadow` rather than reinterpreting 0.8.0
  artifacts after changing instrumentation prerequisites. Require a strict
  majority for the same canonical contradiction relation and unordered evidence
  pair before attaching a contradiction issue to a question target. Carry exact
  source subject evidence separately from issue evidence, accept only explicit
  rubric-owned variants for a supplied closed-set framing, and require the local
  metric reference before an event-declaration question is eligible.
- Reason: Assertion-status agreement did not imply agreement on a specific issue;
  unioning every issue from runs that voted `contradictory` promoted singleton
  false positives. Gap context must remain auditable without pretending a
  prerequisite quote proves absence. The 0.8.1 rerun removed the known Rush
  precedence false positive and improved relevance from 82.76% to 92.59% and
  answerability from 86.21% to 92.59%.
- Consequence: The gate still fails. Consensus coverage was 99.07%, smallest-scope
  was 59.26%, and no-unsupported-assumption was 88.89%. Composite lower-priority
  contracts remain the binding defect. Scoring, legacy restoration, session
  state, the public `Question` model, and live remediation are unchanged. Exact
  results and limitations are appended to
  `reports/atomic question gate 2026-09-28.md`.

## D-069: Reject Relation-Incomplete Evaluation Claims

- Status: implemented; prior 0.8.1 evaluation-recall result superseded
- Decision: Reject a criterion-evaluation submission when any claim is absent
  from all evidence sets or when a referencing evidence set omits that claim's
  assertion id. State the same relation-completeness rule in the bounded prompt;
  never infer support from a bare claim in Python.
- Reason: Two 0.8.1 runs contained verified quotes and claims but no evidence-set
  relations. Their claims looked substantive in the raw artifact but could not
  contribute semantic support, causing false gaps such as Rush constraints.
- Consequence: Rubric `0.8.2-relation-complete-evaluation-shadow` forced fresh
  runs and became the valid pre-atomization baseline. Historical 0.8.1 proxy
  metrics remain renderer diagnostics only. Scoring remains unchanged.

## D-070: Atomize The Remaining Composite Question Contracts

- Status: implemented and measured in shadow
- Decision: Add contract `1.1` assertions and criterion-local prerequisites for
  acceptance subject, transitional state behavior, accessibility, open-question
  scope/identity/owner/deadline, alternative scope/disposition/rejection,
  assumption validation, and service-expectation dimensions. Remove same-field
  sibling evidence as implicit subject context; only declared prerequisites may
  provide exact subject evidence.
- Reason: The relation-complete 0.8.2 baseline confirmed that broad composite
  contracts, rather than generation variability, were the binding atomicity
  defect. Same-field evidence could also create misleading acceptance context.
- Consequence: Rubric `0.9.0-remaining-atomic-contracts-shadow` raised
  smallest-scope quality to 81.48%, passing that threshold, but applicability
  assumptions still blocked the full gate. Legacy fields, scores, gates, and
  restoration remain unchanged.

## D-071: Pass The Synthetic Engineering Gate Without Enabling Live Questions

- Status: engineering gate passed; human and integration gates remain blocked
- Decision: In rubric `0.9.1-applicability-contracts-shadow`, separate
  applicability from behavior for transitional states, sensitive data, and
  instrumentation; atomize requirement priority; accept source-backed
  framing-appropriate drivers in problem evaluation; and retain the unchanged
  predeclared thresholds.
- Reason: Three fresh relation-complete runs produced 25 deterministic questions
  with 100% consensus coverage, 92% relevance, 92% answerability, 96% smallest
  scope, and 100% no-unsupported-assumption. Unsupported output, duplicates, and
  repeated-run instability remained zero.
- Consequence: The synthetic engineering hypothesis passes for the first time,
  but the labels remain calibration-ineligible. Do not connect shadow questions
  to remediation sessions yet. First complete blinded human review and specify
  durable question identity, answer binding, evaluation revision, same-answer
  multi-gap closure, and state migration.
