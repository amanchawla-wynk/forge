from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_review_store(tmp_path, monkeypatch):
    """Keep durable review sessions out of the repository during tests.

    `ReviewSessionRepository` defaults to `.forge/reviews.sqlite3` relative to
    the working directory. Pointing it at a per-test temp file also guarantees
    that no test can observe another test's sessions.
    """
    monkeypatch.setenv("FORGE_SESSION_DB", str(tmp_path / "reviews.sqlite3"))

    import forge.mcp.server as server
    import forge_dashboard.app as dashboard
    from forge_dashboard.storage import DocumentStore

    monkeypatch.setattr(server, "_review_repository", None, raising=False)
    monkeypatch.setattr(dashboard, "_review_repository", None, raising=False)
    monkeypatch.setattr(
        dashboard, "_store", DocumentStore(tmp_path / "dashboard"), raising=False
    )
    yield
    monkeypatch.setattr(server, "_review_repository", None, raising=False)
    monkeypatch.setattr(dashboard, "_review_repository", None, raising=False)
