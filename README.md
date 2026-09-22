# Forge

Forge is a local MCP server that checks whether a PRD is complete and
actionable for its downstream consumers. It borrows the connected MCP client's
LLM and never requires an LLM provider API key.

The bundled rubric is an uncalibrated generic starting point. It must be tuned
against the company's PRD template and real, human-reviewed documents before
its bands are treated as reliable.

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
- `describe_prd_rubric`: describes the active criteria and consumers.

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

Every assessment returns `report` before the detailed `assessment` audit. The
report contains the readiness headline, criterion summary, three highest-impact
gaps, blocked downstream consumers, next step, and an extraction-confidence
note. Python derives it from the same verified assessment; the model does not
write or score the narrative.

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
