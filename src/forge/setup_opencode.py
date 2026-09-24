"""One-command OpenCode MCP registration: `uv run forge-setup-opencode`.

Writes, or merges into, an `opencode.json` so OpenCode can launch Forge over
stdio without anyone hand-editing JSON or hunting for absolute paths. This is
pure developer-experience tooling: it never touches the MCP server process,
the domain/scoring code, or any document. See README.md "Connect OpenCode".
"""

from __future__ import annotations

import argparse
from pathlib import Path

from forge._client_setup import (
    REPO_ROOT as _REPO_ROOT,
    find_uv,
    load_json_object,
    write_json_object,
)

__all__ = [
    "find_uv",
    "target_path",
    "forge_server_entry",
    "write_config",
    "main",
]

_SCHEMA_URL = "https://opencode.ai/config.json"


def target_path(
    scope: str, project_dir: Path | None, config_home: Path | None = None
) -> Path:
    if scope == "user":
        return (config_home or (Path.home() / ".config")) / "opencode" / "opencode.json"
    return (project_dir or Path.cwd()) / "opencode.json"


def forge_server_entry(uv_path: str) -> dict[str, object]:
    return {
        "type": "local",
        "command": [uv_path, "--directory", str(_REPO_ROOT), "run", "forge-mcp"],
        "enabled": True,
    }


def write_config(target: Path, uv_path: str) -> bool:
    """Merge the `forge` server into `target`, preserving other config.

    Returns True if the file was created or changed, False if it already
    configured `forge` identically (safe to run repeatedly). Other MCP
    servers, plugins, and settings already in the file are left untouched.
    """
    config = load_json_object(target)
    changed = False

    if "$schema" not in config:
        config["$schema"] = _SCHEMA_URL
        changed = True

    servers = config.setdefault("mcp", {})
    if not isinstance(servers, dict):
        raise SystemExit(f"{target} has a non-object 'mcp' key.")

    entry = forge_server_entry(uv_path)
    if servers.get("forge") != entry:
        servers["forge"] = entry
        changed = True

    if changed:
        write_json_object(target, config)
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Register Forge as an OpenCode MCP server by writing or updating "
            "opencode.json. Existing config (other servers, plugins, settings) "
            "is preserved."
        )
    )
    parser.add_argument(
        "--scope",
        choices=["user", "project"],
        default="user",
        help=(
            "'user' (default) writes ~/.config/opencode/opencode.json, making "
            "Forge available in every OpenCode project. 'project' writes "
            "opencode.json in --project-dir (or the current directory), for "
            "this project only."
        ),
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=None,
        help="Target project directory for --scope project (default: current directory).",
    )
    args = parser.parse_args()

    uv_path = find_uv()
    target = target_path(args.scope, args.project_dir)
    changed = write_config(target, uv_path)

    if changed:
        print(f"Wrote {target}")
    else:
        print(f"{target} already configures forge correctly; no changes made.")
    print(
        "Restart OpenCode, then run `opencode mcp list` to confirm 'forge' "
        "is connected."
    )


if __name__ == "__main__":
    main()
