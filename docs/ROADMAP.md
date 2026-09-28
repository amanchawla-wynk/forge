# Roadmap

## Completed

- Established PRD-first scope and downstream-consumer readiness framing.
- Defined versioned rubric, criteria, fields, weights, gates, and bands.
- Implemented deterministic ternary verdict and scoring engine.
- Implemented per-consumer readiness and gate-aware remediation ordering.
- Added tests for gates, evidence requirement, placeholders, N/A handling,
  pessimistic run consolidation, and determinism.
- Chose client-borrowed LLM inference with no API-key functionality.
- Added canonical product, theory, architecture, decision, and roadmap records.
- Implemented PDF, DOCX, Markdown, and text normalization with evidence
  locations.
- Added exact normalized quote verification before evidence receives credit.
- Added prompt-injection boundaries that treat source documents as untrusted.
- Exposed native MCP sampling assessment and an agent-driven fallback protocol.
- Added an in-memory MCP integration test proving three sampling requests and
  model metadata capture.
- Added criterion-bound supplemental-answer provenance and stateless rescore
  inputs to native sampling and agent-driven fallback tools.
- Replaced the top-five response with one adaptive `next_question`; complete
  assessments return no question.
- Added a concise deterministic narrative report above the detailed assessment
  audit, including key gaps, blocked consumers, next step, and confidence note.
- Evaluated RAG-Anything and narrower open-source alternatives for long-document
  processing; selected a reuse-first boundary with `semchunk` for text splitting
  and direct Docling evaluation for richer parsing.
- Integrated `semchunk` source offsets for oversized text blocks, exhaustive
  bounded extraction batches, and deterministic fragment consolidation.
- Added PDF and DOCX visual-asset detection with explicit warnings that visual
  interpretation is advisory and excluded from scoring.
- Added native per-batch client-model sampling through `list_prd_batches` and
  `assess_prd_batch`, with an end-to-end long-document MCP test.
- Bound fragments to a plan fingerprint and run index, and surfaced anticipated
  tool failures to the calling agent.
- Added advisory visual observations through `list_prd_visuals` and
  `observe_prd_visual`, using on-demand rendering and `ImageContent` sampling.
- Ran the first real company PRD (DOCX, 397 blocks, 26 sections, 24 images)
  end to end: ingestion, single-batch extraction with three agent runs,
  deterministic scoring, and the supplemental-answer rescore loop.
- Fixed extraction rejecting `string[]` rubric fields, which three independent
  runs all triggered on that document.
- Added an authored regression corpus with band expectations and anti-gaming
  invariants for padding, section order, placeholders, injection, and
  hallucinated quotes.
- Added a fluent-but-hollow template-gaming fixture and rubric-configured value
  constraints. Its vague success metrics now trigger the metric gate instead
  of receiving a false `ready_to_build` result.
- Added an offline human-label calibration evaluator with exhaustive templates,
  criterion and band agreement, reviewer disagreement, ordinal error,
  false-ready rates, source-mix checks, and low-sample warnings.
- Evaluated two public PRD datasets and rejected them as calibration truth: both
  lack human readiness labels, and their reuse licensing is unclear or
  contradictory. They remain candidates only for stress tests after licensing
  is resolved.
- Compared Forge with the BSD-licensed `multi-agent-prd-reviewer`. Retained
  Forge's verified deterministic architecture and adopted its strongest
  presentation idea as exhaustive structured gaps grouped by downstream
  consumer, without adding provider keys or free-text scoring agents.
- Ran three independent, quote-verified extraction passes on two internal PRDs
  and prepared separate blinded label sheets for two reviewers. Predictions are
  stored apart and cannot be merged until review is complete.
- Added disagreement-aware confidence escalation: disputed criteria are exposed
  and up to two additional complete runs are recommended without inflating the
  observed agreement value.
- Added explicit DOCX/Markdown/text revision materialization from approved
  conversational answers while preserving the original document.
- Advanced the generic rubric to `0.3.0-expert-prior` with concrete degraded
  state, accessibility/platform, observability/support, and data-lifecycle
  coverage adapted from the external multi-agent reviewer without its weights.
- Added non-scoreable product terminology context, grounded the two sample PRDs
  in the Xstream Play Rush implementation, and bound context changes into batch
  fingerprints without allowing code facts to satisfy PRD fields.
