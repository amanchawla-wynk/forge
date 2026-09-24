from __future__ import annotations

import json

import pytest

from forge.setup_opencode import (
    _REPO_ROOT,
    find_uv,
    forge_server_entry,
    target_path,
    write_config,
)


def test_target_path_user_scope_uses_config_home_opencode(tmp_path):
    config_home = tmp_path / ".config"
    assert target_path("user", None, config_home=config_home) == (
        config_home / "opencode" / "opencode.json"
    )


def test_target_path_project_scope_uses_project_dir(tmp_path):
    assert target_path("project", tmp_path) == tmp_path / "opencode.json"


def test_find_uv_raises_a_clear_error_when_missing(monkeypatch):
    monkeypatch.setattr("forge._client_setup.shutil.which", lambda name: None)
    with pytest.raises(SystemExit, match="Could not find `uv`"):
        find_uv()


def test_write_config_creates_a_new_file_with_schema_and_forge_server(tmp_path):
    target = tmp_path / "opencode.json"
    changed = write_config(target, "/usr/local/bin/uv")

    assert changed is True
    payload = json.loads(target.read_text())
    assert payload["$schema"] == "https://opencode.ai/config.json"
    assert payload["mcp"]["forge"] == forge_server_entry("/usr/local/bin/uv")
    assert payload["mcp"]["forge"]["command"] == [
        "/usr/local/bin/uv",
        "--directory",
        str(_REPO_ROOT),
        "run",
        "forge-mcp",
    ]
    assert payload["mcp"]["forge"]["enabled"] is True


def test_write_config_preserves_other_servers_plugins_and_schema(tmp_path):
    target = tmp_path / "opencode.json"
    target.write_text(
        json.dumps(
            {
                "$schema": "https://opencode.ai/config.json",
                "mcp": {
                    "context7": {"type": "remote", "url": "https://example.com"}
                },
                "plugin": ["some-plugin@latest"],
            }
        )
    )

    write_config(target, "/usr/local/bin/uv")

    payload = json.loads(target.read_text())
    assert payload["mcp"]["context7"] == {
        "type": "remote",
        "url": "https://example.com",
    }
    assert payload["plugin"] == ["some-plugin@latest"]
    assert "forge" in payload["mcp"]


def test_write_config_is_idempotent(tmp_path):
    target = tmp_path / "opencode.json"
    write_config(target, "/usr/local/bin/uv")
    before = target.read_text()

    changed = write_config(target, "/usr/local/bin/uv")

    assert changed is False
    assert target.read_text() == before


def test_write_config_updates_a_stale_forge_entry(tmp_path):
    target = tmp_path / "opencode.json"
    target.write_text(
        json.dumps(
            {
                "mcp": {
                    "forge": {
                        "type": "local",
                        "command": ["/old/uv", "--directory", "/old/path", "run", "forge-mcp"],
                        "enabled": True,
                    }
                }
            }
        )
    )

    changed = write_config(target, "/usr/local/bin/uv")

    assert changed is True
    payload = json.loads(target.read_text())
    assert payload["mcp"]["forge"]["command"][0] == "/usr/local/bin/uv"


def test_write_config_rejects_invalid_json(tmp_path):
    target = tmp_path / "opencode.json"
    target.write_text("{not valid json")

    with pytest.raises(SystemExit, match="not valid JSON"):
        write_config(target, "/usr/local/bin/uv")


def test_write_config_rejects_non_object_mcp_key(tmp_path):
    target = tmp_path / "opencode.json"
    target.write_text(json.dumps({"mcp": []}))

    with pytest.raises(SystemExit, match="non-object 'mcp' key"):
        write_config(target, "/usr/local/bin/uv")
