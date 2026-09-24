"""Shared helpers for `forge-setup-*` CLIs (Cursor, OpenCode, ...).

These CLIs only read/write a client's own config file. They never run,
import, or otherwise touch the MCP server process or domain/scoring code —
see `src/forge/setup_cursor.py` and `src/forge/setup_opencode.py`.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

# src/forge/_client_setup.py -> src/forge -> src -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]


def find_uv() -> str:
    found = shutil.which("uv")
    if found is None:
        raise SystemExit(
            "Could not find `uv` on PATH. Install it first: "
            "https://docs.astral.sh/uv/getting-started/installation/"
        )
    return found


def load_json_object(target: Path) -> dict[str, object]:
    """Read `target` as a JSON object, or return `{}` if it doesn't exist yet."""
    if not target.exists():
        return {}
    try:
        config = json.loads(target.read_text())
    except json.JSONDecodeError as error:
        raise SystemExit(
            f"{target} exists but is not valid JSON ({error}). Fix or remove "
            "it, then re-run this command."
        ) from error
    if not isinstance(config, dict):
        raise SystemExit(f"{target} does not contain a JSON object at its root.")
    return config


def write_json_object(target: Path, config: dict[str, object]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(config, indent=2) + "\n")