- Split remediation into one missing field per turn with concise prompts and
  field-accurate band projections, while preserving the complete gap audit.
- Rewrote every required-field question in plain conversational language,
  preserving numeric and evidence constraints while removing mechanical
  document-centric phrasing.
- Replaced the generic warning-only rubric with a versioned, source-backed
  cross-industry expert baseline covering 15 criteria and published rationale.
- Required every applicable criterion for `ready_to_build`, preventing a high
  weighted average from hiding a known gap.
- Excluded public and synthetic examples from headline calibration metrics and
  corrected false-ready and false-not-ready denominators.
- Added an optional local dashboard (`forge_dashboard` FastAPI backend plus a
  Next.js/shadcn UI in `web/`) covering upload, full assessment, and the
  one-question-at-a-time remediation loop, as a documented bring-your-own-key
  exception (D-033) that never touches `forge-mcp` or the domain core.
- Added guardrailed, closed-set contextualization of remediation questions
  (D-035): an always-on, model-free document-name prefix, plus an opt-in
  `contextualize_next_question` tool where the client model may only choose
  an index into an already-verified fact list — never author free text — with
  a deterministic fallback to the plain question on any invalid choice.
- Added closed-set document framing (`problem_fix`, `opportunity_bet`,
  `compliance_mandate`, `migration_replatform`) and rubric-authored phrasing
  variants, so opportunity PRDs are no longer asked what is "broken today";
  dashboard sessions detect framing once and preserve it across turns.
- Added evidence-anchored edge-case discovery: the model selects one verified
  source quote and one fixed failure-mode taxonomy entry, while Python renders
  the question and invalid choices fall back to the normal rubric wording.
- Replaced one-answer edge-case completion with versioned coverage ledger
  `1.0`: deterministic requirement/taxonomy pairs, closed-set four-state
  classification, three-run pessimistic consolidation in MCP, cell-bound
  answers, and an explicit taxonomy-relative stopping rule.
- Added `forge-setup-cursor` and `forge-setup-opencode`, one-command,
  idempotent CLIs that write/merge each client's own MCP config file (user-
  or project-scoped) so registering Forge needs no manual JSON editing or
  path lookup, plus fallback-aware prompts and client-specific
  troubleshooting notes in the README.
- Confirmed in a real OpenCode session that `assess_prd` fails because
  OpenCode does not support MCP sampling; the connected agent self-corrects
  to `prepare_prd_assessment`/`score_prd_extraction` as reported by a user.
  README's OpenCode section now states this directly instead of hedging.
- Confirmed in a real Cursor 3.22.7 session that `assess_prd` fails for the
  same reason: Cursor does not declare the MCP sampling capability. Cursor's
  setup guidance now goes directly to `prepare_prd_assessment` /
  `score_prd_extraction` instead of probing native sampling first (D-044).
- Replaced the raw `MCP error -32021: Client did not declare the sampling
  capability...` (reported in practice against `detect_prd_framing`) with a
  proactive capability check in every sampling resolver: a clear, catchable
  error naming the fallback tool when one exists, or stating plainly that
  none exists yet for the four advisory tools (D-039).
- Replaced per-answer full-document re-extraction with checkpointed remediation
  (D-040): a Forge-owned `RemediationState`, deterministic field queue, local
  opaque sessions, five-answer/gate/manual checkpoints, answer-only criterion
  delta prompts, verified patch merging, and unchanged-score signaling while
  answers remain pending.
- Added mandatory full-fragment plan fingerprints plus separate delta
  fingerprints, preventing fallback clients from scoring stale extraction JSON
  after the source, rubric, or pending answers change.
- Added remediation usage accounting and a hard 40,000-character delta budget;
  regression tests prove ordinary answers invoke no model and delta prompts do
  not contain the unchanged PRD body.
- Added integrated revision preview and writing (D-041) alongside appendix mode:
  source and approval digests, section placement, explicit per-edit conflict
  resolution, no-overwrite new copies, audit appendices, dashboard download,
  and automatic full reassessment of the generated dashboard artifact without
  supplemental answers.
- Replaced the in-memory remediation store with durable local SQLite review
  sessions (D-042), bound to exact source hash, rubric version, workspace, and
  local user, with optimistic versions, idempotent operation ids, transactional
  event history, expiry, and deletion.
- Added explicit workflow states and machine-readable `next_action` values to
  MCP and dashboard responses, with transition guards for answer and checkpoint
  operations and stale-version rejection across concurrent conversations.
