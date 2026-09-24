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

- `present`: every required field has a non-placeholder value, satisfies any
  objective field constraint configured by the rubric, and has verified
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

Long-document processing must remain exhaustive. Every normalized source block
must be included in at least one extraction batch; relevance-ranked retrieval
cannot decide which parts of a PRD are eligible to receive credit. Reused
chunking libraries may choose safe text boundaries, but Forge retains the source
offsets and verifies the resulting evidence against the complete document.

Text recovered from an image may receive credit only when it is represented in
the normalized evidence corpus and the quoted text can be verified there.
Model interpretations of diagram structure, arrows, grouping, or visual meaning
are advisory and remain outside numeric scoring. Detecting a visual without
analyzing it must produce an explicit limitation warning.

A field declared as `string[]` may be extracted as a JSON array. Such a field
counts when at least one entry is a non-placeholder value and the evidence
quote verifies, so a list of `TBD` earns nothing.

A rubric field may also declare a regular-expression value constraint for an
objective, mechanically checkable requirement. Both the extracted value and
its verified quote must match. The generic rubric uses this only to require
quantified baselines and targets, and a numeric duration or named calendar
cadence for measurement windows. These constraints are rubric configuration,
not scoring-code heuristics, and remain subject to organization-specific
validation.

## Aggregation

- Verdict credits are fixed: present `1.0`, partial `0.5`, absent `0.0`.
- `not_applicable` criteria leave the denominator.
- Criterion weights are configured in the rubric and hidden from the LLM.
- Python performs all aggregation.
- The external result emphasizes a readiness band and role breakdown. A raw
  ratio may be retained for auditability but must not imply scientific
  precision.
- The highest band additionally requires every applicable criterion to be
  `present`. A high weighted average cannot support a claim that every
  downstream consumer can act while a known applicable gap remains.

## Expert Baseline

The bundled rubric is operational as a cross-industry expert baseline. Its
criteria are synthesized from published PRD guidance and worked examples,
service standards, accessibility and privacy guidance, and production-launch
practice. The source list is versioned with the rubric and exposed by
`describe_prd_rubric`.

The baseline provides a defensible default when an organization has supplied no
template or labels. It is not a statistical claim that its weights or band
thresholds predict a particular organization's reviewer decisions. Assessment
responses therefore identify `calibration_status: expert_baseline` rather than
using the ambiguous word "calibrated."

Public PRDs and templates are useful for coverage and adversarial regression.
No public corpus found during the 2026-09 review combined real PRDs, clear reuse
rights, and independent readiness labels. Public and synthetic cases are
therefore excluded from headline calibration metrics. Representative internal
cases remain the only basis for an `organization_validated` status.

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

If the initial three runs disagree, Forge identifies the disputed criteria and
recommends up to two additional complete runs. Additional runs improve the
estimate of stability; they do not guarantee a higher confidence value. A drop
in agreement after broader sampling is reported as evidence that extraction is
unstable, never hidden by selecting only favourable runs.

## Remediation

Questions are ordered by:

1. failed gates;
2. criterion weight;
3. number of downstream consumers unblocked;
4. stable criterion identifier.

Answers must be retained as supplemental user-provided evidence and clearly
distinguished from text originally present in the PRD. Forge should never
silently rewrite the source document and pretend the answer was already there.

The conversational experience asks one question at a time, but does not require
a full extraction or rescore after every answer. Forge builds a deterministic
queue from the last verified assessment, records exact user answers as pending
criterion-bound evidence, and advances through that queue until a checkpoint.
The default checkpoint is five answers; completing the missing fields of a
failed gate or an explicit user request also triggers one. At that point Forge
processes the pending answers together, rescoring before it rebuilds the queue.
This preserves a focused interaction without repeatedly sending an unchanged
long PRD to a model.

Checkpoint processing is incremental. The initial verified extraction remains
an immutable baseline bound to the source hash and rubric version. A delta
extraction sees only pending supplemental-answer blocks, the field definitions
and previously verified values for the affected criteria, and any edge-case
cell identities carried by those answers. It may update only those criteria or
cells. Python verifies every cited quote against the criterion-bound answer
block, merges valid patches into the baseline, and performs normal deterministic
scoring. One answer may satisfy several fields of its named criterion, but can
never satisfy another criterion.

