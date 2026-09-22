# PRD Readiness Scoring Theory

## Claim Being Measured

A PRD is good when its downstream consumers can act from it with minimal
avoidable clarification. Forge therefore measures operational readiness, not
writing quality, formatting, document length, or strategic correctness.

The primary lens is role-specific:

- Can engineering decompose and estimate the work?
- Can design identify states, constraints, and unresolved interactions?
- Can QA derive observable pass/fail cases?
- Can data instrument and evaluate the stated outcome?
- Can risk functions identify privacy, security, legal, or compliance impact?
- Can leadership understand the problem, outcome, tradeoffs, and cost of
  inaction?
- Can go-to-market teams understand rollout and customer-facing impact?

## Extraction Before Judgment

The LLM does not answer "how good is this?" and never assigns points. For each
criterion, it extracts named fields and a verbatim evidence quote. Python then
derives one of four verdicts:

- `present`: every required field has a non-placeholder value and verified
  evidence;
- `partial`: at least one, but not every, required field is satisfied;
- `absent`: no required field is satisfied;
- `not_applicable`: allowed only for criteria explicitly configured to permit
  it and accompanied by a reason.

This separation reduces verbosity bias, aesthetic bias, and model discretion.

## Evidence Rule

No quote means no credit. A quote that cannot be found in the normalized source
also means no credit. Evidence is location-aware where the source format permits
it. DOCX page numbers are not treated as reliable because pagination depends on
the renderer; paragraph and heading locations are used instead.

## Aggregation

- Verdict credits are fixed: present `1.0`, partial `0.5`, absent `0.0`.
- `not_applicable` criteria leave the denominator.
- Criterion weights are configured in the rubric and hidden from the LLM.
- Python performs all aggregation.
- The external result emphasizes a readiness band and role breakdown. A raw
  ratio may be retained for auditability but must not imply scientific
  precision.

## Gates

Critical omissions cap the final readiness band regardless of points elsewhere.
This prevents a long and polished document from masking an unmeasurable outcome
or unbounded scope. Gate configuration is company-specific and must be
calibrated rather than chosen solely by intuition.

## Repeated Extraction And Confidence

The intended design performs multiple extraction runs. The modal verdict wins;
ties resolve pessimistically. Agreement becomes confidence rather than being
averaged into a verdict no run produced.

Because Forge borrows the client model, results can vary by MCP host and model.
The assessment must expose available model metadata and run agreement. Scores
from different models are not assumed comparable until tested.

## Remediation

Questions are ordered by:

1. failed gates;
2. criterion weight;
3. number of downstream consumers unblocked;
4. stable criterion identifier.

Answers must be retained as supplemental user-provided evidence and clearly
distinguished from text originally present in the PRD. Forge should never
silently rewrite the source document and pretend the answer was already there.

The conversational experience asks one question at a time. After each answer,
the accumulated original and supplemental evidence is rescored before the next
question is selected. This keeps the conversation focused and allows each turn
to respond to the document's new state.

Each answer is bound to the criterion that prompted it. A quote from a
supplemental answer receives no credit for a different criterion. Verified
evidence records whether it came from the source document or a supplemental
answer so the two can never be presented as the same provenance.

## Output Restraint

The concise narrative report is a deterministic projection of the scored
assessment. It may summarize verdict counts, failed gates, blocked consumers,
prioritized gaps, the next remediation question, and extraction agreement. It
does not ask the LLM for a second interpretation and cannot introduce claims
that are absent from the structured audit.

A comprehensive review checklist is not automatically a defensible measurement
model. Category percentages, severity labels, probability estimates, project
health indices, rework estimates, and defect-leakage predictions require their
own definitions, evidence rules, and calibration. Forge does not generate them
merely because a report template requests them.

Structured gaps and risks may be reported when they are traceable to verified
document evidence or a specifically missing rubric field. They remain advisory;
the readiness band is not a Go/No-Go decision and never instructs an
organization to block development.

## Known Gaming And Failure Modes

- Padding and verbosity: defeated by field extraction rather than prose rating.
- Empty headings or `TBD`: rejected as placeholder values.
- Hallucinated content: defeated by exact evidence verification.
- Inappropriate N/A: permitted criterion-by-criterion and requires a reason.
- Model instability: surfaced through repeated-run agreement.
- Cross-model drift: recorded and evaluated during calibration.
- Prompt injection inside a PRD: document text is untrusted data; extraction
  prompts must explicitly ignore instructions found inside it.
- Template gaming: calibration must include superficially complete but
  substantively weak examples.
- Overly generic requirements: field presence alone may not establish
  testability. Anchored examples and human calibration are needed.

## Validation Plan

Build a labelled internal corpus with multiple reviewers and roles. Measure:

- test/retest consistency for each supported client/model;
- inter-reviewer agreement;
- model-to-human agreement by criterion and band;
- false-ready and false-needs-work rates;
- sensitivity to document length and shuffled section order;
- resistance to empty headings, placeholders, duplicated content, and prompt
  injection;
- whether answering recommended questions improves human-rated actionability.

No rubric version should be called calibrated until these tests have been run.
