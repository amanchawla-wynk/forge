# Atomic Question Gate - 2026-09-28

## Scope

This is the first fresh D-060 rerun under rubric
`0.8.0-atomic-evaluation-shadow`. It evaluates deterministic rubric/evidence
questions after the D-062 through D-066 atomic migrations. It is an engineering
gate using synthetic AI proxy review, not calibration or human validation.

Three isolated agents independently evaluated both internal PRDs. All 90
criterion artifacts verified against the current source snapshots and rubric
fingerprint. Each document produced 94 consolidated atomic assertion outcomes;
the artifacts retained bounded missing-decision detail for 133 gap variants.

## Predeclared Thresholds

Thresholds were written to the diagnostic artifact before reviewer labels
existed:

| Measure | Gate |
|---|---:|
| Consensus coverage | 100% |
| Relevant, yes | at least 90% |
| Answerable, yes | at least 90% |
| Smallest single-decision scope, yes | at least 80% |
| Unsupported assumption, no | at least 95% |
| Unsupported output text | 0 |
| Within-document duplicate questions | 0 |
| Repeated deterministic preparation | identical |

These are provisional engineering thresholds. Synthetic proxy labels cannot
establish organization validity or replace blinded human review.

## Mechanical Results

The planner produced 29 currently eligible questions. Deterministic templates
were primary; no question-generation model completion was requested.

- deterministic rendering: 29/29;
- unsupported text reaching output: 0;
- within-document duplicate questions: 0;
- repeated plan and wording stability: 29/29;
- mechanical gate: pass.

## Proxy Results

Three isolated reviewers completed all 29 questions against source documents
without seeing evaluation runs, thresholds, reports, code, or peer labels.

| Measure | Result | Gate | Pass |
|---|---:|---:|---:|
| Consensus coverage | 99.14% | 100% | no |
| Relevant, yes | 82.76% | 90% | no |
| Answerable, yes | 86.21% | 90% | no |
| Smallest scope, yes | 58.62% | 80% | no |
| Unsupported assumption, no | 82.76% | 95% | no |

Reviewers were unanimous across all dimensions for 18/29 questions. The overall
gate fails. Generated or deterministic shadow questions must not replace live
field remediation.

## Failure Analysis

The rerun separates four remaining causes:

1. Lower-priority composite contracts still emit broad questions. Examples are
   requirement prioritisation, transitional states, assumptions, data access,
   open-question dates, and alternative-rejection reasons.
2. Atomic gap templates are stable but can lack a verified subject. "Name the
   accountable owner for the material dependency" and "State which production
   expectation dimensions apply" do not identify which dependency or service
   claim prompted the gap.
3. Instrumentation ordering is incomplete. An event-declaration question can be
   eligible while the local metric reference is unresolved, causing an
   unsupported event assumption.
4. One Rush contradiction is a semantic false positive. The source states that
   Data Saver overrides manual quality, but the evaluator still asks which rule
   is authoritative. Exact evidence makes the error auditable but does not make
   the question useful.

Problem-framing questions also retain the known category issue for documents that
describe an opportunity or technical contract rather than a current user harm.
Deterministic shadow rendering does not yet apply the existing closed-set framing
variants.

## Gate Decision

Keep Phase 3 shadow-only. Preserve deterministic templates as the primary safety
path, but do not integrate them into remediation state.

The next corrective work is:

1. carry verified subject context from supported prerequisite or sibling
   assertions into gap targets and deterministic templates;
2. make the local metric reference a prerequisite for event declarations;
3. apply rubric-owned framing variants to deterministic shadow questions;
4. correct false contradiction attachment when evidence already states explicit
   precedence; and
5. atomize the remaining broad contracts identified above before another gate
   rerun.

## Reproduction

```bash
uv run python spikes/prepare_internal_atomic_evaluation.py prepare
uv run python spikes/prepare_internal_atomic_evaluation.py validate
uv run python spikes/run_atomic_question_diagnostics.py prepare
uv run python spikes/run_atomic_question_diagnostics.py review
```

## D-067 Corrective Rerun: Rubric 0.8.1

The first bounded corrective slice advanced the rubric to
`0.8.1-atomic-question-corrections-shadow`. The fingerprint change intentionally
invalidated the prior three runs. Three new isolated runs produced 90 verified
criterion artifacts, 188 consolidated atomic outcomes, and 198 gap variants
with bounded missing-decision detail.

The correction:

- requires a strict majority for the same canonical contradiction evidence pair
  before that issue can become question-eligible;
- carries exact verified subject evidence separately from evidence proving a gap;
- lets an already-resolved closed-set framing select only an explicit
  rubric-owned wording variant;
- resolves the local metric reference before event-declaration questions become
  eligible; and
- leaves scoring, legacy extraction restoration, and live remediation unchanged.

The corrected planner emitted 27 questions and again passed all mechanical
checks. Proxy results were:

