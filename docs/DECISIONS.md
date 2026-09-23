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
