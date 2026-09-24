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

## Release Claim

Forge remains an `expert_baseline` unless the preregistered holdout thresholds
pass. Failed or underpowered studies are reported as such; they are not repaired
by removing difficult cases or changing thresholds after evaluation.