| Measure | 0.8.0 | 0.8.1 | Gate | 0.8.1 Pass |
|---|---:|---:|---:|---:|
| Consensus coverage | 99.14% | 99.07% | 100% | no |
| Relevant, yes | 82.76% | 92.59% | 90% | yes |
| Answerable, yes | 86.21% | 92.59% | 90% | yes |
| Smallest scope, yes | 58.62% | 59.26% | 80% | no |
| Unsupported assumption, no | 82.76% | 88.89% | 95% | no |

The singleton Rush precedence false positive no longer became a question.
Opportunity framing removed the category error for Micro Dramas, although its
current rubric variant still combines opportunity and cost of inaction in one
question. Source-subject provenance is implemented and tested, but none of the
first eligible gaps in this corpus had a majority-supported prerequisite or
same-field sibling with evidence, so that mechanism did not affect these 27
questions.

The remaining smallest-scope failures are concentrated in composite contracts:
assumption categories, alternative rejection reasons, precedence/default rules,
open-question dates, transitional states, and service-expectation dimensions.
The remaining unsupported assumptions are the metric-reference wording, which
still presumes events, and an alternatives question where the source does not
establish rejected alternatives. One Rush constraint gap is also judged
irrelevant, indicating a remaining evaluation-recall problem rather than a
rendering problem.

**Decision:** keep the live gate closed. The next slice must atomize the named
composite contracts and improve prerequisite/context ordering before another
rerun. Thresholds remain unchanged.

## D-069 Integrity Correction: Rubric 0.8.2

Post-run analysis found that two 0.8.1 evaluator runs contained claims and exact
quotes without evidence-set relations. Those claims were structurally accepted
but semantically inert, so the 0.8.1 comparison remains useful as a renderer
signal but is not a trustworthy evaluation-recall baseline.

Forge now rejects:

- any claim not referenced by an evidence set; and
- any evidence set whose assertion ids omit the assertion of a referenced claim.

The bounded prompt states the same requirements and forbids reporting a gap when
an exact source statement satisfies the assertion. Rubric
`0.8.2-relation-complete-evaluation-shadow` forced three fresh runs. They yielded
90 verified artifacts, 188 consolidated outcomes, and 171 gap variants. Its 26
questions passed mechanical checks and measured:

| Measure | 0.8.2 | Gate | Pass |
|---|---:|---:|---:|
| Consensus coverage | 100% | 100% | yes |
| Relevant, yes | 80.77% | 90% | no |
| Answerable, yes | 88.46% | 90% | no |
| Smallest scope, yes | 61.54% | 80% | no |
| Unsupported assumption, no | 80.77% | 95% | no |

This relation-complete run is the valid pre-atomization baseline.

## D-070 Atomic Contract Rerun: Rubric 0.9.0

Rubric `0.9.0-remaining-atomic-contracts-shadow` added explicit contracts for
acceptance subjects, transitional states, accessibility, open questions,
alternatives, assumptions, and service-expectation dimensions. It also removed
same-field sibling evidence as implicit question context and corrected opportunity
and metric wording.

Three fresh runs yielded 90 verified artifacts, 212 consolidated outcomes, 129
gap variants, and 27 deterministic questions. Mechanical checks passed. The
smallest-scope rate crossed its gate, but relevance and assumption safety did not:

| Measure | 0.9.0 | Gate | Pass |
|---|---:|---:|---:|
| Consensus coverage | 99.07% | 100% | no |
| Relevant, yes | 77.78% | 90% | no |
| Answerable, yes | 92.59% | 90% | yes |
| Smallest scope, yes | 81.48% | 80% | yes |
| Unsupported assumption, no | 85.19% | 95% | no |

The surviving failures were applicability questions still combined with behavior
and broad roots for sensitive data, instrumentation, requirement priority, and
framing-aware problem evidence.

## D-071 Engineering Gate Pass: Rubric 0.9.1

Rubric `0.9.1-applicability-contracts-shadow` separates applicability from
behavior for transitional states, sensitive data, and instrumentation; atomizes
requirement priority; and makes problem evaluation accept a source-backed
framing-appropriate opportunity, mandate, or migration driver. Acceptance subject
evidence also explicitly accepts an exact title or overview.

Three fresh relation-complete runs produced:

- 90 verified criterion artifacts;
- 234 consolidated atomic assertion outcomes;
- 112 gap variants with bounded missing-decision detail; and
- 25 deterministic questions.

All mechanical and predeclared synthetic-proxy thresholds passed:

| Measure | 0.9.1 | Gate | Pass |
|---|---:|---:|---:|
| Consensus coverage | 100% | 100% | yes |
| Relevant, yes | 92% | 90% | yes |
| Answerable, yes | 92% | 90% | yes |
| Smallest scope, yes | 96% | 80% | yes |
| Unsupported assumption, no | 100% | 95% | yes |
| Unsupported output text | 0 | 0 | yes |
| Within-document duplicates | 0 | 0 | yes |
| Repeated deterministic preparation | identical | identical | yes |

**Decision:** the frozen synthetic engineering gate passes for the first time.
This does not establish calibration, organization validity, or human question
quality. Deterministic shadow questions must remain outside live remediation
until blinded human review passes and durable question identity, answer binding,
revision, and migration semantics are specified and tested.