A full exhaustive extraction remains required when the source document or
rubric changes and for the final reassessment of a materialized revision. It is
not required merely because another clarification answer was collected. Forge
reports token usage separately for initial extraction, remediation deltas, and
final verification; remediation should have a configured budget and must not
silently fall back to full-document extraction when that budget is exceeded.

One remediation delta is not represented as several independent model runs.
For remediated criteria, Forge retains the source-run agreement that existed
before remediation, marks its basis as `source_before_remediation`, and reports
the number of verified delta extractions separately. A copied criterion patch
therefore cannot manufacture unanimous test/retest confidence.

Each turn targets one missing required field, even when the selected criterion
has several gaps. The response retains the full missing-field list for audit but
shows one field-specific question and requirement. Band projection assumes only
that field is answered: an absent criterion may become partial, and a gate is
cleared only when the final required field becomes present.

Questions use configured, field-specific language rather than generated prose
or internal field identifiers. They ask for the missing fact directly, use
active and familiar wording, and preserve qualifiers that affect validation,
such as `single`, `current`, `numeric`, and `explicit`. The answer requirement
also includes any objective value constraint.

That plain, rubric-owned string is `Question.base_question` and never
changes. Two additive layers may adjust the `Question.question` text a client
actually sees, and neither lets a model author free user-facing prose (D-035):

- Level 0, always on: `question` is deterministically prefixed with the
  document's filename-derived display name, computed in Python with no model
  call, so it can never disagree with the file actually being scored.
- Level 1, opt-in via `contextualize_next_question`: the connected model
  performs exactly one closed-set choice — `{"choice": <int>}` — among up to
  five facts already verified elsewhere in the same assessment (same
  criterion first). Any response that is not exactly that shape, or whose
  integer is out of range, is mechanically discarded and the tool falls back
  to the Level 0 text. When a choice is accepted, Python assembles the final
  sentence from the static question, the display name, the chosen field's
  configured description, and its already-verified quote — the model never
  writes any of those words itself. This is a closed-output-space guardrail in the same
  spirit as typed-decision "System 1" classifiers: bound what the model may
  emit tightly enough that hallucination has no room to appear, rather than
  trusting free generation and only checking it afterward.

Before rendering questions, Forge may also classify the document's framing
through a closed output space: `problem_fix`, `opportunity_bet`,
`compliance_mandate`, or `migration_replatform`. The model returns only the
option index; rubric authors supply every phrasing variant. An invalid or
unclear choice uses the rubric's default wording. Framing solves category
errors such as asking a new-market PRD "what goes wrong today?": an
`opportunity_bet` instead asks what opportunity is being pursued and what the
business loses by waiting. Framing is presentation metadata only and cannot
change any scoring input or output.

When a behavioural edge-case field is missing, Forge may replace its generic
prompt with one evidence-anchored discovery question. The model selects two
integers: one source-verified fact and one fixed edge-case taxonomy entry.
Python combines the exact quote with rubric-owned question text. The model
cannot invent a scenario or rewrite the source. A malformed or inapplicable
selection falls back to the normal field question. This discovery remains
advisory: it identifies a plausible omission, while only the user's subsequent
criterion-bound answer can become evidence and affect the score.

The durable representation is edge-case coverage ledger `1.0`, not the single
question. Forge independently verifies requirement atoms, applies deterministic
rules to select applicable taxonomy pairs, and classifies every pair as
`covered`, `missing`, `not_applicable`, or `unclear`. Positive statuses require
verified evidence. Three native MCP runs consolidate by modal status with a
pessimistic tie-break; disagreement is exposed rather than averaged into a
status no run produced. Each user answer is bound to one requirement quote and
one taxonomy id, so it updates only that cell on the next stateless rescore.

The edge-case criterion is `PRESENT` only when the ledger is complete and the
existing platform and accessibility fields are also satisfied. It is `PARTIAL`
when there is verified progress but unresolved cells/components, and `ABSENT`
when no component has evidence. Therefore one offline answer cannot silently
complete playback, payments, quota, concurrency, and recovery coverage.
"Complete" always means complete against the declared taxonomy version, not
proof that every possible edge case has been imagined.

