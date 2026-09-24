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
  edge-case type; Python renders the question. This single-shot tool never
  changes scoring by itself; see `assess_edge_case_coverage` below for the
  ledger that can satisfy `edge_cases_and_states`.
- `assess_edge_case_coverage`: builds a versioned coverage ledger crossing
  every verified functional requirement against the edge-case taxonomy
  entries that apply to it, using three closed-set classification runs.
  Returns which requirement/edge-case pairs are `covered`, `missing`,
  `not_applicable`, or `unclear`, plus the next uncovered question. Pass the
  returned `ledger` into `score_prd_extraction`/`assess_prd` to make it the
  authority for the `edge_cases_and_states` verdict.

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

This is the fastest path and the one most teams should use.

### One-command setup (recommended)

From the Forge repository root, after [Install Locally](#install-locally):

```bash
uv run forge-setup-cursor
```

This registers Forge in `~/.cursor/mcp.json`, so it is available in **every**
Cursor workspace on your machine — no manual JSON editing, no hunting for
absolute paths. It merges into any existing config and preserves other MCP
servers you already have; it never overwrites the file. Running it again is
always safe (it no-ops if Forge is already registered correctly).

To scope Forge to one project instead of every workspace, add
`--scope project` (writes `<project>/.cursor/mcp.json`, defaulting to the
current directory, or pass `--project-dir /path/to/project`):

```bash
uv run forge-setup-cursor --scope project --project-dir /path/to/your/project
```

Then **fully restart Cursor** (quit and reopen, not just reload the window).
Verify the connection by typing `/mcp list` in a Cursor agent chat, or open
**Cursor Settings → MCP** (menu name may vary slightly by Cursor version) and
confirm `forge` is listed and enabled.

For a whole team, the easiest rollout is: everyone clones this repo once,
runs `uv sync --extra dev` and `uv run forge-setup-cursor`, and restarts
Cursor. No shared config file or path coordination needed, since each person's
script writes their own absolute `uv` and repo paths.

### Manual setup (if you'd rather edit JSON yourself)

Create `.cursor/mcp.json` in the project where you want to use Forge (or
`~/.cursor/mcp.json` for every workspace), using the absolute paths from
`command -v uv` and `pwd` (run from the Forge repo root):

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

Restart Cursor, then confirm `forge` is enabled the same way as above.

### First prompt to try in Cursor

Cursor's support for MCP *sampling* (the capability `assess_prd` needs to
borrow its model) varies by version, so start with a prompt that lets Cursor's
agent pick whichever path works — this mirrors the fallback logic already
built into Forge's tool descriptions, so most of the time you can just say:

```text
Use the forge MCP server to assess the PRD at /absolute/path/to/document.pdf.
Try assess_prd first. If that tool errors or isn't available because this
client doesn't support MCP sampling, instead call prepare_prd_assessment,
perform each returned extraction yourself, and submit the result to
score_prd_extraction. Then show me the report and ask me the single
next_question, retaining my answers as supplemental evidence, until no
material question remains.
```

If you know your Cursor version supports sampling, the shorter prompt in
[Use Forge](#use-forge) below works too. When in doubt, use the prompt above —
it costs nothing extra and always resolves to a working path.

### Cursor-specific troubleshooting

- **`forge` doesn't appear in `/mcp list` after restart**: confirm you fully
  quit and reopened Cursor (a window reload is not always enough to reload
  `mcp.json`). Re-run `uv run forge-setup-cursor` to confirm the config is
  correct, then restart again.
- **Cursor reports it can't find `uv` or the server exits immediately**:
  Cursor launches MCP servers without your shell's login environment on
  macOS, so a bare `uv` on PATH inside a terminal is not enough — the config
  needs the absolute path. `forge-setup-cursor` already resolves this for
  you via `command -v uv`; if you edited the config by hand, double check the
  `command` field is an absolute path, not just `"uv"`.
- **A tool call sits waiting for approval**: Cursor may prompt to approve each
  MCP tool call individually depending on your auto-run/approval settings.
  Approve the first call or adjust Cursor's tool-approval setting if you want
  the whole remediation loop to run without stopping each turn.
- **To see raw errors**: open Cursor's MCP logs (look for an "MCP Logs" entry
  in the Output panel, naming may vary by version) or run the launch command
  directly in a terminal as a smoke test:
  ```bash
  uv --directory /absolute/path/to/forge run forge-mcp
  ```
  It should print nothing and hang waiting for stdio input; `Ctrl-C` to stop.
  Any Python traceback here is an installation problem, not a Cursor problem.
