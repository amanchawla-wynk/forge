# Forge Agent Instructions

Forge is a local-first MCP server that assesses whether a PRD is complete and
actionable. It uses the connected MCP client's LLM. It must never require,
store, or accept an LLM provider API key.

The one documented exception is the optional local dashboard
(`src/forge_dashboard/`, `web/`), which has no MCP client to borrow a model
from and therefore accepts a per-request, browser-held, never-persisted
bring-your-own-key for its own LiteLLM calls only. It is not installed by
default (`dashboard` extra) and never touches the MCP server or core domain
code. See `docs/DECISIONS.md` D-033 and `docs/ARCHITECTURE.md` "Dashboard Mode"
before changing anything in that boundary.

Before changing product behavior, architecture, scoring, or the MCP surface,
read these files in order:

1. `docs/PRODUCT.md`
2. `docs/SCORING_THEORY.md`
3. `docs/ARCHITECTURE.md`
4. `docs/DECISIONS.md`
5. `docs/ROADMAP.md`

## Working Rules

- Treat the documents above as the canonical project record.
- Update the relevant document in the same change whenever a decision,
  assumption, limitation, architecture boundary, or plan changes.
- Append material decisions to `docs/DECISIONS.md`; do not silently overwrite
  their history.
- Keep `docs/ROADMAP.md` synchronized with implemented and blocked work.
- Never add Anthropic, OpenAI, Bedrock, or other provider SDKs or API-key
  configuration. Inference comes from MCP sampling or an explicit agent-driven
  fallback workflow.
- The LLM extracts facts and evidence. Python validates evidence, derives
  verdicts, applies weights and gates, and selects the final band.
- Never let the LLM assign numeric scores or see criterion weights.
- A claimed field receives no credit unless its quote can be found in the
  normalized source document.
- Keep company-specific rubrics configurable and outside scoring code.
- Do not describe the generic `prd.v0.yaml` rubric as calibrated or final.
- Run `uv run pytest` before considering implementation work complete.

## Current Blockers

- Company PRD template and internal guidance are needed to tune the rubric.
- Real PRDs and human labels are needed to calibrate and validate it.
- Client compatibility must be tested because MCP sampling support varies by
  host. The fallback protocol must remain available for hosts without sampling.
