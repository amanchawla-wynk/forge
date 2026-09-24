"""One-command Cursor MCP registration: `uv run forge-setup-cursor`.

Writes, or merges into, a Cursor `mcp.json` so Cursor can launch Forge over
stdio without anyone hand-editing JSON or hunting for absolute paths. This is
pure developer-experience tooling: it never touches the MCP server process,
the domain/scoring code, or any document. See README.md "Connect Cursor".
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


def target_path(scope: str, project_dir: Path | None, home: Path | None = None) -> Path:
    if scope == "user":
        return (home or Path.home()) / ".cursor" / "mcp.json"
    return (project_dir or Path.cwd()) / ".cursor" / "mcp.json"


def forge_server_entry(uv_path: str) -> dict[str, object]:
    return {
        "type": "stdio",
        "command": uv_path,
        "args": ["--directory", str(_REPO_ROOT), "run", "forge-mcp"],
    }


def write_config(target: Path, uv_path: str) -> bool:
    """Merge the `forge` server into `target`, preserving any other servers.

    Returns True if the file was created or changed, False if it already
    configured `forge` identically (safe to run repeatedly).
    """
    config = load_json_object(target)
    servers = config.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise SystemExit(f"{target} has a non-object 'mcpServers' key.")

    entry = forge_server_entry(uv_path)
    if servers.get("forge") == entry:
        return False

    servers["forge"] = entry
    write_json_object(target, config)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Register Forge as a Cursor MCP server by writing or updating "
            "mcp.json. Existing servers in that file are preserved."
        )
    )
    parser.add_argument(
        "--scope",
        choices=["user", "project"],
        default="user",
        help=(
            "'user' (default) writes ~/.cursor/mcp.json, making Forge available "
            "in every Cursor workspace. 'project' writes .cursor/mcp.json in "
            "--project-dir (or the current directory), for this project only."
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
        "Restart Cursor, then confirm 'forge' is enabled under MCP settings "
        "(or run `/mcp list` in a Cursor agent chat)."
    )


if __name__ == "__main__":
    main()