- Added `find_prd_reviews`, `resume_prd_review`, `start_prd_review`, and
  `get_prd_review_status`; exact matches always require Resume / Start new /
  Cancel, cross-client resume requires confirmation, and the dashboard carries
  the review id and authoritative version in per-tab `sessionStorage`.
- Added restart, stale-version, duplicate-operation, wrong-document,
  exact-document discovery, explicit parallel-review, and OpenCode-to-Cursor
  resume regression coverage.
- Verified edge-case ledgers at remediation-session creation, closing a path
  where unsupported positive coverage could enter durable scoring state.
- Made dashboard documents, revision plans, generated artifacts, and final
  assessment links restart-durable; revision approval now participates in the
  versioned review workflow.
- Bound idempotency keys to operation type and request digest and reserve
  external checkpoint work before inference, preventing duplicate paid calls.
- Separated source-run agreement from remediation-delta evidence so one delta
  cannot appear as repeated independent consensus.
- Added preregistered development/holdout calibration splits, executable
  acceptance thresholds, `forge-calibration`, and `docs/VALIDATION_PROTOCOL.md`.
- Added agent-driven fallbacks for all four advisory sampling features and
  added DOCX body-order plus header/footer ingestion.
- Added dashboard upload, inference, timeout, retention, SQLite, loopback, and
  response-projection safeguards.
- Added the first D-045 deep-review vertical slice: verified claims survive
  pre-score batch consolidation and repeated runs, carry exact quote-local
  offsets, and feed deterministic findings for impossible numeric ranges and
  conflicting named skip thresholds. Assessment responses and durable
  remediation state retain the advisory review, and the dashboard presents it
  before readiness scoring.
- Added the bounded requirement-graph phase with claim, milestone, metric, and
  event nodes plus source-backed schedule, declaration, and formula edges.
  Deterministic review now also finds conflicting exact and relative timelines
  and formulas that reference undeclared events, while abstaining on deadlines,
  ambiguous dates, unsupported formulas, and wholly missing event inventories.
- Added closed-set conflict classification (D-046): deterministic candidate
  pairing by named subject, a fixed relation taxonomy, three-run strict-majority
  consolidation with ties resolving to `unclear`, quote re-verification, and
  template-rendered `classified` findings exposed through the `consistency`
  advisory kind and `score_prd_extraction`.
- Added the offline `forge-review-eval` golden-case harness (D-047): blinded
  reviewer sheets, strict-majority consensus, one-to-one quote matching,
  development/holdout splits, internal-only headline metrics, preregistered
  threshold checks, and precision, recall, blocker recall, quote-alignment,
  duplicate, false-positive, and inter-reviewer reports.
- Ran three source-family AI proxy reviews over the MicroDrama recommendations
  PDF using public Google, Microsoft/LinkedIn, Atlassian/GitLab/GOV.UK, and
  related first-party guidance. Materialized 29 proxy labels with 75 verified
  source spans, including hard negatives and disagreements, under a
  calibration-ineligible schema (D-048).
- Advanced the expert baseline to `0.6.0` with required runtime precedence and
  requirement-to-test mapping evidence plus stronger dependency-readiness
  wording. Weights, gates, bands, and verdict credits are unchanged.
- Added measured deep-review recall (D-051): `forge-proxy-diagnostics` reports
  finding recall, blocker recall, coverage, and hard-negative violations against
  the synthetic proxy ledger. First measurement: recall 3/19 (0.158), blocker
  recall 3/9 (0.333), 0 hard-negative violations. Candidate generation gained
  category pairing, budget reservation, quote-pair deduplication, and exclusion
  of pairs already proved deterministically.
- Completed the deterministic core and deferred both frameworks (D-050):
  overlapping relative timelines and exact-versus-relative schedules now abstain,
  every claim carries a deterministic `ClaimInterpretation`, same-scope
  `opposite_polarity`, `duplicate_rank`, and `precedence_cycle` checks were
  added, consistency taxonomy `1.1` added `implied_exception` and
  `ambiguous_scope`, and executable LangGraph/property-graph spikes recorded a
  do-not-adopt-yet result.
- Added deterministic structured-contract findings (D-049): flattened tier
  rows and declared domains now expose incompatible enum mappings, and exact
  machine field names expose array/scalar or other schema-type conflicts.
  Explicitly different product, variant, phase, surface, or fallback scopes and
  repeated compatible declarations are hard negatives.
