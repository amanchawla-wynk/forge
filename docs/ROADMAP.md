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
- Replaced the raw `MCP error -32021: Client did not declare the sampling
  capability...` (reported in practice against `detect_prd_framing`) with a
  proactive capability check in every sampling resolver: a clear, catchable
  error naming the fallback tool when one exists, or stating plainly that
  none exists yet for the four advisory tools (D-039).

## Current Build

- Grow the regression corpus with a multi-batch document.
- Run the one-question remediation loop on both internal PRDs, materialize the
  approved answers, and measure score and extraction-agreement movement.
- Resolve the documented Rush quality contradictions: Data Saver precedence,
  flag-off behavior, and the 360p fallback algorithm.
- Evaluate local OCR output as separately provenanced, quote-verifiable evidence.
- Harden extraction validation against duplicate or unknown criterion fields.
- Ingest DOCX header and footer text, which is currently skipped.

## Next

- Confirm, in a real running Cursor session, whether `assess_prd` native
  sampling works or whether Cursor also requires the
  `prepare_prd_assessment` / `score_prd_extraction` fallback (setup and a
  fallback-aware prompt are documented and automated via `forge-setup-cursor`,
  but live sampling behavior has not been observed firsthand there; OpenCode
  is now confirmed not to support it). Test installation and behavior in
  GitHub Copilot similarly.
- Add non-sampling fallback tools for `detect_prd_framing`,
  `discover_edge_case_question`, `assess_edge_case_coverage`, and
  `contextualize_next_question`, mirroring `prepare_prd_assessment` +
  `score_prd_extraction`, so clients without sampling (confirmed: at least
  one OpenCode build) can still use framing and edge-case features instead of
  losing them outright (D-039).
- Investigate SEP-2577 (the installed MCP SDK marks the whole `sampling`
  capability `@deprecated` as of protocol revision 2026-07-28) and whether
  Forge's client-borrowed-model architecture (D-006/D-007) should move to
  whatever replaces it.
- Test the dashboard's `dashboard` extra install and BYOK flow against real
  Anthropic, OpenAI, and Gemini keys on a clean machine.
- Compare a direct Docling adapter with current PDF and DOCX normalization on
  representative fixtures before expanding to multimodal document content.
- Add qualitative risk records only where source evidence or a rubric omission
  supports them; do not invent probability or numeric risk scores.
- Add local session storage only if the stateless workflow proves cumbersome.

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
