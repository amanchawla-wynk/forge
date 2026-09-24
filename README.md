# Forge

Forge is a local MCP server that checks whether a PRD is complete and
actionable for its downstream consumers. It borrows the connected MCP client's
LLM and never requires an LLM provider API key.

The bundled rubric is a source-backed cross-industry expert baseline. It works
without company data and returns evidence-based bands and questions immediately.
Its output identifies that basis explicitly; organization-specific validation
still requires independent labels from the organization's own reviewers.

## Current Tools

- `assess_prd`: three extraction runs using MCP client sampling, followed by
  evidence verification, deterministic scoring, a concise narrative report,
  and one `next_question`.
- `list_prd_batches`: lists the exhaustive extraction batches for a document.
- `assess_prd_batch`: extracts one batch using three MCP client sampling runs,
  for documents too large for a single `assess_prd` call.
- `list_prd_visuals`: lists detected images and diagrams.
- `observe_prd_visual`: describes one image using the client's vision-capable
  model; advisory only and never scored.
- `prepare_prd_assessment`: returns one or more exhaustive extraction batches
  for hosts without MCP sampling.
- `score_prd_extraction`: verifies and scores extraction JSON produced by the
  calling agent.
- `write_prd_revision`: writes approved supplemental answers into a new DOCX,
  Markdown, or text revision while preserving the original.
- `describe_prd_rubric`: describes the active criteria and consumers.
- `contextualize_next_question`: optionally rephrases `next_question` using a
  fact already verified elsewhere in the same document, through one
  guardrailed model choice. Advisory phrasing only; never changes the score.
- `detect_prd_framing`: classifies the PRD as a problem fix, opportunity bet,
  compliance mandate, or migration/replatform through a closed-set model
  choice, then returns the appropriate rubric-authored question wording.
- `discover_edge_case_question`: finds one concrete missing failure or
  transition question by selecting a verified source quote and a fixed
  edge-case type; Python renders the question and scoring remains unchanged.

## Install Locally