- Completed the architecture-audit Phase 0 hardening (D-052): direct and batched
  extraction now share exact schema validation; per-item list evidence survives
  session restart while remaining absent from model schemas; checkpoint output
  uses one persisted evaluation revision and refreshed deterministic deep review;
  uncovered edge-case cells are explicit queue entries; dashboard coverage uses
  repeated pessimistic consolidation; and MCP revision writes are session-bound,
  versioned, crash-recoverable, restricted to the exact previewed verified
  answers, and completed only after a hash-bound full assessment of the generated
  artifact. Durable answer ids now survive restart and version-1 pending sessions
  are repaired safely on load.
- Added immutable, parser-versioned source snapshots (D-053): acquisition is
  byte-exact and source-neutral, canonical nodes and normalized content are
  hashed, extraction and remediation fingerprints bind the snapshot plus rubric,
  and SQLite sessions persist the complete parse for restart-safe checkpoints.
  Discovery/resume fail closed on parser, normalized-content, snapshot, or rubric
  drift; legacy sessions remain audit-only. Dashboard and MCP advisory operations
  now reuse one prepared assessment instead of reparsing within an operation.
- Added `spikes/parser_benchmark.py`, a dependency-free control harness that can
  compare the current parser with optional Docling and PyMuPDF4LLM installs for
  timing, determinism, text retention, structure, images, pages, and provenance.
  Measured the two DOCX and one PDF files in `sampleDoc/`: Docling retained
  98.26-99.41% of baseline tokens and recovered materially richer heading/table
  structure, while PyMuPDF4LLM provided a faster PDF control. Results are in
  `reports/parser benchmark 2026-09-26.md`; no candidate has been adopted pending
  manual evidence/provenance review.
- Added Phase 2 criterion evaluation in score-neutral shadow mode (D-054): strict
  submissions retain multiple support/counterevidence sets, gaps, ambiguities,
  and contradictions; Python verifies named blocks and exact spans, requires
  exhaustive batches, mints authoritative ids, and consolidates repeated runs
  conservatively. `prepare_prd_evaluation` / `apply_prd_evaluation` expose the
  agent-driven flow. Legacy extraction has a reversible score-parity adapter,
  and new durable reviews transactionally persist per-run evaluation artifacts
  under state schema version `3`. The rubric is now
  `0.7.0-evaluation-shadow`; scoring rules are unchanged.
- Added criterion-evaluation shadow diagnostics and completed the first
  three-run study (D-055). The authored corpus achieved 88% full status
  agreement, 5.33% abstention, 100% quote verification, and 81.33% symmetric
  native/legacy agreement; native evaluation preserved a real ambiguity in the
  complete fixture and rejected many fluent-but-hollow gaming claims. The two
  internal DOCX samples achieved only 56.67% full agreement, so Phase 3 was
  blocked at that checkpoint. Full results are in
  `reports/criterion evaluation shadow diagnostics 2026-09-26.md`.
- Replaced whole-criterion shadow voting with assertion-level strict-majority
  reconciliation (D-056), retaining minority evidence for audit. The unchanged
  study now reports 95.29% full assertion agreement on the corpus and 74.51% on
  internal PRDs, with internal abstention reduced to 16.67%. This improves the
  representation but did not by itself clear the Phase 3 gate.
- Normalized support and ambiguity identities so model paraphrases do not block
  deterministic merging (D-057). Added prediction-free sheets for every
  assertion in both internal PRDs and a strict agreement evaluator. The sheets
  were initially blank, so Forge correctly reported no agreement or consensus
  before the proxy reviews in D-058 were completed.
- Completed three isolated synthetic AI proxy reviews because human reviewers
  were unavailable (D-058). Agents unanimously agreed on 79/102 assertions,
  produced strict-majority consensus for 100, and native shadow outcomes matched
  81/100 consensus labels. This opens Phase 3 as a guarded score-neutral shadow
  prototype only; it does not clear calibration or production-default gates.
- Implemented the first Phase 3 shadow question slice (D-059). Exhaustive native
  evaluations now expose one deterministically ranked strict-majority issue to a
  bounded host prompt. Python re-verifies the evaluation batch, accepts only
  lexically grounded wording and exact source quotations, and otherwise returns
  the rubric-owned answer contract. The artifact has no score effect and is not
  connected to live remediation or persisted sessions.
