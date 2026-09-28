# Criterion Evaluation Shadow Diagnostics

Date: 2026-09-26

## Scope

Three independent connected-agent runs evaluated every active rubric criterion
without reading legacy extraction fixtures. The study covered:

- five authored regression documents in `fixtures/corpus/`;
- `sampleDoc/Micro Dramas.docx`;
- `sampleDoc/Rush_Playback_Quality_Selection_Guide.docx`.

Python verified every submitted quote against its named block, required complete
criterion/batch/run schemas, minted evidence identities, and consolidated runs.
The study is synthetic and diagnostic. It is not calibration evidence, a human
quality label, or a scoring input. The agent host did not expose latency or token
metadata, so those fields remain unreported rather than zero.

## Authored Corpus

| Metric | Result |
| --- | ---: |
| Cases | 5 |
| Criterion outcomes | 75 |
| Exact quote verification | 280 / 280 |
| Duplicate submitted references | 0 / 280 |
| Unique verified spans | 129 |
| Full three-run status agreement | 66 / 75 (88.00%) |
| Full assertion-level agreement | 243 / 255 (95.29%) |
| Consolidated abstention (`unclear`) | 4 / 75 (5.33%) |
| Native/legacy exact status agreement | 61 / 75 (81.33%) |

Consolidated native statuses were 16 `supported`, 9 `partial`, 46
`unsupported`, and 4 `unclear`.

The status mismatches were useful rather than uniformly erroneous. The fluent
but hollow `gaming` fixture produced ten native/legacy differences: native
evaluation downgraded seven legacy `partial` outcomes and one legacy `supported`
outcome to `unsupported`, which is consistent with the fixture's intended
anti-gaming role. The `placeholders` fixture had unanimous `unsupported` status
for all 15 criteria and exact native/legacy agreement.

The authored `complete` fixture had one native `unclear` result where legacy
field scoring reported `supported`. Two runs retained tension between
"duplicate requests return the original result" and "submitted twice must be
rejected." Those statements may be compatible if rejection means no second
record while the original result is returned, but the document does not state
that reconciliation. Preserving the ambiguity is preferable to silently
discarding one witness.

## Internal Documents

| Metric | Result |
| --- | ---: |
| Cases | 2 |
| Criterion outcomes | 30 |
| Exact quote verification | 261 / 261 |
| Duplicate submitted references | 0 / 261 |
| Unique verified spans | 117 |
| Full three-run status agreement | 17 / 30 (56.67%) |
| Full assertion-level agreement | 76 / 102 (74.51%) |
| Consolidated abstention (`unclear`) | 5 / 30 (16.67%) |

Micro Dramas had only 6/15 full-agreement criteria and six consolidated
`unclear` outcomes. Nine criteria changed status across runs. The Rush quality
guide had 11/15 full-agreement criteria; all three runs independently classified
`functional_requirements` and `rollout` as contradictory, while four other
criteria remained disputed.

The disagreement is not a citation problem: every quote verified and no run
submitted a duplicate evidence reference. It comes from semantic contract
variation:

- one run records an omitted assertion as a gap while another treats nearby
  prose as partial support;
- agents differ on whether tension is a contradiction, ambiguity, or scoped
  compatible rule;
- issue/evidence-set identities include model-authored claim shape, making
  semantically equivalent observations difficult to reconcile directly.

Forge now reconciles every required assertion by strict majority before deriving
the consolidated criterion status. Minority evidence and issues remain in the
audit, but one minority contradiction cannot dominate a criterion. This raised
the more granular agreement signal to 95.29% on the corpus and 74.51% on the
internal documents. It does not change the raw per-run criterion-status metric,
which remains the comparable 88%/56.67% baseline above.

## Initial Gate Decision

At the D-055 checkpoint, do not start Phase 3 generated question plans. Exact provenance and corpus
behavior are promising, but 56.67% full status agreement on the internal sample
is too unstable to make native `gap_id`s the source of user-facing questions.

The next validation slice should improve and adjudicate assertion/relation
agreement:

1. identify equivalent support sets by assertion plus verified evidence ids,
   not model-authored claim wording;
2. have blinded reviewers label the disputed internal criteria and the known
   proxy hard negatives before setting a Phase 3 threshold.

That hold required independent adjudication without losing the
gaming/placeholder hard-negative gains.

Forge now normalizes support-set identity from criterion/assertion, verified
evidence ids, role, and relation rather than model claim wording. Ambiguity
identity likewise excludes model-authored alternative phrasing. This changes
deduplication and reconciliation identity, not the measured status totals above.

Three prediction-free synthetic AI proxy sheets cover every assertion in both
internal documents:

- `sampleDoc/.forge/evaluation-ai-proxy-1.json`
- `sampleDoc/.forge/evaluation-ai-proxy-2.json`
- `sampleDoc/.forge/evaluation-ai-proxy-3.json`

They contain no Forge prediction, legacy/native status, criterion weight, or
gate. Reviewers select one assertion state and paste exact source quotes.
Disagreement remains contested unless a strict majority exists. The sheets are
permanently marked `synthetic_ai_proxy` and `calibration_eligible: false`.

All three agents completed 102 assertions independently. They unanimously agreed
on 79/102 (77.45%); strict-majority consensus exists for 100 assertions, while
two three-way splits remain unresolved. Native assertion outcomes exactly match
81/100 proxy consensus labels. The 19 differences are concentrated around the
boundary between structural support and semantic coherence: for example, the
Rush guide contains discrete requirements but also conflicting flag-off rules,
so proxies mark `requirements` supported and `decision_rules_and_precedence`
contradictory while native evaluation attaches conflict to both assertions.

## Updated Gate Decision

This D-058 proxy result is sufficient to start Phase 3 as a shadow engineering
prototype, not as validated product behavior. Generated questions may target
only strict-majority native assertion outcomes, must cite verified evidence ids,
and must fall back to rubric-owned text. They remain advisory and cannot affect
scores. Human validation remains required for any calibration or quality claim.

## Reproduction

```bash
uv run python spikes/run_corpus_evaluation_diagnostics.py
uv run python spikes/run_internal_evaluation_diagnostics.py
uv run python spikes/generate_evaluation_reviewer_sheets.py
uv run python spikes/evaluate_evaluation_reviewer_sheets.py
uv run python spikes/compare_evaluation_proxy_consensus.py
```

The committed corpus runs are under `fixtures/evaluation/`. Internal submissions
remain in ignored `sampleDoc/.forge/evaluation-shadow-run*.json`.
