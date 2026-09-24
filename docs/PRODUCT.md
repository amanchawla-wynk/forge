# Forge Product Definition

## Purpose

Forge helps a product author answer one bounded question:

> Is this PRD complete and actionable enough for downstream teams to begin
> work without avoidable clarification cycles?

It is an advisory reviewer, not an approval gate and not a judge of whether the
product bet itself is strategically correct.

## Users

- PRD authors who want a useful review before circulation.
- Product leaders who want consistent language for document readiness.
- Engineering, design, QA, data, risk, leadership, and go-to-market readers
  who need their missing inputs identified.
- Coding-agent users in clients such as Cursor and GitHub Copilot.
- Users of the optional local dashboard who supply their own Claude, OpenAI,
  or Gemini API key instead of an MCP client.

## Initial Scope

- PRDs only. BRDs require a separate theory and rubric and are deferred.
- PDF and DOCX input first; plain text and Markdown are convenient additions.
- Embedded images and diagrams are detected and can be described on request
  using the client's vision-capable model. Text can affect scoring; visual
  interpretation stays advisory until its evidence model is validated.
- A source-backed cross-industry expert baseline that works without company
  inputs, with optional company-specific terminology and later validation.
- A readiness band, downstream-consumer breakdown, evidence, confidence, and
  concise reasons.
- A conversational question loop that shows exactly one highest-impact missing
  field at a time while collecting several answers before a checkpoint. At a
  checkpoint, Forge processes only the pending answers and affected criteria,
  verifies them as supplemental evidence, and rescores without re-extracting
  the unchanged PRD. Question wording adapts to whether the document describes
  a problem fix, opportunity bet, compliance mandate, or migration; the framing
  changes phrasing only and cannot affect the score.
- Evidence-anchored edge-case discovery that can turn a broad missing-state
  category into one concrete question about a verified requirement, without
  allowing the model to write the question or alter scoring.
- A persistent edge-case coverage ledger that asks one uncovered taxonomy cell
  per turn and claims completion only against its declared taxonomy version;
  one answer cannot satisfy unrelated requirements or failure modes.
- Local MCP server distribution with no Forge-hosted service required.
- An optional local dashboard (FastAPI + Next.js) exposing the same
  assessment and remediation loop for users without an MCP client. It is a
  documented exception to "no API key": see `docs/DECISIONS.md` D-033. It is
  not installed by default and is not a hosted service.

## Non-goals For V1

- Deciding whether the product strategy or commercial bet is correct.
- Replacing product, design, architecture, security, or legal review.
- Automatically approving or rejecting work.
- Comparing scores produced by different client models as if they were fully
  equivalent before cross-client calibration exists.
- BRD grading.
- A hosted dashboard.
- Mandatory Excel or SharePoint delivery; these may become optional adapters
  after the review and remediation loop is validated.
- Numeric predictions of rework, production risk, testing risk, or defect
  leakage without a separately validated model and supporting evidence.

## Product Experience

1. The user gives the agent a PRD file.
2. Forge normalizes the document while retaining page and section evidence.
3. The client's model extracts rubric fields and verbatim evidence.
4. Forge verifies evidence and computes deterministic verdicts and bands.
5. Forge makes one closed-set framing classification so rubric-authored
   questions fit the kind of product bet without allowing generated prose.
6. The user receives a concise deterministic narrative followed by the readiness
   band, consumer breakdown, failed gates, confidence, evidence-based reasons,
   and the single next question to answer.
7. Forge records the exact answer as pending supplemental evidence and asks the
   next queued question without re-extracting the unchanged PRD.
8. After a bounded checkpoint (default five answers, completion of a failed
   gate, or an explicit user request), Forge extracts only the pending answers
   against their named criteria, verifies their quotes, merges the resulting
   patches into the verified baseline, and deterministically rescores.
9. Steps 6 through 8 repeat until no material question remains or the user
   stops. Forge reports initial-assessment, remediation, and final-verification
   model usage separately so conversational improvement has a visible token and
   latency cost.
10. Forge previews a revision plan that maps approved answers to existing PRD
    sections and surfaces contradictions for resolution. On explicit approval,
    it writes an integrated new editable copy, preserves the original, and adds
    an audit appendix describing the accepted clarifications.
11. Forge performs one full reassessment of the revised copy without
    supplemental evidence. This final pass validates the durable artifact rather
    than conversational state.

When available, the caller may supply product terminology derived from an
implementation repository or other background. It helps the extractor resolve
names and aliases but is never treated as PRD evidence or credited by scoring.

## Review Coverage

The broader engineering-review prompt supplied during discovery is a useful
coverage checklist. Its requirement, gap, risk, testability, security,
operations, performance, and dependency categories should inform rubric design
and evidence-linked reporting where they apply to a PRD.

It is not itself a validated scoring model. Forge does not adopt its fixed
category percentages, guessed probability or impact values, predictive delivery
metrics, or approval language. Every scored item must belong to a versioned
rubric, and every credited claim must have verified evidence.

## Success Criteria

The product is credible only when:

- identical extraction inputs always produce identical scores;
- unsupported claims earn no credit;
- the score cannot be inflated merely by document length or polished prose;
- users can understand every lost point from cited document evidence;
- high-priority remediation questions materially improve actionability;
- agreement with calibrated internal reviewers is measured and acceptable;
- client/model variance is visible rather than hidden.

## Inputs Still Needed

Forge does not require these inputs to operate. They are needed to validate and
tune the expert baseline for organization-specific policy and language:

- The company's current PRD template.
- Internal guidance or examples of what "good" means.
- Several real PRDs spanning strong, average, and weak quality.
- Human labels and reviewer rationale, ideally from multiple roles.
