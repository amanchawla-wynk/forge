from __future__ import annotations

import json

import pytest

from forge.setup_cursor import (
    _REPO_ROOT,
    find_uv,
    forge_server_entry,
    target_path,
    write_config,
)


def test_target_path_user_scope_uses_home_dot_cursor(tmp_path):
    assert target_path("user", None, home=tmp_path) == tmp_path / ".cursor" / "mcp.json"


def test_target_path_project_scope_uses_project_dir(tmp_path):
    assert target_path("project", tmp_path) == tmp_path / ".cursor" / "mcp.json"


def test_find_uv_raises_a_clear_error_when_missing(monkeypatch):
    monkeypatch.setattr("forge.setup_cursor.shutil.which", lambda name: None)
    with pytest.raises(SystemExit, match="Could not find `uv`"):
        find_uv()


def test_find_uv_returns_the_resolved_path(monkeypatch):
    monkeypatch.setattr(
        "forge.setup_cursor.shutil.which", lambda name: "/usr/local/bin/uv"
    )
    assert find_uv() == "/usr/local/bin/uv"


def test_write_config_creates_a_new_file_with_the_forge_server(tmp_path):
    target = tmp_path / ".cursor" / "mcp.json"
    changed = write_config(target, "/usr/local/bin/uv")

    assert changed is True
    payload = json.loads(target.read_text())
    assert payload["mcpServers"]["forge"] == forge_server_entry("/usr/local/bin/uv")
    assert payload["mcpServers"]["forge"]["args"] == [
        "--directory",
        str(_REPO_ROOT),
        "run",
        "forge-mcp",
    ]


def test_write_config_preserves_other_servers(tmp_path):
    target = tmp_path / ".cursor" / "mcp.json"
    target.parent.mkdir(parents=True)
    target.write_text(
        json.dumps({"mcpServers": {"other": {"command": "other-tool"}}})
    )

    write_config(target, "/usr/local/bin/uv")

    payload = json.loads(target.read_text())
    assert payload["mcpServers"]["other"] == {"command": "other-tool"}
    assert "forge" in payload["mcpServers"]


def test_write_config_is_idempotent(tmp_path):
    target = tmp_path / ".cursor" / "mcp.json"
    write_config(target, "/usr/local/bin/uv")
    before = target.read_text()

    changed = write_config(target, "/usr/local/bin/uv")

    assert changed is False
    assert target.read_text() == before


def test_write_config_updates_a_stale_forge_entry(tmp_path):
    target = tmp_path / ".cursor" / "mcp.json"
    target.parent.mkdir(parents=True)
    target.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "forge": {
                        "type": "stdio",
                        "command": "/old/uv",
                        "args": ["--directory", "/old/path", "run", "forge-mcp"],
                    }
                }
            }
        )
    )

    changed = write_config(target, "/usr/local/bin/uv")

    assert changed is True
    payload = json.loads(target.read_text())
    assert payload["mcpServers"]["forge"]["command"] == "/usr/local/bin/uv"


def test_write_config_rejects_invalid_json(tmp_path):
    target = tmp_path / ".cursor" / "mcp.json"
    target.parent.mkdir(parents=True)
    target.write_text("{not valid json")

    with pytest.raises(SystemExit, match="not valid JSON"):
        write_config(target, "/usr/local/bin/uv")


def test_write_config_rejects_non_object_root(tmp_path):
    target = tmp_path / ".cursor" / "mcp.json"
    target.parent.mkdir(parents=True)
    target.write_text("[]")

    with pytest.raises(SystemExit, match="JSON object"):
        write_config(target, "/usr/local/bin/uv")