Forge requires Python 3.11 or newer and
[`uv`](https://docs.astral.sh/uv/getting-started/installation/). From the Forge
repository root, install the project and its development dependencies:

```bash
uv sync --extra dev
uv run pytest
```

Find the absolute paths needed by desktop MCP clients:

```bash
command -v uv
pwd
```

The launch command has this form. Replace both example paths in the client
configurations below with the output from those commands.

```bash
/absolute/path/to/uv --directory /absolute/path/to/forge run forge-mcp
```

You can run that command directly as a smoke test. Forge communicates over
stdio, so it normally prints nothing and waits for an MCP client; press
`Ctrl-C` to stop it. In normal use, the MCP client starts and stops Forge, so do
not run a separate background server.

## Connect Cursor

Create `.cursor/mcp.json` in the project where you want to use Forge. To make it
available in every Cursor workspace, use `~/.cursor/mcp.json` instead.

```json
{
  "mcpServers": {
    "forge": {
      "type": "stdio",
      "command": "/absolute/path/to/uv",
      "args": [
        "--directory",
        "/absolute/path/to/forge",
        "run",
        "forge-mcp"
      ]
    }
  }
}
```

Restart Cursor, open **Customize**, and confirm that `forge` is enabled. In a
Cursor agent chat, `/mcp list` shows configured servers. If startup fails, open
the Output panel and select **MCP Logs**.

## Connect Claude Code

Add Forge at user scope to make it available across all Claude Code projects:

```bash
claude mcp add --transport stdio --scope user forge -- \
  /absolute/path/to/uv --directory /absolute/path/to/forge run forge-mcp
```

Confirm the connection:

```bash
claude mcp get forge
claude mcp list
```

Use `--scope project` instead of `--scope user` when the configuration should
be written to a shareable `.mcp.json` in the current project. Claude Code asks
for approval the first time it loads a project-scoped server. Inside Claude
Code, `/mcp` shows server and tool status.

## Connect Claude Desktop

Open **Claude > Settings > Developer > Edit Config**, or edit the configuration
file directly:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

Add Forge under `mcpServers`, preserving any existing server entries:

```json
{
  "mcpServers": {
    "forge": {
      "command": "/absolute/path/to/uv",
      "args": [
        "--directory",
        "/absolute/path/to/forge",
        "run",
        "forge-mcp"
      ]
    }
  }
}
```

Completely quit and restart Claude Desktop. Open **Connectors > Manage
connectors** and confirm that Forge and its tools appear.

## Connect OpenCode

Add this to `opencode.json` in the project where you want to use Forge. For a
user-wide configuration, add the same entry to
`~/.config/opencode/opencode.json` instead.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "forge": {
      "type": "local",
      "command": [
        "/absolute/path/to/uv",
        "--directory",
        "/absolute/path/to/forge",
        "run",
        "forge-mcp"
      ],
      "enabled": true
    }
  }
}
```

Restart OpenCode and verify the server:

```bash
opencode mcp list
```

## Use Forge

First confirm that the client can see Forge by asking:

```text
Use Forge to describe the active PRD rubric.
```

Then assess a document using an absolute path:

```text
Use Forge to assess the PRD at /absolute/path/to/document.pdf. Ask me the
single next clarification question, retain my answers as supplemental evidence,
and continue until no material question remains.
```

If the host supports MCP sampling, the agent should call `assess_prd`. When that
reports that the document needs several batches, the agent should call
`list_prd_batches`, then `assess_prd_batch` for each `batch_id`, and submit the
collected fragments to `score_prd_extraction`, keeping each run's fragments
together.

When sampling is unavailable, the agent should call `prepare_prd_assessment`,
perform every returned batch extraction with its connected model, and submit the
fragments to `score_prd_extraction`.

Long documents automatically use `semchunk` to split oversized source blocks
while preserving exact source offsets. Scoring rejects incomplete fragment sets,
fragments whose criteria or fields do not match the rubric exactly, repeated run
indexes, and fragments from a stale batch plan.

Recording a new supplemental answer changes the batch plan, so the batch
extraction flow must be repeated before rescoring.

After presenting `next_question`, the agent records the reply as an object with
`criterion_id` and `answer`, then resubmits the accumulated
`supplemental_answers` on the next call. Supplemental answers are marked
separately from the PRD and may provide evidence only for their named criterion.
Forge remains stateless and returns `next_question: null` when no rubric gap
remains.

Each question includes `answer_requirements` for the exact missing fields. The
planner targets one missing field per turn through `target_field`, while keeping
the complete `missing_fields` list in the audit. The answer is rescored as
criterion-bound supplemental evidence. Once the user
approves the accumulated answers, call `write_prd_revision` with a new output
path, then assess that revision without supplemental answers. Forge never
silently overwrites the source document.

Every required field has a short, rubric-owned question written in plain,
conversational language. Forge asks for the decision or fact directly rather
than asking what "the PRD should say." Numeric and other objective requirements
remain visible in `answer_requirements`.

That plain text is always available as `next_question.base_question`. The
`next_question.question` a client actually shows is additionally, and always,
prefixed with the document's filename-derived name at no cost — no model call
involved. For a further, opt-in layer of contextualization, call
`contextualize_next_question` with the same `extraction_json` already
submitted to `score_prd_extraction`. The connected model may only choose an
index into an already-verified fact list Forge supplies (or `0` for none); it
can never author new sentences that reach the user, and any invalid or
out-of-range choice silently falls back to the plain, document-named question.
See `docs/DECISIONS.md` D-035 for the exact guardrail.

Before remediation, call `detect_prd_framing` with either the first response's
`assessment` JSON (native sampling) or the scored `extraction_json` (fallback),
then pass its returned `framing` into later
`score_prd_extraction`, `assess_prd`, or `contextualize_next_question` calls.
This changes phrasing only. For example, an opportunity PRD is asked what
opportunity it pursues and what is lost by waiting, rather than being
incorrectly asked what is broken today. The dashboard performs this
classification automatically on the first assessment and retains it across
remediation turns. See `docs/DECISIONS.md` D-036.

When `edge_cases_and_states` is missing behavioural coverage, call
`discover_edge_case_question` with the same assessment or extraction JSON.
For example, Forge can anchor to a verified progress-sync requirement and ask
what happens when connectivity is lost and restored. Submit the user's answer
as `edge_cases_and_states` supplemental evidence on the next assessment. The
discovery itself is advisory and cannot earn credit. See D-037.

`confidence` measures extraction-run agreement, not correctness. When the first
three runs disagree, the response identifies `disputed_criteria` and recommends
up to two additional complete runs. A lower result after more runs is useful
evidence of instability and is never rounded upward or hidden.

Assessment tools also accept optional `product_context` terms with `term`,
`meaning`, and `source_ref`. This background can disambiguate product language
such as “Rush,” “Microdrama,” or “package,” but it is excluded from normalized
evidence and cannot earn score credit. Any quoted evidence must still occur in
the PRD or criterion-bound supplemental answer.

Every assessment returns `report` before the detailed `assessment` audit. The
report contains the readiness headline, criterion summary, three highest-impact
gaps, exhaustive structured gap records, consumer-specific gap views, blocked
downstream consumers, next step, and an extraction-confidence note. Python
derives it from the same verified assessment; the model does not write or score
the narrative.

## Calibrate The Rubric

Calibration requires Forge assessment JSON plus independent human labels. The
label suite stores verdicts and bands, not the PRD text. Create an exhaustive
blank label from either a full Forge response or its nested `assessment` object:

```bash
uv run python -m forge.calibration template assessment.json labels.json \
  --case-id prd-001 --reviewer reviewer-a