- Added frozen question diagnostics and three isolated generation/reviewer runs
  (D-060). Across 198 completions, no unsupported text reached output, fallback
  was at most 4.55% per run, and wording was stable for 63/66 targets. The live
  gate failed: synthetic proxy consensus rated only 29/71 unique questions as
  single-decision scope and identified unsupported assumptions in 13/71. The
  baseline is recorded in
  `reports/question generation shadow diagnostics 2026-09-28.md`.
- Fixed assertion-outcome issue references exposed by that study: selected
  ambiguity and contradiction outcomes no longer carry lower-priority gap ids;
  all minority issue records remain auditable.
- Implemented and reran the D-060 corrective slice (D-061): bounded gap detail,
  issue-variant grouping, sibling deduplication, first-gap deferral, and
  evidence-rendered conflict fallback. Three fresh native evaluation runs
  produced 90 verified artifacts and reduced active plans from 66 to 28. Proxy
  relevance improved to 44/46 and answerability to 46/46, but only 15/46 were
  single-decision scope, 8/46 retained unsupported assumptions, fallback rose to
  39-46%, and wording stability was 14/28. Live integration remains blocked.
- Added atomic evaluation contract infrastructure and the dependency-readiness
  vertical slice (D-062). Contract `1.1` validates resolution contracts and a
  prerequisite DAG; native outcomes now use assertion ids, while the reversible
  legacy adapter fans one field witness into mapped atoms with exact score parity.
  The rubric first advanced to `0.8.0-atomic-evaluation-shadow`; old 0.7 shadow
  submissions remain historical and require fresh runs rather than silent
  reinterpretation.
- Added the operational-readiness atomic slice (D-063): applicable service-level
  dimensions are gated by a required scope decision; monitoring, support, and
  incident owners are separate; and recovery behavior depends on a diagnostic
  method. All three legacy fields still round-trip with exact score parity.
- Added the rollout atomic slice (D-064): mechanism gates thresholds and rollback
  trigger, promotion waits for entry plus observation, rollback procedure waits
  for its trigger, authority/execution are separate, and optional launch-channel
  actions follow an impact-scope decision. All five legacy rollout fields retain
  exact score parity.
- Added the instrumentation atomic slice (D-065): event declarations gate
  properties, events plus a local metric reference gate the formula, and scoped
  operational signals separate detection from diagnosis. All three legacy
  instrumentation fields retain exact score parity, including list evidence and
  objective signal constraints.
- Added the acceptance-coverage atomic slice (D-066): completion/pass/fail,
  applicability-scoped failure categories, requirement inventory, mapping, and
  completeness are separate ordered decisions. Dynamic requirement names remain
  document data, while all three legacy fields and the acceptance gate retain
  exact parity.
- Reran the frozen question gate under rubric 0.8 with deterministic templates
  and predeclared thresholds (D-067). Three fresh evaluation runs yielded 90
  verified artifacts and 29 stable questions with zero unsupported output or
  duplicates. The semantic gate failed: 82.76% relevant, 86.21% answerable,
  58.62% smallest-scope, and 82.76% no-unsupported-assumption. Results are in
  `reports/atomic question gate 2026-09-28.md`; live integration remains blocked.
- Advanced to `0.8.1-atomic-question-corrections-shadow` (D-068), invalidated the
  old fingerprint, and completed three fresh isolated runs. Canonical
  issue-majority filtering removed the known false precedence question;
  rubric-owned opportunity framing and corrected ordering raised relevance and
  answerability to 92.59%, passing both gates. Smallest scope (59.26%), assumption
  safety (88.89%), and consensus coverage (99.07%) still fail, so live integration
  remains blocked.
- Found and closed the orphan-claim integrity hole (D-069). Claims now require an
  evidence-set relation that includes their assertion id. Fresh relation-complete
  0.8.2 runs replaced the untrustworthy evaluation-recall baseline.
- Atomized the remaining composite contracts and removed implicit same-field
  subject context (D-070). Rubric 0.9.0 raised smallest-scope quality to 81.48%
  but retained applicability failures.
