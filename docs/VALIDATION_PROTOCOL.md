# Forge Validation Protocol

## Purpose

This protocol tests whether a fixed Forge rubric predicts independent human
judgments and whether remediation improves the durable PRD. It does not treat
public templates, synthetic documents, Forge score movement, or reviewer
workshops as calibration truth.

## Preregistration

Before evaluating holdout cases, record:

- the exact rubric id and version;
- supported client, model, and ingestion configurations;
- development and holdout case ids;
- minimum resolved-case count;
- maximum false-ready rate;
- minimum band agreement;
- maximum mean ordinal band distance;
- minimum inter-reviewer agreement;
- the adjudication policy for contested labels.

Store thresholds as `ValidationThresholds` JSON and do not revise them after
viewing holdout results. A material rubric change creates a new version and a
new holdout evaluation.

## Dataset

Use representative internal PRDs spanning readiness bands, product framings,
teams, risk levels, lengths, and supported formats. Include polished but hollow
documents, legitimate not-applicable cases, multi-batch documents, and documents
whose important evidence appears in tables, headers, footers, or visuals.

Assign every `CalibrationCase.study_split` before labels are merged. Public and
synthetic cases remain robustness diagnostics and never enter headline metrics.

## Review

Use at least two blinded reviewers per case and three where role disagreement is
material. Reviewers see the source PRD and rubric standards, but not Forge's
prediction, weights, gates, or another reviewer's labels. Ties remain contested.

Create sheets with `forge-calibration template`, merge completed sheets with
`forge-calibration merge`, and evaluate only the frozen holdout with:

```bash
forge-calibration evaluate suite.json --holdout-only --thresholds thresholds.json
```

## Remediation Outcome Study

Measure a draft before remediation, materialize the approved revised copy, and
have downstream reviewers assess that copy without conversational evidence.
Primary outcomes are human readiness, remaining clarification questions, and
role-specific ability to act. Forge score movement is secondary because it is
not independent evidence of usefulness.

Record completion, abandonment, checkpoint count, extraction failures, token
and latency use, unresolved contradictions, and the difference between the
conversational assessment and final artifact assessment.

## Deep-Review Finding Study

Evaluate D-045 findings separately from readiness calibration. Before reviewers
see Forge output, create one blinded sheet per reviewer with
`forge-review-eval template`. Reviewers record each implementation-blocking or
material defect using exact source fragments; they may identify the expected
finding kind, but taxonomy knowledge is not required. Use at least two distinct
reviewers per internal case.

After labels are fixed, create the prediction case with `forge-review-eval
case`, merge sheets with `forge-review-eval merge`, and evaluate the frozen
holdout with:

```bash
forge-review-eval evaluate golden-suite.json --holdout-only \
  --thresholds review-thresholds.json
```

Preregister the minimum internal case count, minimum precision, minimum blocker
recall, maximum false positives per case, and minimum inter-reviewer agreement.
Do not infer accuracy from public or synthetic examples. They remain useful for
failure-mode development but are excluded from headline metrics. A finding
recorded by only half or fewer reviewers remains contested and cannot enter
consensus recall. Undefined metrics fail threshold checks rather than passing by
absence of evidence.

Human quote alignment is not source verification: it reports whether a
prediction cited the same text reviewers used to identify a defect. Forge's
normal source verifier remains responsible for proving that every published
quote occurs in the normalized document. Priority agreement and actionability
require a second, post-prediction reviewer pass and are not claimed by the
initial blinded-discovery evaluator.

## Public-Guidance Proxy Panels

When independent reviewers are unavailable, separate AI agents may review a PRD
through different public first-party source families. Record these as synthetic
proxy diagnostics, never as human labels. The artifact must use
`forge.synthetic_public_guidance_proxy_panel.v1`, retain exact verified source
spans, preserve hard negatives and disagreements, and set human review,
organization validation, calibration eligibility, and headline eligibility to
false. Individual labels remain advisory with no score effect.

Proxy agreement may justify content-validity hypotheses, generic field wording,
anchored examples, adversarial fixtures, and transfer tests. It cannot justify
weights, gates, bands, calibrated severity, acceptance thresholds, legal or
accessibility conformance, or a claim that the cited companies endorse the
rubric. A rubric field added from proxy evidence advances the expert-baseline
version and must preserve this limitation in the decision log.

## Release Claim

Forge remains an `expert_baseline` unless the preregistered holdout thresholds
pass. Failed or underpowered studies are reported as such; they are not repaired
by removing difficult cases or changing thresholds after evaluation.