- **`assess_prd`, `detect_prd_framing`, or another sampling tool fails with
  "has not declared the 'sampling' capability"**: your Cursor version doesn't
  support MCP sampling. For `assess_prd`/`assess_prd_batch`, the error itself
  names the fallback — use the prompt above, or explicitly ask for
  `prepare_prd_assessment` + `score_prd_extraction` (see
  [Troubleshooting](#troubleshooting) below), which always works regardless
  of sampling support since Cursor's own agent performs the extraction.
  `detect_prd_framing`, `discover_edge_case_question`,
  `assess_edge_case_coverage`, and `contextualize_next_question` have no
  fallback yet — the error says so; just continue with `score_prd_extraction`
  or `assess_prd` alone and skip that enrichment. (If you instead see a raw
  `MCP error -32021: Client did not declare the sampling capability...`,
  you're on an older Forge checkout — `git pull` and reinstall; current
  versions always translate this into the readable message above.)

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

### One-command setup (recommended)

From the Forge repository root, after [Install Locally](#install-locally):

```bash
uv run forge-setup-opencode
```

This registers Forge in `~/.config/opencode/opencode.json`, so it is
available in **every** OpenCode project — no manual JSON editing, no hunting
for absolute paths. It merges into any existing config and preserves other
MCP servers, plugins, and settings you already have; it never overwrites the
file. Running it again is always safe (it no-ops if Forge is already
registered correctly).

To scope Forge to one project instead, add `--scope project` (writes
`<project>/opencode.json`, defaulting to the current directory, or pass
`--project-dir /path/to/project`):

```bash
uv run forge-setup-opencode --scope project --project-dir /path/to/your/project
```

Then restart OpenCode and verify:

```bash
opencode mcp list
```

For a whole team, the rollout is the same shape as Cursor: everyone clones
this repo once, runs `uv sync --extra dev` and `uv run forge-setup-opencode`,
and restarts OpenCode. Each person's script writes their own absolute `uv`
and repo paths, so there's no config file to share or coordinate.

### Manual setup (if you'd rather edit JSON yourself)

Add this to `opencode.json` in the project where you want to use Forge (or
`~/.config/opencode/opencode.json` for every project), using the absolute
paths from `command -v uv` and `pwd` (run from the Forge repo root):

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

### First prompt to try in OpenCode

**Confirmed:** OpenCode does not support MCP sampling, so `assess_prd` fails
there. Go straight to the fallback workflow — either of these works:

```text
Use the forge MCP server to assess the PRD at /absolute/path/to/document.pdf.
This client doesn't support MCP sampling, so call prepare_prd_assessment,
perform each returned extraction yourself, and submit the result to
score_prd_extraction. Then show me the report and ask me the single
next_question, retaining my answers as supplemental evidence, until no
material question remains.
```

or just ask directly:

```text
Use Forge to assess the PRD at /absolute/path/to/document.pdf using the
fallback (non-sampling) workflow, then walk me through the remediation
questions one at a time.
```

OpenCode's own agent will otherwise try `assess_prd` first, see it fail, and
self-correct to the fallback tools anyway (this is exactly the behavior
reported in practice), so either prompt gets you there — the explicit one
just skips the failed first attempt.

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

In Cursor specifically, prefer the fallback-aware prompt in
[Connect Cursor](#connect-cursor) instead, since it works whether or not your
Cursor version supports MCP sampling.

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
`assess_edge_case_coverage` with the same assessment or extraction JSON. It
crosses every verified functional requirement against the edge-case taxonomy
entries that deterministically apply to it (a sync requirement gets
connectivity-loss and concurrent-state checks; a quota requirement gets
exhaustion and retry checks, and so on) and returns a versioned ledger: each
requirement/edge-case pair is `covered`, `missing`, `not_applicable`, or
`unclear`. Pass the returned `ledger` into `score_prd_extraction` or
`assess_prd` and it becomes the authority for the `edge_cases_and_states`
verdict — PRESENT only once every applicable pair is covered or explicitly not
applicable, and platform/accessibility are also satisfied. Present the
`next_question` from the ledger to the user, and submit their answer as a
`SupplementalAnswer` carrying that exact `requirement_quote`, `edge_case_id`,
and `taxonomy_version` so the next rescore updates only that one cell instead
of silently marking the whole field satisfied. "Complete" is always relative
to the declared taxonomy version, never a claim that every possible edge case
has been found. `discover_edge_case_question` remains available as a
lighter-weight single question, but only the ledger can move the verdict past
PARTIAL. See D-037 and D-038.

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

Using Cursor? See [Cursor-specific troubleshooting](#cursor-specific-troubleshooting)
first; the issues below apply to every MCP client.

- If a client reports that `uv` was not found, use the absolute path returned by
  `command -v uv` rather than `uv` in its configuration (or, for Cursor, just
  run `uv run forge-setup-cursor`, which does this for you).
- If Forge disconnects immediately, run the configured launch command in a
  terminal to expose installation or path errors.
- If `assess_prd` cannot run because the client does not support MCP sampling,
  use the `prepare_prd_assessment` and `score_prd_extraction` fallback workflow.
  Forge detects this itself and returns a message naming that fallback,
  rather than a raw protocol error.
- If `assess_prd` reports that a document requires multiple batches, use the
  same prepare/score fallback workflow and complete every returned batch.
- `detect_prd_framing`, `discover_edge_case_question`,
  `assess_edge_case_coverage`, and `contextualize_next_question` are all
  sampling-only with no fallback yet: on a client without sampling, they fail
  with a message saying so explicitly. This is expected — continue with
  `score_prd_extraction`/`assess_prd` alone; you just don't get framing-aware
  wording or edge-case enrichment on that client.
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
