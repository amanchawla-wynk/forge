# Minimal Architecture for Evidence-Backed Contradiction and Ambiguity Review

Research current through 2026-09-25. This proposal is intentionally advisory: findings cannot change readiness verdicts, points, gates, or bands until a separate versioned and validated policy says otherwise.

## How should multiple claims across batches and runs be retained and reconciled?

### Takeaway

Add an immutable, source-span-first claim ledger between extraction verification and the existing field/verdict consolidation. Preserve every verified source occurrence and attach each run's structured interpretation to it; reconcile interpretations for analysis without deleting minority claims or changing the current deterministic scoring path.

### Cited Findings

- Forge currently verifies every batch fragment, then `_consolidate_fragments` selects the first satisfied candidate for each rubric field and discards later satisfied candidates. This is the exact representation-loss point for cross-section analysis. — [Forge batch extraction](../../src/forge/extract/batch.py#L242-L295)
- The score engine later selects the first run that produced the modal criterion verdict and exposes only that run's missing and satisfied fields. This behavior is appropriate for the existing score but cannot represent conflicting statements found by other runs. — [Forge scoring engine](../../src/forge/score/engine.py#L100-L153)
- Existing evidence already carries section, page, provenance, block identity, parent block identity, and chunk offsets after quote verification. — [Forge extraction models](../../src/forge/extract/models.py#L17-L41); [Forge verifier](../../src/forge/extract/batch.py#L73-L132)
- `NormalizedDocument.locate_quote` normalizes case and whitespace and returns the first block containing a quote. Repeated identical text is therefore not uniquely located by the present quote-only lookup. — [Forge ingestion model](../../src/forge/ingest/models.py#L89-L96)
- Forge requires exhaustive batching: every prepared batch must be submitted, duplicate or unknown batch ids are rejected, and fragments are bound to a plan fingerprint and optional unique run indexes. — [Forge batch verification](../../src/forge/extract/batch.py#L27-L70); [Forge plan and run validation](../../src/forge/extract/batch.py#L135-L197)
- Forge's architecture already specifies verified claims carrying exact quote, source location, scope, phase, modality, and extraction-run identity, while keeping the graph advisory and exhaustive batching authoritative. — [Forge architecture](../../docs/ARCHITECTURE.md#components)
- ContractNLI is an actionable precedent for document-level inference that jointly classifies a closed relation (`entailed`, `contradicting`, or `not mentioned`) and identifies evidence spans; its baseline treats evidence identification as classification over spans and explicitly addresses long-document segmentation. — [ContractNLI](https://aclanthology.org/2021.findings-emnlp.164/)
- FEVER similarly separates a three-way claim decision (`Supported`, `Refuted`, `NotEnoughInfo`) from the sentence evidence needed for supported or refuted labels, demonstrating that label accuracy alone is not an evidence-grounded evaluation. — [FEVER](https://aclanthology.org/N18-1074/)

### Inferences

#### Minimal ledger

- Introduce `ClaimLedger` as an additional verified artifact returned by full extraction, not as a replacement for `ExtractionRun`. The existing consolidated runs continue unchanged into `score()`, while deep review consumes the ledger. This preserves D-005 and D-045's separation between advisory analysis and score authority. — [D-005 and D-045](../../docs/DECISIONS.md#d-045-make-evidence-backed-deep-review-the-primary-experience); [Forge scoring theory](../../docs/SCORING_THEORY.md#extraction-before-judgment)
- Use two levels rather than treating each model extraction as a new fact:
  - `ClaimOccurrence`: one uniquely located source assertion.
  - `ClaimInterpretation`: one run's typed parse of that occurrence.
  This avoids multiplying a source statement by the number of runs while retaining disagreement about its meaning. — [Forge repeated-extraction policy](../../docs/SCORING_THEORY.md#repeated-extraction-and-confidence); [ContractNLI](https://aclanthology.org/2021.findings-emnlp.164/)
- A minimal `ClaimOccurrence` should contain `claim_id`, `source_sha256`, `source_block_id`, `source_parent_block_id`, quote-local `start_char` and `end_char`, exact `quote`, page, section, provenance, and all `(batch_id, run_index, criterion_id, field_name)` observations. Add quote-local offsets because the current source offsets identify a split block's range in its parent, not the quote's range inside that block, and first-match lookup cannot distinguish repeated text. — [Forge evidence fields](../../src/forge/extract/models.py#L17-L27); [Forge block splitting](../../src/forge/ingest/batching.py#L59-L87); [Forge quote lookup](../../src/forge/ingest/models.py#L89-L96)
- A minimal `ClaimInterpretation` should contain only bounded attributes needed for pairing: `claim_kind`, `subject_key`, `property_key`, `object_text`, `polarity`, `modality`, `scope` (actor, product/feature, platform, segment, locale), `phase`, `conditions`, and optional typed value (`number`, `unit`, `comparator`, `lower`, `upper`, `date`, `duration`, or `cadence`). Every non-enum string must be either an exact substring of the verified quote or a deterministic normalization of it. — [Forge exact-evidence rule](../../docs/SCORING_THEORY.md#evidence-rule); [ContractNLI](https://aclanthology.org/2021.findings-emnlp.164/)
- Compute `claim_id` from source identity plus the unique source span, not from model wording: for example, `sha256(source_sha256 || block_id || quote_start || quote_end || quote)`. A repeated sentence in two sections remains two occurrences; repeated extraction of the same span across runs maps to one occurrence. — [Forge plan fingerprint pattern](../../src/forge/ingest/batching.py#L97-L115); [Forge architecture](../../docs/ARCHITECTURE.md#components)

#### Reconciliation algorithm

- Verify and flatten all fragments before score-oriented `_consolidate_fragments`; never reconstruct the ledger from its first-candidate output. Group exact observations by verified source span, then retain all distinct spans even when normalized text is identical. — [Forge first-candidate consolidation](../../src/forge/extract/batch.py#L242-L295); [D-045](../../docs/DECISIONS.md#d-045-make-evidence-backed-deep-review-the-primary-experience)
- Consolidate each interpretation attribute independently by modal value across distinct run indexes. A tie or missing majority becomes `unknown`; preserve the observed alternatives and per-attribute agreement. Do not pessimistically turn a parse tie into a contradiction, and do not let majority reconciliation erase the underlying source occurrence. — [Forge modal-verdict precedent](../../docs/SCORING_THEORY.md#repeated-extraction-and-confidence); [Forge edge-ledger consolidation](../../src/forge/score/edge_coverage.py#L254-L284)
- Merge two different source spans only at the graph-relation layer (`restates`, `equivalent_to`, or `possibly_same_subject`), never in ledger storage. Exact deterministic aliases may link automatically; semantic alias or coreference requires a constrained `same`, `different`, or `unclear` classification. — [Forge non-evidence context boundary](../../docs/SCORING_THEORY.md#remediation); [HANS shortcut findings](https://aclanthology.org/P19-1334/)
- Retain `not_applicable` as an extraction observation, not a claim occurrence, unless its reason is itself a uniquely verified source span. Existing verification already rejects unlocatable reasons. — [Forge batch verifier](../../src/forge/extract/batch.py#L73-L85)
- Bind a ledger to `source_sha256`, rubric id/version, claim-schema version, extraction-plan fingerprint, and run identities. Any source or schema change requires complete re-extraction; checkpoint answers may add separately provenanced claims only within their criterion, following the current supplemental-evidence boundary. — [Forge checkpoint policy](../../docs/SCORING_THEORY.md#remediation); [Forge architecture](../../docs/ARCHITECTURE.md#components)

### Gaps

- The current extractor emits one value and one field-level citation, so it cannot yet enumerate all claims in a block or uniquely locate repeated quotes. A claim-oriented extraction schema and span-bound verifier are prerequisite implementation work. — [Forge extraction prompt](../../src/forge/extract/prompt.py#L39-L57); [Forge quote lookup](../../src/forge/ingest/models.py#L89-L96)
- Product-specific alias dictionaries and scope vocabularies are not validated. They should begin as versioned expert-prior configuration, and product context must remain non-evidence. — [D-029](../../docs/DECISIONS.md#d-029-keep-implementation-context-outside-prd-evidence)

## Which contradiction types can be detected deterministically and which require constrained semantic classification?

### Takeaway

Python should generate and decide only mechanically provable conflicts over typed claims. All paraphrase, referent, scope-overlap, exception, precedence-intent, staleness, and ambiguity judgments should be exhaustive closed-set classifications over pre-enumerated, quote-verified candidates; invalid, disputed, or incomplete outputs become `unclear`, not findings.

### Cited Findings

- Forge already uses the safe pattern needed here: deterministic requirement/taxonomy pairing, closed four-state model classification, exact evidence verification, complete-pair validation, modal consolidation, and pessimistic handling of unsupported positive claims. — [D-038](../../docs/DECISIONS.md#d-038-score-edge-cases-from-a-versioned-coverage-ledger); [Edge coverage implementation](../../src/forge/score/edge_coverage.py#L137-L189)
- Forge's framing and contextualization tools permit only an integer choice among predeclared options and mechanically discard malformed, extra-keyed, or out-of-range model output. — [Forge scoring theory](../../docs/SCORING_THEORY.md#remediation); [D-035](../../docs/DECISIONS.md#d-035-guardrailed-closed-set-contextualization-of-remediation-questions)
- NLI convention supplies a useful but insufficient three-way relation: entailment, contradiction, or neutral/not-mentioned. MultiNLI also shows that cross-genre inference is materially harder than a single-genre benchmark despite similar annotator agreement. — [MultiNLI](https://aclanthology.org/N18-1101/); [ContractNLI](https://aclanthology.org/2021.findings-emnlp.164/)
- HANS demonstrates that strong NLI models can rely on fallible lexical-overlap, subsequence, and constituent heuristics and perform poorly on controlled counterexamples. Candidate lexical overlap must therefore never be accepted as proof of contradiction or equivalence. — [HANS](https://aclanthology.org/P19-1334/)
- Forge's target finding classes already include contradictions, precedence conflicts, undefined boundaries, stale requirements, and non-testable formulas, while its roadmap names impossible ranges, conflicting timelines, and metrics that cannot be computed from specified events. — [Forge architecture](../../docs/ARCHITECTURE.md#components); [Forge roadmap](../../docs/ROADMAP.md#current-build)

### Inferences

#### Bounded requirement graph

- Build one in-memory graph per source document with no embeddings or retrieval store. Claim nodes link to typed nodes for `entity`, `requirement`, `state`, `metric`, `event`, `dependency`, `milestone`, `definition`, and `section`. Minimal edge types are `asserts`, `applies_to`, `during_phase`, `conditioned_by`, `measures`, `computed_from`, `depends_on`, `precedes`, `overrides`, `supersedes`, `defines`, `excepts`, and `possibly_same_subject`. — [Forge bounded-graph decision](../../docs/ARCHITECTURE.md#components); [D-045](../../docs/DECISIONS.md#d-045-make-evidence-backed-deep-review-the-primary-experience)
- Use typed indexes to avoid an all-pairs graph: pair only claims sharing a deterministic subject/property key, normalized metric/event identifier, dependency, milestone, or explicit cross-reference. Add adjacency pairs for explicit precedence/supersession language. The graph discovers candidates but never controls evidence eligibility or scoring. — [Forge architecture](../../docs/ARCHITECTURE.md#components); [Forge exhaustive evidence rule](../../docs/SCORING_THEORY.md#evidence-rule)

#### Deterministic findings

- Python may emit `deterministic_confirmed` only when compatible scope, phase, and conditions are themselves exact typed matches and one of these proofs holds:
  - opposite explicit polarity for the same normative proposition;
  - disjoint exact numeric values or ranges after unit normalization;
  - an internally impossible range (`lower > upper`) or impossible duration/cadence arithmetic;
  - incompatible exact dates for the same milestone, or a required precedence cycle;
  - two exact definitions of the same identifier with disjoint literal values;
  - a broken explicit reference, missing formula operand, duplicate precedence rank, or graph cycle;
  - an explicit `supersedes`/`deprecated` marker whose older claim is still referenced as active.
  These are mechanical consequences of verified typed values, not free-text judgments. — [Forge objective-constraint precedent](../../docs/SCORING_THEORY.md#evidence-rule); [D-023](../../docs/DECISIONS.md#d-023-permit-objective-field-constraints-in-rubrics)
- If scope compatibility, unit conversion, temporal interpretation, or referent identity is not mechanically established, the deterministic rule may create a candidate but must not confirm a finding. — [Forge rule that unsupported claims receive no credit](../../docs/SCORING_THEORY.md#evidence-rule); [HANS](https://aclanthology.org/P19-1334/)

#### Constrained semantic tasks

- Task 1, claim atomization: for every source block, return zero or more atoms using the fixed claim schema, exact quote substrings, and enum values. Require every block id exactly once across the complete extraction plan. This is extraction, not finding judgment. — [Forge exhaustive batching](../../docs/SCORING_THEORY.md#evidence-rule); [ContractNLI evidence-span approach](https://aclanthology.org/2021.findings-emnlp.164/)
- Task 2, identity resolution: for each deterministic alias/coreference candidate, return exactly `{candidate_id, relation}` where relation is `same`, `different`, or `unclear`. Python verifies ids and applies only `same` edges supported by the consolidated result. — [Forge closed-output precedent](../../docs/SCORING_THEORY.md#remediation); [HANS](https://aclanthology.org/P19-1334/)
- Task 3, pair classification: for every precomputed pair, return exactly `{candidate_id, relation, contradiction_type}`. `relation` is one of `contradiction`, `compatible`, `scoped_exception`, `supersedes`, `duplicate`, or `unclear`; `contradiction_type` is a versioned enum or `none`. The model cannot provide prose, evidence, severity, consumers, consequence, or score effect. — [ContractNLI](https://aclanthology.org/2021.findings-emnlp.164/); [Forge closed-output precedent](../../docs/SCORING_THEORY.md#remediation)
- Task 4, ambiguity classification: for every deterministic unary or subgraph candidate, return exactly `{candidate_id, ambiguity_type}` where the options are `undefined_term`, `missing_boundary`, `unresolved_precedence`, `missing_fallback`, `incomplete_formula`, `stale_status`, `not_ambiguous`, or `unclear`. Python renders all user-facing language from versioned templates. — [D-035](../../docs/DECISIONS.md#d-035-guardrailed-closed-set-contextualization-of-remediation-questions); [D-045](../../docs/DECISIONS.md#d-045-make-evidence-backed-deep-review-the-primary-experience)
- Semantic-only classes include paraphrased contradiction, same-referent resolution, overlapping but differently worded scopes, whether one statement is an exception, implied precedence, suspected staleness without an explicit marker, undefined behavioral boundaries, and whether a metric is semantically computable from named events. — [Forge roadmap](../../docs/ROADMAP.md#current-build); [ContractNLI](https://aclanthology.org/2021.findings-emnlp.164/)

#### Exhaustive verification pipeline

- Fingerprint the candidate plan over source hash, claim-schema/taxonomy versions, ordered candidate ids, and exact claim spans. Batch by candidate count or prompt size, but require every candidate exactly once in every run; reject missing, duplicate, unknown, stale, or mixed-run results. — [Forge extraction-plan controls](../../src/forge/extract/batch.py#L27-L70); [Forge plan fingerprint](../../src/forge/ingest/batching.py#L97-L115)
- Run semantic tasks three times per fixed client/model configuration. Consolidate each candidate by modal label; ties, malformed responses, missing responses, and positive-label disagreement resolve to `unclear`. Unlike readiness's pessimistic verdict tie-break, this conservative publication rule minimizes false accusations while retaining disagreement in audit data. — [Forge repeated extraction](../../docs/SCORING_THEORY.md#repeated-extraction-and-confidence); [Forge edge consolidation](../../src/forge/score/edge_coverage.py#L254-L284)
- Before publication, Python must reverify both source spans against the specified block and offsets, validate candidate membership and allowed type combinations, recompute every deterministic proof, merge duplicate findings by canonical claim set plus type, and retain model/client/run metadata and agreement. No model-authored text reaches the user. — [Forge trust boundaries](../../docs/ARCHITECTURE.md#trust-boundaries); [D-035](../../docs/DECISIONS.md#d-035-guardrailed-closed-set-contextualization-of-remediation-questions)
- Generate `implementation_consequence` and `required_author_decision` from versioned templates keyed by finding type and graph role, populated only with verified quotes, typed values, and configured consumer names. If no safe template applies, expose the evidence and type without generated explanation. — [Forge deterministic-report policy](../../docs/SCORING_THEORY.md#output-restraint); [D-045](../../docs/DECISIONS.md#d-045-make-evidence-backed-deep-review-the-primary-experience)

### Gaps

- Generic NLI corpora do not validate PRD-specific relation types, scope semantics, or priority. MultiNLI's genre result and ContractNLI's reported difficulty argue for a PRD-specific labelled holdout rather than assuming transfer. — [MultiNLI](https://aclanthology.org/N18-1101/); [ContractNLI](https://aclanthology.org/2021.findings-emnlp.164/)
- Deterministic unit conversion and date parsing need a deliberately small supported-unit policy. Unsupported units should create `unclear` candidates, not guessed conversions. — [Forge objective-constraint policy](../../docs/SCORING_THEORY.md#evidence-rule)

## How should severity and priority be represented before calibration?

### Takeaway

Do not emit numeric risk, probability, impact, or conventional `high/medium/low` severity. Store auditable priority signals separately from confidence, then sort by a versioned expert-prior tuple labelled as review order, not calibrated risk.

### Cited Findings

- Forge explicitly rejects generated category percentages, severity labels, probability estimates, rework estimates, and defect-leakage predictions without definitions, evidence rules, and calibration. — [Forge scoring theory](../../docs/SCORING_THEORY.md#output-restraint)
- Forge is advisory rather than an approval gate and does not make predictive risk claims. — [D-003](../../docs/DECISIONS.md#d-003-advisory-not-approval-gate); [D-012](../../docs/DECISIONS.md#d-012-remain-advisory-and-avoid-predictive-claims)
- Existing remediation ordering is a transparent tuple: failed gate, criterion weight, number of downstream consumers, then stable id. — [Forge scoring theory](../../docs/SCORING_THEORY.md#remediation)
- D-045 requires each deep-review finding to cite verified locations, explain implementation consequence, state the required author decision, and remain outside the score until precision, recall, priority usefulness, and false-positive behavior are validated. — [D-045](../../docs/DECISIONS.md#d-045-make-evidence-backed-deep-review-the-primary-experience)

### Inferences

#### Pre-calibration representation

- Keep three independent concepts:
  - `verification_status`: `deterministic_confirmed`, `model_consensus`, or `unclear`;
  - `implementation_effect`: one or more descriptive enums such as `mutually_exclusive_behavior`, `unimplementable_constraint`, `undefined_precedence`, `non_testable_outcome`, `missing_operational_behavior`, or `documentation_staleness`;
  - `priority_signals`: mechanically derived fields such as affected consumer enums, affected requirement count, cross-section flag, normative-modality flag, launch/rollout scope, failed-gate overlap, and classifier agreement.
  Confidence must never substitute for impact, and gate overlap may order review without altering the gate or score. — [Forge confidence policy](../../docs/SCORING_THEORY.md#repeated-extraction-and-confidence); [Forge output restraint](../../docs/SCORING_THEORY.md#output-restraint)
- Sort with a versioned `review_order_policy`, for example: deterministic impossibility before model consensus; mutually exclusive normative behavior before missing clarification; failed-gate overlap; number of affected consumers; cross-section before same-section; stable finding id. Expose the tuple and policy version. Call the result `review_order`, not `severity`, `risk`, or `priority score`. — [Forge existing transparent ordering](../../docs/SCORING_THEORY.md#remediation); [D-012](../../docs/DECISIONS.md#d-012-remain-advisory-and-avoid-predictive-claims)
- `unclear` candidates belong in a separate “needs reviewer confirmation” list and should not outrank verified findings merely because the model is uncertain. — [Forge unsupported-positive downgrade](../../src/forge/score/edge_coverage.py#L137-L189); [Forge advisory posture](../../docs/PRODUCT.md#purpose)

#### Minimal finding schema

```yaml
finding_id: string                 # deterministic digest
analysis_version: string
candidate_id: string
finding_type: enum                 # versioned contradiction/ambiguity taxonomy
verification_status: deterministic_confirmed | model_consensus | unclear
claim_ids: [string]                # one for unary ambiguity, usually two for conflict
evidence:
  - claim_id: string
    quote: string
    source_block_id: string
    start_char: integer
    end_char: integer
    page: integer | null
    section: string | null
scope_relation: exact | overlapping | disjoint | unclear
implementation_effects: [enum]
affected_consumers: [enum]
implementation_consequence:
  template_id: string
  rendered: string
required_author_decision:
  template_id: string
  rendered: string
priority_signals:
  deterministic_impossibility: boolean
  normative_conflict: boolean
  failed_gate_overlap: boolean
  cross_section: boolean
  affected_requirement_count: integer
review_order_policy: string
review_order: integer
classification:
  run_count: integer
  agreement: number
  observed_labels: {label: count}
  client_model_metadata: [object]
provenance:
  source_sha256: string
  plan_fingerprint: string
  claim_schema_version: string
  taxonomy_version: string
advisory: true
score_effect: none
```

- Every rendered consequence and decision must come from a source-controlled template, with substitutions restricted to verified evidence and fixed enums. The structured fields remain authoritative if rendering changes. — [Forge deterministic-report policy](../../docs/SCORING_THEORY.md#output-restraint); [D-035](../../docs/DECISIONS.md#d-035-guardrailed-closed-set-contextualization-of-remediation-questions)
- Keep a `ConsistencyLedger` containing every candidate, including compatible, non-ambiguous, unclear, and rejected entries, plus verification failures. `findings` are only a deterministic projection of publishable ledger rows. This makes exhaustive processing and false-negative analysis auditable. — [Forge edge-ledger precedent](../../src/forge/score/edge_coverage.py#L114-L189); [D-038](../../docs/DECISIONS.md#d-038-score-edge-cases-from-a-versioned-coverage-ledger)

### Gaps

- No evidence yet supports a calibrated severity scale, risk probability, business-impact weight, or universal ordering among contradiction types. Those values require independent labels and a new versioned decision, not inference from wording. — [Forge validation protocol](../../docs/VALIDATION_PROTOCOL.md#preregistration); [D-045](../../docs/DECISIONS.md#d-045-make-evidence-backed-deep-review-the-primary-experience)
- Consumer impact templates will need review by engineering, design, QA, data, risk, leadership, and go-to-market users; rubric consumer mappings alone do not prove that a specific contradiction blocks a role. — [Forge product users](../../docs/PRODUCT.md#users); [Forge scoring theory](../../docs/SCORING_THEORY.md#claim-being-measured)

## What golden-case and human-label metrics should validate the feature?

### Takeaway

Evaluate the pipeline in layers: exhaustive claim/span extraction, candidate-generation recall, conditional classification, and end-to-end finding quality. Use authored golden and metamorphic cases for deterministic guarantees, then blinded multi-reviewer internal PRDs and a frozen holdout for precision, recall, priority usefulness, and actionability.

### Cited Findings

- Forge's current protocol preregisters rubric/version, configurations, development and holdout ids, sample minimums, error thresholds, agreement thresholds, and adjudication policy before viewing holdout results. It requires representative internal PRDs and blinded independent review. — [Forge validation protocol](../../docs/VALIDATION_PROTOCOL.md#preregistration); [Forge validation protocol](../../docs/VALIDATION_PROTOCOL.md#dataset); [Forge validation protocol](../../docs/VALIDATION_PROTOCOL.md#review)
- Public and synthetic documents are robustness diagnostics, not calibration truth; internal human labels are required for organization-validity claims. — [Forge scoring theory](../../docs/SCORING_THEORY.md#expert-baseline); [Forge validation protocol](../../docs/VALIDATION_PROTOCOL.md#release-claim)
- Forge's roadmap already designates the MicroDrama recommendations PRD as a human-reviewed golden case for finding precision, recall, quote correctness, duplicate rate, priority agreement, and actionability. — [Forge roadmap](../../docs/ROADMAP.md#current-build)
- The known MicroDrama defects include incompatible skip thresholds, an impossible interval, conflicting mood-picker state/frequency rules, inconsistent launch timelines, and unclear ranking precedence. — [D-045](../../docs/DECISIONS.md#d-045-make-evidence-backed-deep-review-the-primary-experience)
- CheckList shows why aggregate held-out accuracy is insufficient and advocates a matrix of linguistic capabilities and test types; controlled behavioral cases exposed failures in extensively tested NLP systems. — [CheckList](https://aclanthology.org/2020.acl-main.442/)
- HANS shows that controlled counterexamples are necessary to detect lexical-overlap, subsequence, and constituent shortcuts that ordinary aggregate NLI tests can miss. — [HANS](https://aclanthology.org/P19-1334/)
- FEVER jointly reports claim labels and required evidence and observed only moderate annotator agreement (`Fleiss kappa = 0.6841`) in its task, reinforcing the need to report reviewer disagreement rather than silently force consensus. — [FEVER](https://aclanthology.org/N18-1074/)

### Inferences

#### Golden and behavioral suite

- Build gold annotations at the source-span and candidate level, not only as a list of prose findings. Each case should declare all claim spans, all applicable candidate pairs, accepted finding type, acceptable evidence sets, and intentional non-findings. This permits separate measurement of missed candidates and classifier errors. — [ContractNLI evidence-span design](https://aclanthology.org/2021.findings-emnlp.164/); [FEVER](https://aclanthology.org/N18-1074/)
- Start with the five known MicroDrama defects, add human-confirmed true negatives that share vocabulary, and add a multi-batch variant where each half of a contradiction is in a different batch. The full set must also include same-section conflicts, cross-section paraphrases, scoped exceptions, explicit supersession, legitimate alternatives, repeated identical quotes, tables, supplemental answers, and unsupported units. — [D-045 known defects](../../docs/DECISIONS.md#d-045-make-evidence-backed-deep-review-the-primary-experience); [Forge representative-data requirements](../../docs/VALIDATION_PROTOCOL.md#dataset)
- Add metamorphic transformations with expected invariants: reorder sections; alter batch boundaries; duplicate a non-authoritative paragraph; change names through a declared alias; negate one claim; change one number or unit; add an explicit scope exception; add an explicit supersession statement; inject instructions into PRD text. These test sensitivity where intended and invariance otherwise. — [Forge current adversarial invariants](../../docs/SCORING_THEORY.md#regression-corpus); [CheckList](https://aclanthology.org/2020.acl-main.442/); [HANS](https://aclanthology.org/P19-1334/)

#### Machine metrics

- Claim layer: source-block coverage, gold claim-span recall, exact-span precision/recall/F1, quote-verification pass rate, and claim deduplication error. Report repeated-text and cross-batch slices separately. — [Forge exhaustive evidence rule](../../docs/SCORING_THEORY.md#evidence-rule); [ContractNLI](https://aclanthology.org/2021.findings-emnlp.164/)
- Candidate layer: oracle candidate recall overall and by finding type, candidates per claim, pair-reduction ratio versus all-pairs, and exhaustive-processing rate. Candidate recall is a release gate because no classifier can recover a pair the deterministic generator omitted. — [Forge exhaustive batching requirement](../../docs/SCORING_THEORY.md#evidence-rule); [Forge roadmap candidate types](../../docs/ROADMAP.md#current-build)
- Classifier layer, conditioned on gold candidates: per-type precision, recall, and F1; macro-F1 for rare types; confusion matrix including `compatible` and `unclear`; positive predictive value; false-positive rate over labelled negative candidates; abstention/unclear rate; and three-run agreement. Report deterministic and semantic strata separately. — [ContractNLI three-way classification](https://aclanthology.org/2021.findings-emnlp.164/); [Forge repeated-run policy](../../docs/SCORING_THEORY.md#repeated-extraction-and-confidence)
- End-to-end layer: finding-level micro and macro precision/recall/F1, where a match requires compatible type and the canonical gold claim-span set; exact quote/location correctness; evidence-set precision/recall; duplicate finding rate; false-positive findings per PRD; missed implementation-blocker rate; and complete-ledger processing rate. — [FEVER evidence-plus-label design](https://aclanthology.org/N18-1074/); [D-045 evaluation requirements](../../docs/DECISIONS.md#d-045-make-evidence-backed-deep-review-the-primary-experience)
- Robustness layer: finding-set Jaccard stability across repeated runs and supported client/models, invariance under section reorder and batch-boundary changes, sensitivity to controlled negation/numeric changes, prompt-injection resistance, and latency/token/candidate counts by document length. Do not pool client/model configurations before cross-client comparability is established. — [Forge cross-client policy](../../docs/SCORING_THEORY.md#repeated-extraction-and-confidence); [Forge regression corpus](../../docs/SCORING_THEORY.md#regression-corpus)

#### Human-label study

- Use at least two blinded reviewers per PRD and three where role disagreement matters. Reviewers should first mark findings independently, then adjudicate only for a separate resolved gold set; preserve individual labels and contested items. — [Forge validation protocol](../../docs/VALIDATION_PROTOCOL.md#review); [Forge calibration consensus policy](../../src/forge/calibration.py#L213-L300)
- Label each proposed and missed finding on: existence (`valid`, `not_valid`, `unclear`), type, exact supporting spans, affected consumers, whether the consequence is accurate, whether the requested author decision is specific/actionable, and relative review priority. Include a candidate-free pass in which reviewers may add missed findings, otherwise recall is unknowable. — [D-045 required finding content](../../docs/DECISIONS.md#d-045-make-evidence-backed-deep-review-the-primary-experience); [Forge remediation outcome study](../../docs/VALIDATION_PROTOCOL.md#remediation-outcome-study)
- Report inter-reviewer agreement for existence and type, evidence-span agreement, contested-item rate, and role-stratified disagreement. For priority, collect pairwise preference or an ordered list and report pairwise agreement plus rank correlation/top-k overlap against resolved reviewer order; do not manufacture numeric severity labels. — [Forge policy to expose contested labels](../../docs/SCORING_THEORY.md#validation-plan); [Forge rejection of uncalibrated severity](../../docs/SCORING_THEORY.md#output-restraint)
- Report majority-rated consequence correctness and author-decision actionability as separate proportions, with reviewer-role slices and confidence intervals. In a remediation study, measure remaining clarification questions and downstream ability to act on the revised artifact; Forge score movement remains secondary. — [Forge validation protocol](../../docs/VALIDATION_PROTOCOL.md#remediation-outcome-study)
- Preregister separate development and holdout PRDs, minimum sample sizes, per-type and overall acceptance thresholds, maximum false-positive findings per PRD, minimum candidate recall, minimum evidence correctness, maximum duplicate rate, minimum priority agreement, and the treatment of contested labels. A taxonomy, claim-schema, candidate-rule, template, or ordering-policy change creates a new analysis version and holdout evaluation. — [Forge preregistration policy](../../docs/VALIDATION_PROTOCOL.md#preregistration); [Forge release claim](../../docs/VALIDATION_PROTOCOL.md#release-claim)

### Gaps

- No representative labelled PRD corpus or acceptable thresholds currently exist, so this feature can only claim an expert-prior advisory status at launch. Thresholds must be preregistered from development data and stakeholder tolerance, not invented in this architecture note. — [Forge blocked inputs](../../docs/ROADMAP.md#blocked-on-company-inputs); [Forge validation protocol](../../docs/VALIDATION_PROTOCOL.md#release-claim)
- The MicroDrama case alone cannot estimate generalization, rare-type recall, cross-team behavior, or client/model variance. It is a golden regression anchor, not calibration evidence. — [Forge expert-baseline limitation](../../docs/SCORING_THEORY.md#expert-baseline); [Forge validation dataset requirements](../../docs/VALIDATION_PROTOCOL.md#dataset)