- Added applicability-first contracts and framing-aware problem evaluation in
  `0.9.1-applicability-contracts-shadow` (D-071). Three fresh runs yielded 90
  verified artifacts and 25 deterministic questions. The frozen synthetic gate
  passes: 100% consensus coverage, 92% relevance, 92% answerability, 96%
  smallest-scope, 100% assumption safety, zero unsupported output, zero
  duplicates, and stable repeated preparation. This is not human validation or
  calibration, so live integration remains blocked.

## Current Build

- Run a blinded human review against the frozen 0.9.1 question set without
  changing thresholds or wording based on those labels.
- Define durable `question_id`/`issue_id` answer binding, same-answer multi-gap
  closure, evaluation-revision behavior, and state migration before considering
  any replacement of legacy field questions.
- Compare legacy-parser and Docling shadow evaluations on the same snapshot
  fixtures after the bounded Docling adapter exists, using evidence ids and
  canonical spans rather than raw output text as the comparison unit.
- Specify the deep-review finding, claim-ledger, and consistency-ledger schemas
  required by D-045, including exact quote provenance, scope, phase, modality,
  affected consumers, implementation consequence, and required author decision.
- Fix claim granularity for multi-line source units. Measured with
  `forge-proxy-diagnostics`, PDF line splitting breaks one statement into
  several claims, so state-lifetime, activation, dependency-status, and
  precedence conflicts cannot form candidate pairs at all. This is the binding
  constraint on recall and blocks the detectors below.
- Then extend classified conflict coverage to state lifetimes, activation
  states, dependency status, undefined boundaries, and unstated fallbacks,
  re-measuring recall after each addition and retaining the proxy ledger's
  scoped and compatible hard negatives.
- Replace the MicroDrama proxy labels with at least two blinded human reviews
  when reviewers become available, then add a separate post-prediction pass for
  priority agreement and actionability.
- Re-run `spikes/graph_framework_comparison.py` only when durable branching,
  background execution, or multi-party approvals become real requirements; both
  frameworks were measured and deferred in D-050.
- Grow the regression corpus with a multi-batch document.
- Run the checkpointed one-question remediation loop on both internal PRDs,
  materialize approved answers into new copies, and measure score,
  extraction-agreement, token, and latency movement.
- Resolve the documented Rush quality contradictions: Data Saver precedence,
  flag-off behavior, and the 360p fallback algorithm.
- Evaluate local OCR output as separately provenanced, quote-verifiable evidence.
- Manually label quote fidelity, table-cell order, repeated headers, OCR-only
  text, and canonical provenance across the measured `sampleDoc/` outputs, then
  compare corpus and proxy-diagnostic behavior before selecting a parser.

## Next

- Test installation, MCP sampling capability, and fallback behavior in GitHub
  Copilot.
- Investigate SEP-2577 (the installed MCP SDK marks the whole `sampling`
  capability `@deprecated` as of protocol revision 2026-07-28) and whether
  Forge's client-borrowed-model architecture (D-006/D-007) should move to
  whatever replaces it.
- Test the dashboard's `dashboard` extra install and BYOK flow against real
  Anthropic, OpenAI, and Gemini keys on a clean machine.
- Prototype a direct Docling adapter behind a new parser fingerprint, without
  making it the production default, to measure corpus and proxy-diagnostic
  behavior before expanding to multimodal content.
- Add qualitative risk records only where source evidence or a rubric omission
  supports them; do not invent probability or numeric risk scores.

## Blocked On Company Inputs

- Validate and, where evidence supports it, tune terminology, weights, gates,
  and bands to the company PRD template and guidance. The expert baseline works
  without this validation.
- Build adversarial and representative fixtures from real PRDs.
- Expand the multi-reviewer labelled calibration set beyond the first real PRD.
- Set acceptable agreement and false-ready thresholds.
- Validate the edge-case taxonomy's deterministic requirement-applicability
  rules (D-038) against reviewed PRDs; the rules are an unvalidated expert
  prior, same status as the rest of the bundled rubric.

## Later

- Dashboard: visual asset review, long-document batch progress UI, and
  revision export/download, reusing `forge.ingest.visuals` and `forge.revise`
  the same way the v1 dashboard reuses `forge.service`.
- Optional Excel workbook output adapter.
- Optional SharePoint publication adapter using caller-managed authentication.
- Optional remote MCP transport.
- BRD-specific theory and rubric.
- Separate rubrics and ingestion strategies for ARDs, user stories, API
  specifications, solution documents, and design artifacts.
- Rubric administration and version migration.
