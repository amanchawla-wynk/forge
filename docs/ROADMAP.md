# Roadmap

## Completed

- Established PRD-first scope and downstream-consumer readiness framing.
- Defined versioned rubric, criteria, fields, weights, gates, and bands.
- Implemented deterministic ternary verdict and scoring engine.
- Implemented per-consumer readiness and gate-aware remediation ordering.
- Added tests for gates, evidence requirement, placeholders, N/A handling,
  pessimistic run consolidation, and determinism.
- Chose client-borrowed LLM inference with no API-key functionality.
- Added canonical product, theory, architecture, decision, and roadmap records.
- Implemented PDF, DOCX, Markdown, and text normalization with evidence
  locations.
- Added exact normalized quote verification before evidence receives credit.
- Added prompt-injection boundaries that treat source documents as untrusted.
- Exposed native MCP sampling assessment and an agent-driven fallback protocol.
- Added an in-memory MCP integration test proving three sampling requests and
  model metadata capture.
- Added criterion-bound supplemental-answer provenance and stateless rescore
  inputs to native sampling and agent-driven fallback tools.
- Replaced the top-five response with one adaptive `next_question`; complete
  assessments return no question.
- Added a concise deterministic narrative report above the detailed assessment
  audit, including key gaps, blocked consumers, next step, and confidence note.

## Current Build

- Decide and test a chunking strategy for documents over 120,000 characters.
- Harden extraction validation against duplicate or unknown criterion fields.

## Next

- Test installation and behavior in Cursor and GitHub Copilot.
- Add evidence-linked structured gap records derived from failed rubric fields.
- Add qualitative risk records only where source evidence or a rubric omission
  supports them; do not invent probability or numeric risk scores.
- Add local session storage only if the stateless workflow proves cumbersome.

## Blocked On Company Inputs

- Tune terminology, criteria, weights, gates, and bands to the company PRD
  template and guidance.
- Build adversarial and representative fixtures from real PRDs.
- Create a multi-reviewer labelled calibration set.
- Set acceptable agreement and false-ready thresholds.

## Later

- Dashboard using the same core packages.
- Optional Excel workbook output adapter.
- Optional SharePoint publication adapter using caller-managed authentication.
- Optional remote MCP transport.
- BRD-specific theory and rubric.
- Separate rubrics and ingestion strategies for ARDs, user stories, API
  specifications, solution documents, and design artifacts.
- Rubric administration and version migration.