Each answer is bound to the criterion that prompted it. A quote from a
supplemental answer receives no credit for a different criterion. Verified
evidence records whether it came from the source document or a supplemental
answer so the two can never be presented as the same provenance.

Questions expose plain-language requirements for each missing field. After the
user approves the accumulated answers, Forge may propose an integrated revision
plan: place each answer in the most relevant existing section, identify any
conflict with existing text, and retain an audit appendix. The user must resolve
conflicts and approve the proposed edits before Forge creates a new editable
copy. Forge never overwrites the source or claims that conversational evidence
was originally present. The new copy receives a full assessment without
supplemental evidence before Forge reports its final readiness.

The generic `0.3.0-expert-prior` rubric added concrete coverage adapted from the
reviewed multi-agent project: transitional/degraded and platform/accessibility
states, production monitoring and support signals, and data-lifecycle controls.
These fields use Forge's quote verification and objective value constraints;
the external project's keyword weights and 0-100 score are not adopted.

The `0.4.0-expert-baseline` rubric introduced source-backed primary
flows and preconditions, failure acceptance criteria, accessibility validation,
dependency readiness, data minimisation and access, rollout thresholds and
ownership, assumption validation, production recovery, and document governance.
It also requires all applicable criteria for the top band.
The `0.4.1-expert-baseline` revision adds framing-aware, rubric-authored
question variants without changing criteria, weights, gates, or bands.
The `0.5.0-expert-baseline` revision adds the edge-case coverage ledger and
changes how `edge_cases_and_states` is derived when that ledger is supplied.

Implementation repositories may provide non-evidence terminology context. This
can clarify that two names refer to the same product or explain internal domain
terms, but it cannot satisfy a field. Context is excluded from normalized source
blocks, exact-quote lookup, and scoring. Contradictions between a PRD and code
remain questions for the owner; Forge never lets current implementation silently
rewrite intended requirements.

## Output Restraint

The concise narrative report is a deterministic projection of the scored
assessment. It may summarize verdict counts, failed gates, blocked consumers,
prioritized gaps, the next remediation question, and extraction agreement. It
does not ask the LLM for a second interpretation and cannot introduce claims
that are absent from the structured audit.

Role-specific presentation is also deterministic. Every failed criterion
produces a structured gap record containing its missing fields, affected
consumers, gate status, and rubric rationale. Consumer views group those records
without adding specialist-agent opinions, generated severity, or unsupported
technical, UX, or legal claims.

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
- Template gaming: a quantified success-metric gate now prevents the corpus's
  fluent-but-hollow example from reaching a ready band. Generic filler in other
  fields still inflates its raw score, so calibration must include
  superficially complete but substantively weak examples.
- Overly generic requirements: field presence alone may not establish
  testability. Anchored examples and human calibration are needed.

## Regression Corpus

`fixtures/corpus/` holds authored documents paired with extraction JSON, plus
expected bands. It locks the deterministic half of the system: placeholder
templates score zero, padding and section reordering do not move a score,
injected instructions cannot award credit, unverifiable quotes lose theirs,
and vague metric prose cannot satisfy configured quantitative constraints.

The corpus is a regression guard, not calibration. Its expected bands record the
versioned expert baseline's intended behaviour rather than organization-specific
truth. Human-labelled internal PRDs remain required before claiming that the
bands reproduce a particular organization's reviewer decisions.

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

The offline calibration evaluator records source type, excludes public and
synthetic examples from headline calibration metrics, and warns when there are
no internal labels, fewer than 20 resolved internal human bands, or no internal
cases with two completed reviewers. Reviewer results require a strict majority;
ties and pluralities are reported as contested and excluded from model-to-human
agreement. This differs from repeated model extraction, where pessimistic
tie-breaking is an intentional product rule.

Human reviewers label blinded sheets that omit Forge's prediction. Predictions
and completed reviewer sheets are merged only for evaluation, preventing the
model result from anchoring the supposed ground truth.

Public or synthetic PRDs without human readiness labels may be used for format
coverage, robustness, and gaming tests. They cannot determine criterion
weights, gate placement, or band thresholds. Dataset-level claims of quality or
completeness are not substitutes for document-level reviewer judgments.

No rubric version should be called calibrated until these tests have been run.
