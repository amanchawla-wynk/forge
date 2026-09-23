# Expert Baseline

Forge `0.4.0-expert-baseline` is a self-contained cross-industry PRD reviewer.
It converts published product, service, privacy, accessibility, and launch
guidance into atomic fields that an LLM extracts and Python verifies. It does
not copy external scoring weights and does not treat an online template as a
human quality label.

## Source Basis

| Source | Contribution to the rubric |
| --- | --- |
| [Atlassian PRD template](https://www.atlassian.com/software/confluence/templates/product-requirements) | Objectives, metrics, assumptions, prioritized requirements, open questions, ownership, and explicit scope. |
| [Shape Up: Write the Pitch](https://basecamp.com/shapeup/1.5-chapter-06) | Specific problem evidence, bounded scope, solution shape, rabbit holes, and no-gos, with worked examples from shipped projects. |
| [GOV.UK: Understand users and their needs](https://www.gov.uk/service-manual/service-standard/point-1-understand-user-needs) | Research evidence, prototypes, analytics, and explicit testing of assumptions. |
| [GOV.UK: Make sure everyone can use the service](https://www.gov.uk/service-manual/service-standard/point-5-make-sure-everyone-can-use-the-service) | Accessibility standards, inclusive research, and alternative access needs. |
| [GOV.UK: Create a secure service](https://www.gov.uk/service-manual/service-standard/point-9-create-a-secure-service) | Security and privacy risks, ownership, third parties, controls, and verification. |
| [GOV.UK: Define success](https://www.gov.uk/service-manual/service-standard/point-10-define-success-publish-performance-data) | Outcome measures, collection, review, and decision use. |
| [GOV.UK: Operate a reliable service](https://www.gov.uk/service-manual/service-standard/point-14-operate-a-reliable-service) | Monitoring, sustainable response, production-like testing, and user-outcome monitoring. |
| [Google SRE: Reliable Product Launches at Scale](https://sre.google/sre-book/reliable-product-launches/) | Dependency readiness, capacity, failure modes, staged rollout, verification, ownership, contingencies, and rollback. |
| [ICO data-protection principles](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/data-protection-principles/a-guide-to-the-data-protection-principles/) | Purpose-limited collection, data minimisation, retention, deletion, and lifecycle controls. |

Sources were reviewed on 2026-09-23. They establish an expert basis for what an
actionable PRD should contain; they do not establish organization-specific band
accuracy.

## Public Example Review

The research also considered reusable public examples from Wikimedia, OpenStack
Nova specifications, Kubernetes Enhancement Proposals, Opulo's PRD template,
and several MIT-licensed example repositories. These are useful regression and
format fixtures. None provides an independent human label saying whether the
document is a good PRD, and engineering workflow states such as `implemented`
or `approved` are not substitutes for that label.

Forge therefore uses public examples only for robustness diagnostics. The
calibration evaluator excludes `public` and `synthetic` cases from headline
model-to-human metrics.

## Operating Claim

The expert baseline can assess a PRD, explain verified gaps, and ask the next
highest-impact question without organization data. `ready_to_build` requires
every applicable criterion to be present. Lower bands remain weighted summaries
subject to critical gates.

`expert_baseline` means the rubric is grounded in explicit published standards.
It does not mean its thresholds have been validated against one organization's
reviewers. That stronger claim is reserved for `organization_validated` after a
representative, independently labelled internal corpus meets agreed accuracy
and false-ready thresholds.
