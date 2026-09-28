# Question Generation Shadow Diagnostics - 2026-09-28

## Scope

This diagnostic evaluates the D-059 bounded question slice against the two
internal PRDs used for criterion-evaluation shadow testing. It is an engineering
diagnostic, not calibration. All generation and review artifacts are marked
`calibration_eligible: false` and `score_effect: none`.

The frozen procedure is:

1. Re-verify the three native criterion-evaluation runs against exact sources.
2. Enumerate every exhaustive, three-run, strict-majority gap, ambiguity, or
   contradiction target.
3. Have three isolated agents complete the bounded prompt for every target.
4. Apply production validation and deterministic fallback to every completion.
5. Compare rendered wording across the three independent runs.
6. Deduplicate rendered candidates and have three different isolated agents
   review them against the complete source documents without seeing Forge
   targets, evidence selections, generation modes, peer labels, or reports.

The ignored artifacts are under `sampleDoc/.forge/`:

- `question-generation-prompts.json`
- `question-generation-run{1,2,3}.json`
- `question-diagnostic-report.json`
- `question-review-ai-proxy-{1,2,3}.json`
- `question-review-report.json`

## Mechanical Results

There were 66 eligible assertion targets and 198 independent completions.

| Measure | Run 1 | Run 2 | Run 3 |
|---|---:|---:|---:|
| Accepted generated wording | 65/66 (98.48%) | 66/66 (100%) | 63/66 (95.45%) |
| Rubric fallback | 1/66 (1.52%) | 0/66 (0%) | 3/66 (4.55%) |
| Unsupported wording rejected | 1 | 0 | 3 |
| Unsupported text reaching output | 0 | 0 | 0 |
| Within-document duplicate output | 0 | 0 | 0 |
| Deterministic preparation repeat | pass | pass | pass |

Rendered wording matched across all three runs for 63/66 targets (95.45%). The
three variable targets produced 71 unique rendered candidates. The lexical
closed-world validator therefore provides the intended mechanical safety and a
low fallback rate, but those facts do not establish question usefulness.

The run also exposed and regression-locked a Phase 2 referential bug. A selected
ambiguity or contradiction outcome previously retained lower-priority gap issue
ids because per-run outcomes unioned every issue category. Assertion outcomes
now retain only issue ids for their selected status; all underlying minority
records remain in the criterion audit.

## Synthetic Proxy Review

Three isolated AI proxy reviewers completed all 71 unique candidates. They were
unanimous on all four dimensions for 35/71 questions (49.30%); 36 questions had
at least one disputed dimension. Strict-majority consensus produced:

| Dimension | Yes | No | Unclear / no majority |
|---|---:|---:|---:|
| Relevant to a real unresolved source issue | 59 | 11 | 1 |
| Answerable by the PRD owner | 64 | 0 | 7 |
| Smallest single-decision scope | 29 | 42 | 0 |
| Contains an unsupported assumption | 13 | 58 | 0 |

These are synthetic proxy labels, not inter-reviewer agreement and not human
ground truth. They may reject the current engineering hypothesis, but cannot
validate a future one.

## Failure Analysis

The live-path gate fails. Mechanical grounding alone is insufficient because the
question plan still inherits field-oriented representation loss:

- One model-submitted gap may bind several assertions. The enumerator currently
  emits one candidate per assertion instead of one candidate per issue id, so a
  single broad absence becomes several sibling questions.
- Later fields can presuppose an unresolved antecedent. Baseline, target, and
  measurement-window questions refer to "that metric" even when the primary
  metric is itself missing. Proxy reviewers correctly identify those assumptions
  as unsupported or answerability as unclear.
- Many rubric answer contracts intentionally collect several facts. They remain
  useful safe fallbacks, but are not the smallest single-decision question.
- Gap records retain a rubric question but no source-specific model description
  of the missing decision. With no verified source anchor for an absence, the
  bounded generator usually repeats the broad answer contract.
