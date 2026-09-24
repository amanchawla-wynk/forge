"""Durable local document and revision-plan storage for dashboard mode."""

from __future__ import annotations

import os
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from forge.ingest.document import SUPPORTED_EXTENSIONS
from forge.revise import RevisionPlan


@dataclass(frozen=True)
class StoredDocument:
    document_id: str
    filename: str
    path: Path


class DocumentStore:
    """Persist opaque document ids and revision plans across process restarts."""

    def __init__(self, root: str | Path | None = None) -> None:
        configured = root or os.environ.get("FORGE_DASHBOARD_DATA_DIR")
        self._root = Path(configured or ".forge/dashboard").expanduser().resolve()
        self._documents_root = self._root / "documents"
        self._documents_root.mkdir(parents=True, exist_ok=True)
        os.chmod(self._root, 0o700)
        os.chmod(self._documents_root, 0o700)
        self._database = self._root / "dashboard.sqlite3"
        self._lock = Lock()
        self._initialize()
        os.chmod(self._database, 0o600)

    @property
    def root(self) -> Path:
        return self._root

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS dashboard_documents (
                    document_id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    relative_path TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS dashboard_revision_plans (
                    plan_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (document_id) REFERENCES dashboard_documents(document_id)
                      ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS dashboard_review_artifacts (
                    review_session_id TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    source_document_id TEXT NOT NULL,
                    generated_document_id TEXT NOT NULL,
                    final_review_session_id TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (review_session_id, plan_id)
                );
                """
            )

    def save(self, filename: str, content: bytes) -> StoredDocument:
        suffix = self._validated_suffix(filename)
        document_id = uuid.uuid4().hex
        relative_path = f"documents/{document_id}{suffix}"
        path = self._root / relative_path
        path.write_bytes(content)
        try:
            with self._lock, closing(self._connect()) as connection:
                connection.execute(
                    "INSERT INTO dashboard_documents(document_id, filename, relative_path) "
                    "VALUES (?, ?, ?)",
                    (document_id, Path(filename).name, relative_path),
                )
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return StoredDocument(document_id=document_id, filename=filename, path=path)

    def get(self, document_id: str) -> StoredDocument:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT document_id, filename, relative_path FROM dashboard_documents "
                "WHERE document_id = ?",
                (document_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown document_id {document_id!r}")
        path = (self._root / row["relative_path"]).resolve()
        if self._root not in path.parents or not path.is_file():
            raise FileNotFoundError(f"stored document is unavailable: {document_id!r}")
        return StoredDocument(
            document_id=row["document_id"],
            filename=row["filename"],
            path=path,
        )

    def delete(self, document_id: str) -> None:
        stored = self.get(document_id)
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "DELETE FROM dashboard_documents WHERE document_id = ?",
                    (document_id,),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        stored.path.unlink(missing_ok=True)

    def allocate_generated(self, filename: str) -> StoredDocument:
        suffix = self._validated_suffix(filename)
        if suffix == ".pdf":
            raise ValueError("generated revisions require DOCX, Markdown, or text")
        document_id = uuid.uuid4().hex
        return StoredDocument(
            document_id=document_id,
            filename=Path(filename).name,
            path=self._documents_root / f"{document_id}{suffix}",
        )

    def register_generated(self, stored: StoredDocument) -> None:
        if not stored.path.exists() or not stored.path.is_file():
            raise FileNotFoundError(f"generated document not found: {stored.path}")
        relative_path = stored.path.resolve().relative_to(self._root).as_posix()
        with self._lock, closing(self._connect()) as connection:
            try:
                connection.execute(
                    "INSERT INTO dashboard_documents(document_id, filename, relative_path) "
                    "VALUES (?, ?, ?)",
                    (stored.document_id, stored.filename, relative_path),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(
                    f"document_id already registered: {stored.document_id}"
                ) from error

    def save_revision_plan(self, document_id: str, plan: RevisionPlan) -> str:
        self.get(document_id)
        plan_id = uuid.uuid4().hex
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                "INSERT INTO dashboard_revision_plans(plan_id, document_id, plan_json) "
                "VALUES (?, ?, ?)",
                (plan_id, document_id, plan.model_dump_json()),
            )
        return plan_id

    def get_revision_plan(self, plan_id: str) -> tuple[str, RevisionPlan]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT document_id, plan_json FROM dashboard_revision_plans "
                "WHERE plan_id = ?",
                (plan_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown revision plan {plan_id!r}")
        return row["document_id"], RevisionPlan.model_validate_json(row["plan_json"])

    def delete_revision_plan(self, plan_id: str) -> None:
        with self._lock, closing(self._connect()) as connection:
            cursor = connection.execute(
                "DELETE FROM dashboard_revision_plans WHERE plan_id = ?",
                (plan_id,),
            )
        if cursor.rowcount == 0:
            raise KeyError(f"unknown revision plan {plan_id!r}")

    def link_review_artifact(
        self,
        *,
        review_session_id: str,
        plan_id: str,
        source_document_id: str,
        generated_document_id: str,
        final_review_session_id: str | None,
    ) -> None:
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                "INSERT INTO dashboard_review_artifacts "
                "(review_session_id, plan_id, source_document_id, "
                "generated_document_id, final_review_session_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    review_session_id,
                    plan_id,
                    source_document_id,
                    generated_document_id,
                    final_review_session_id,
                ),
            )

    def review_artifacts(self, review_session_id: str) -> list[dict[str, str | None]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT plan_id, source_document_id, generated_document_id, "
                "final_review_session_id FROM dashboard_review_artifacts "
                "WHERE review_session_id = ? ORDER BY created_at",
                (review_session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _validated_suffix(filename: str) -> str:
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
            raise ValueError(f"unsupported document type {suffix!r}; use {supported}")
        return suffix
