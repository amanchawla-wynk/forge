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