- Contradiction targets can fall back to a presence question, such as asking for
  requirements that already exist, instead of asking which conflicting rule is
  authoritative.

## Gate Decision

Keep Phase 3 in shadow. Do not replace `Question`, remediation queues, answer
binding, sessions, or dashboard behavior with generated plans.

The next corrective slice must:

1. retain a bounded, audit-only missing-decision description on evaluation gaps;
2. plan and deduplicate issue ids rather than emitting every assertion sibling;
3. suppress dependent questions until their prerequisite decision is resolved;
4. render ambiguity and contradiction questions from exact verified evidence and
   rubric-owned resolution templates, with generation remaining optional; and
5. rerun this exact frozen diagnostic before any live-path proposal.

Human review remains required before a quality, calibration, or
organization-validity claim.

## Corrective Rerun

D-061 tested the D-060 corrective hypothesis instead of editing the frozen
baseline. The implementation added optional bounded `missing_decision` text to
gap submissions without changing gap identity, retained all descriptions across
runs, grouped multi-run issue-id variants into one outcome plan, deduplicated
shared issue ids across sibling assertions, exposed only the first unresolved
gap per criterion, and rendered ambiguity/contradiction fallbacks from verified
evidence.

Because the original Phase 2 artifacts predated `missing_decision`, three new
isolated native evaluation runs were produced for both internal PRDs. All 90
criterion artifacts verified. Their consolidated records retained bounded detail
for 98 gap variants. These v2 artifacts are versioned separately under
`sampleDoc/.forge/evaluation-shadow-v2-*`; the D-055/D-058 baseline is unchanged.

The enriched planner produced 28 currently actionable plans, down from 66. Three
new isolated generation runs produced 84 completions:

| Measure | Run 1 | Run 2 | Run 3 |
|---|---:|---:|---:|
| Accepted generated wording | 17/28 (60.71%) | 15/28 (53.57%) | 17/28 (60.71%) |
| Rubric/evidence fallback | 11/28 (39.29%) | 13/28 (46.43%) | 11/28 (39.29%) |
| Unsupported text reaching output | 0 | 0 | 0 |
| Within-document duplicate output | 0 | 0 | 0 |

Exact rendered wording matched for 14/28 plans (50%). The lexical boundary
remained safe but rejected many useful paraphrases, while accepted wording varied
more because richer missing-decision descriptions allowed more choices.

Three new isolated proxy reviewers completed all 46 unique rendered candidates:

| Dimension | Yes | No | Unclear / no majority |
|---|---:|---:|---:|
| Relevant to a real unresolved source issue | 44 | 2 | 0 |
| Answerable by the PRD owner | 46 | 0 | 0 |
| Smallest single-decision scope | 15 | 31 | 0 |
| Contains an unsupported assumption | 8 | 38 | 0 |

Reviewers were unanimous across all dimensions for 33/46 candidates. Relative to
the first baseline, relevance and answerability improved, but smallest-scope
performance declined and unsupported assumptions changed only slightly. Typical
failures expose the lower boundary: one evaluation assertion still combines
owner, readiness proof, failure behavior, and fallback; another combines
availability, latency, capacity, integrity, and recovery. Question generation
cannot turn those composite answer obligations into one decision without losing
the assertion contract.

The live gate remains closed. The next representation must split composite
shadow assertions into atomic resolution contracts and declare prerequisite
edges between them. Multiple shadow assertions may continue mapping to one
legacy scoring field, so this work must remain score-neutral. Deterministic
issue/evidence templates should be primary; model-authored wording remains an
optional shadow comparison until stability and scope improve.

## Reproduction

```bash
uv run python spikes/run_internal_question_diagnostics.py prepare
uv run python spikes/run_internal_question_diagnostics.py evaluate
uv run python spikes/run_internal_question_diagnostics.py review
uv run python spikes/prepare_internal_evaluation_shadow_v2.py prepare
uv run python spikes/prepare_internal_evaluation_shadow_v2.py validate
```