```

The reviewer sheet deliberately excludes Forge's prediction to avoid anchoring.
Set the human `band` and every criterion verdict, then create a separate sheet
for each reviewer. Merge completed sheets into a prediction bundle before
evaluation:

```bash
uv run python -m forge.calibration merge predictions.json calibration-suite.json \
  reviewer-a.json reviewer-b.json
```

Evaluate the merged suite with:

```bash
uv run python -m forge.calibration evaluate calibration-suite.json
```

The report includes model-to-human and inter-reviewer agreement, ordinal band
distance, false-ready and false-not-ready rates, criterion-level agreement,
contested cases, source mix, and sample-size warnings. Synthetic or public PRDs
can exercise robustness, but they are excluded from headline calibration
metrics. Only representative, independently labelled internal PRDs can validate
the baseline for organization-specific use.

See `docs/EXPERT_BASELINE.md` for the published standards and public corpus
research behind the bundled rubric.

## Optional Local Dashboard (Bring Your Own Key)

For people without an MCP client, an optional local web dashboard exposes the
same upload, assessment, and one-question-at-a-time remediation loop. It is a
documented, narrow exception to "no API key": see `docs/DECISIONS.md` D-033
and `docs/ARCHITECTURE.md` "Dashboard Mode" before changing it. It is **not**
installed by default and never touches `forge-mcp` or the core domain code.

You supply your own Anthropic, OpenAI, or Gemini API key in the browser, or a
Cursor API key generated at `cursor.com/dashboard/api` if you'd rather not
configure Forge as an MCP server at all (see D-034 — this path runs each
extraction through a short-lived Cursor Cloud Agent, so it is slower and
billed against your Cursor plan instead of raw token pricing). Whichever you
choose, the key is held in that browser tab for the session only, sent to
your local FastAPI process per request, and never written to disk, a
database, or a log.

Click **Connect model** in the top navbar to open the connection dialog. It
makes one minimal test call before saving, so the navbar badge only turns
green ("Connected") once the key/model combination is actually verified.

Install the extra and start the backend:

```bash
uv sync --extra dashboard
uv run forge-dashboard-api
```

This starts a local API on `http://127.0.0.1:8000`. In a second terminal,
start the Next.js UI:

```bash
cd web
npm install
cp .env.local.example .env.local
npm run dev
```

Open `http://localhost:3000`, choose a provider and model, paste your API
key, upload a PDF/DOCX/Markdown/text PRD, and click **Assess PRD**. Answer the
single remediation question shown after each assessment to rescore with
supplemental evidence, exactly like the MCP conversation loop.

## Troubleshooting

- If a client reports that `uv` was not found, use the absolute path returned by
  `command -v uv` rather than `uv` in its configuration.
- If Forge disconnects immediately, run the configured launch command in a
  terminal to expose installation or path errors.
- If `assess_prd` cannot run because the client does not support MCP sampling,
  use the `prepare_prd_assessment` and `score_prd_extraction` fallback workflow.
- If `assess_prd` reports that a document requires multiple batches, use the
  same prepare/score fallback workflow and complete every returned batch.
- Always pass an absolute PRD path. Forge runs with your local user permissions
  and must be able to read that file.
- Forge detects embedded PDF and DOCX visuals and reports a warning. Text remains
  scoreable. To inspect a diagram, call `list_prd_visuals` and then
  `observe_prd_visual`, which sends the rendered image to a vision-capable
  client model. Those observations are advisory and never change the score;
  record any confirmed fact as a supplemental answer so it becomes verifiable
  evidence.
- If a client cannot accept image sampling requests, `observe_prd_visual` fails
  while the text assessment tools keep working.

## Verify

```bash
uv run pytest
```

See `docs/PRODUCT.md`, `docs/SCORING_THEORY.md`, `docs/ARCHITECTURE.md`,
`docs/DECISIONS.md`, and `docs/ROADMAP.md` for the canonical project record.
