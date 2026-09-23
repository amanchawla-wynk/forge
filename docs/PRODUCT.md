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
- A future dashboard using the same ingestion and deterministic scoring core.

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
- A conversational question loop that asks for exactly one highest-impact
  missing field in concise language, retains the answer as supplemental
  evidence, and then rescores.
- Local MCP server distribution with no Forge-hosted service required.

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
5. The user receives a concise deterministic narrative followed by the readiness
   band, consumer breakdown, failed gates, confidence, evidence-based reasons,
   and the single next question to answer.
6. The answer is added as explicit supplemental evidence and the PRD is
   rescored.
7. Steps 5 and 6 repeat until no material question remains or the user stops.
8. On explicit approval, Forge writes the accumulated answers into a new
   editable PRD revision. The original remains unchanged, and the revision can
   be reassessed without supplemental evidence.

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
