from __future__ import annotations

import getpass
import hashlib
import json
import os
import sqlite3
import time
import uuid
from contextlib import closing
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Any

from pydantic import BaseModel, Field

from forge.evaluate.models import CriterionEvaluation
from forge.ingest.document import ingest_snapshot
from forge.ingest.snapshot import (
    DocumentSnapshot,
    SnapshotCache,
    rebind_snapshot_origin,
)
from forge.remediation import (
    RemediationState,
    RemediationTurn,
    assert_current_source,
    current_turn,
)
from forge.revise import is_revision_operation_temp_path
from forge.rubric.loader import load_rubric
from forge.rubric.models import Rubric


class WorkflowState(str, Enum):
    AWAITING_ANSWER = "awaiting_answer"
    COLLECTING_ANSWERS = "collecting_answers"
    CHECKPOINT_REQUIRED = "checkpoint_required"
    AWAITING_DELTA_EXTRACTION = "awaiting_delta_extraction"
    REVISION_READY = "revision_ready"
    AWAITING_REVISION_APPROVAL = "awaiting_revision_approval"
    FINAL_ASSESSMENT_REQUIRED = "final_assessment_required"
    COMPLETE = "complete"
    PAUSED = "paused"


class NextAction(BaseModel):
    type: str
    tool: str | None = None


class ClientBinding(BaseModel):
    client_name: str | None = None
    client_version: str | None = None
    host_conversation_id: str | None = None


class ReviewSession(BaseModel):
    review_session_id: str
    session_version: int
    workflow_state: WorkflowState
    next_action: NextAction
    state: RemediationState
    workspace_fingerprint: str
    local_user: str
    client_binding: ClientBinding
    created_at: float
    updated_at: float
    expires_at: float


class ReviewSessionSummary(BaseModel):
    review_session_id: str
    display_name: str
    source_path: str
    source_sha256: str
    current_band: str
    workflow_state: WorkflowState
    verified_answer_count: int
    pending_answer_count: int
    client_name: str | None
    updated_at: float
    compatible: bool = True
    incompatibility_reasons: list[str] = Field(default_factory=list)


class ReviewStatus(BaseModel):
    review_session_id: str
    session_version: int
    workflow_state: WorkflowState
    next_action: NextAction
    next_question: dict[str, Any] | None
    source_path: str
    source_sha256: str
    current_band: str
    verified_answer_count: int
    pending_answer_count: int
    client_binding: ClientBinding


def workspace_fingerprint(source_path: str, workspace_root: str | None = None) -> str:
    root = Path(workspace_root).expanduser().resolve() if workspace_root else Path(source_path).expanduser().resolve().parent
    return hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:32]


def local_user_identity(value: str | None = None) -> str:
    return value.strip() if value and value.strip() else getpass.getuser()


def operation_digest(operation_type: str, payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        {"operation_type": operation_type, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def workflow_for_turn(turn: RemediationTurn) -> WorkflowState:
    if turn.checkpoint_due:
        return WorkflowState.CHECKPOINT_REQUIRED
    if turn.next_question is None:
        return WorkflowState.REVISION_READY
    if turn.pending_answer_count:
        return WorkflowState.COLLECTING_ANSWERS
    return WorkflowState.AWAITING_ANSWER


def next_action_for(state: WorkflowState) -> NextAction:
    actions = {
        WorkflowState.AWAITING_ANSWER: NextAction(type="ask_question"),
        WorkflowState.COLLECTING_ANSWERS: NextAction(type="ask_question"),
        WorkflowState.CHECKPOINT_REQUIRED: NextAction(
            type="prepare_checkpoint", tool="prepare_prd_checkpoint"
        ),
        WorkflowState.AWAITING_DELTA_EXTRACTION: NextAction(
            type="submit_delta", tool="apply_prd_checkpoint"
        ),
        WorkflowState.REVISION_READY: NextAction(
            type="review_revision", tool="preview_prd_revision"
        ),
        WorkflowState.AWAITING_REVISION_APPROVAL: NextAction(
            type="approve_revision", tool="write_integrated_prd_revision"
        ),
        WorkflowState.FINAL_ASSESSMENT_REQUIRED: NextAction(
            type="complete_review", tool="complete_prd_review"
        ),
        WorkflowState.COMPLETE: NextAction(type="complete"),
        WorkflowState.PAUSED: NextAction(type="resume", tool="resume_prd_review"),
    }
    return actions[state]


class ReviewSessionRepository:
    def __init__(self, path: str | Path | None = None, *, ttl_seconds: int = 604_800) -> None:
        configured = path or os.environ.get("FORGE_SESSION_DB") or Path(".forge/reviews.sqlite3")
        self.path = Path(configured).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        self.ttl_seconds = ttl_seconds
        self._lock = Lock()
        self._initialize()
        os.chmod(self.path, 0o600)
        self.purge_expired()

    def _connect(self) -> sqlite3.Connection:
        # `isolation_level=None` puts sqlite3 in autocommit mode so this module
        # controls transactions explicitly with BEGIN IMMEDIATE. Without it,
        # Python opens implicit transactions that make the read-modify-write in
        # `update()` race against a concurrent chat.
        connection = sqlite3.connect(self.path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS document_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    source_sha256 TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    parser_fingerprint TEXT NOT NULL,
                    normalized_hash TEXT NOT NULL,
                    normalized_schema_version TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS review_sessions (
                    review_session_id TEXT PRIMARY KEY,
                    session_version INTEGER NOT NULL,
                    workflow_state TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    rubric_id TEXT NOT NULL,
                    rubric_version TEXT NOT NULL,
                    workspace_fingerprint TEXT NOT NULL,
                    local_user TEXT NOT NULL,
                    client_name TEXT,
                    client_version TEXT,
                    host_conversation_id TEXT,
                    snapshot_id TEXT,
                    parser_fingerprint TEXT,
                    normalized_hash TEXT,
                    state_schema_version INTEGER NOT NULL DEFAULT 1,
                    evaluation_revision INTEGER NOT NULL DEFAULT 0,
                    state_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS review_sessions_source_idx
                  ON review_sessions(source_sha256, workspace_fingerprint, local_user);
                CREATE TABLE IF NOT EXISTS criterion_evaluation_artifacts (
                    evaluation_id TEXT PRIMARY KEY,
                    snapshot_id TEXT NOT NULL,
                    rubric_id TEXT NOT NULL,
                    rubric_version TEXT NOT NULL,
                    plan_fingerprint TEXT NOT NULL,
                    evaluation_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY (snapshot_id) REFERENCES document_snapshots(snapshot_id)
                );
                CREATE TABLE IF NOT EXISTS review_evaluation_artifacts (
                    review_session_id TEXT NOT NULL,
                    evaluation_id TEXT NOT NULL,
                    evaluation_revision INTEGER NOT NULL,
                    purpose TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (
                        review_session_id, evaluation_id,
                        evaluation_revision, purpose
                    ),
                    FOREIGN KEY (review_session_id) REFERENCES review_sessions(review_session_id)
                      ON DELETE CASCADE,
                    FOREIGN KEY (evaluation_id) REFERENCES criterion_evaluation_artifacts(evaluation_id)
                );
                CREATE TABLE IF NOT EXISTS review_operations (
                    review_session_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    operation_type TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    PRIMARY KEY (review_session_id, operation_id),
                    FOREIGN KEY (review_session_id) REFERENCES review_sessions(review_session_id)
                      ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS review_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    review_session_id TEXT NOT NULL,
                    session_version INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY (review_session_id) REFERENCES review_sessions(review_session_id)
                      ON DELETE CASCADE
                );
                """
            )
            self._ensure_column(
                connection, "review_sessions", "snapshot_id", "TEXT"
            )
            self._ensure_column(
                connection, "review_sessions", "parser_fingerprint", "TEXT"
            )
            self._ensure_column(
                connection, "review_sessions", "normalized_hash", "TEXT"
            )
            self._ensure_column(
                connection,
                "review_sessions",
                "state_schema_version",
                "INTEGER NOT NULL DEFAULT 1",
            )
            self._ensure_column(
                connection,
                "review_sessions",
                "evaluation_revision",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                connection,
                "review_operations",
                "operation_type",
                "TEXT NOT NULL DEFAULT 'legacy'",
            )
            self._ensure_column(
                connection,
                "review_operations",
                "request_digest",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                connection,
                "review_operations",
                "status",
                "TEXT NOT NULL DEFAULT 'completed'",
            )
            self._ensure_column(
                connection,
                "review_operations",
                "metadata_json",
                "TEXT NOT NULL DEFAULT '{}'",
            )

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        declaration: str,
    ) -> None:
        columns = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {declaration}"
            )

    def create(
        self,
        state: RemediationState,
        *,
        review_session_id: str | None = None,
        workspace_root: str | None = None,
        local_user: str | None = None,
        client_binding: ClientBinding | None = None,
    ) -> ReviewSession:
        now = time.time()
        review_id = review_session_id or "rvw_" + uuid.uuid4().hex
        if not review_id.strip():
            raise ValueError("review_session_id must not be blank")
        binding = client_binding or ClientBinding()
        workflow = workflow_for_turn(current_turn(state))
        workspace = workspace_fingerprint(state.source_path, workspace_root)
        user = local_user_identity(local_user)
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if state.source_snapshot is None and state.snapshot_id is not None:
                    stored_snapshot = self._get_snapshot(
                        connection, state.snapshot_id
                    )
                    if stored_snapshot is not None:
                        state = state.model_copy(
                            update={"source_snapshot": stored_snapshot}
                        )
                self._validate_state_snapshot(state)
                self._put_snapshot(connection, state.source_snapshot)
                connection.execute(
                    """
                    INSERT INTO review_sessions (
                        review_session_id, session_version, workflow_state,
                        source_path, source_sha256, rubric_id, rubric_version,
                        workspace_fingerprint, local_user, client_name,
                        client_version, host_conversation_id, snapshot_id,
                        parser_fingerprint, normalized_hash, state_schema_version,
                        evaluation_revision, state_json, created_at, updated_at,
                        expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        review_id,
                        1,
                        workflow.value,
                        state.source_path,
                        state.source_sha256,
                        state.rubric_id,
                        state.rubric_version,
                        workspace,
                        user,
                        binding.client_name,
                        binding.client_version,
                        binding.host_conversation_id,
                        state.snapshot_id,
                        state.parser_fingerprint,
                        state.normalized_hash,
                        state.state_schema_version,
                        state.evaluation_revision,
                        state.model_dump_json(),
                        now,
                        now,
                        now + self.ttl_seconds,
                    ),
                )
                self._put_evaluation_artifacts(
                    connection,
                    review_id,
                    state.criterion_evaluations,
                    evaluation_revision=state.evaluation_revision,
                    purpose="baseline",
                )
                self._event(connection, review_id, 1, "review_started", {})
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return self.get(review_id)

    def get(self, review_session_id: str) -> ReviewSession:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM review_sessions WHERE review_session_id = ?",
                (review_session_id,),
            ).fetchone()
            if row is not None and row["expires_at"] >= time.time():
                return self._session(row, connection=connection)
        if row is None:
            raise KeyError(f"unknown review_session_id {review_session_id!r}")
        if row["expires_at"] < time.time():
            self.delete(review_session_id)
            raise KeyError(f"expired review_session_id {review_session_id!r}")
        raise KeyError(f"unknown review_session_id {review_session_id!r}")

    def find(
        self,
        source_path: str,
        *,
        workspace_root: str | None = None,
        local_user: str | None = None,
        rubric_name: str = "prd",
    ) -> list[ReviewSessionSummary]:
        source = Path(source_path).expanduser().resolve()
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"document not found: {source}")
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        workspace = workspace_fingerprint(str(source), workspace_root)
        user = local_user_identity(local_user)
        current_snapshot = ingest_snapshot(source, SnapshotCache())
        current_rubric = load_rubric(rubric_name)
        now = time.time()
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM review_sessions
                WHERE source_sha256 = ? AND workspace_fingerprint = ?
                  AND local_user = ? AND expires_at >= ?
                ORDER BY updated_at DESC
                """,
                (source_hash, workspace, user, now),
            ).fetchall()
            return [
                self._summary(
                    self._session(
                        row, connection=connection, require_snapshot=False
                    ),
                    self._compatibility_reasons(
                        connection, row, current_snapshot, current_rubric
                    ),
                )
                for row in rows
            ]

    def get_snapshot(self, snapshot_id: str) -> DocumentSnapshot:
        with closing(self._connect()) as connection:
            snapshot = self._get_snapshot(connection, snapshot_id)
        if snapshot is None:
            raise KeyError(f"unknown snapshot_id {snapshot_id!r}")
        return snapshot

    def put_snapshot(self, snapshot: DocumentSnapshot) -> None:
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._put_snapshot(connection, snapshot)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def list_evaluation_artifacts(
        self, review_session_id: str
    ) -> list[CriterionEvaluation]:
        with closing(self._connect()) as connection:
            return self._get_evaluation_artifacts(connection, review_session_id)

    def operation_result(
        self,
        review_session_id: str,
        operation_id: str,
        *,
        operation_type: str,
        request_digest: str,
    ) -> str | None:
        row = self.operation_record(
            review_session_id,
            operation_id,
            operation_type=operation_type,
            request_digest=request_digest,
        )
        if row is None:
            return None
        if row["status"] == "pending":
            raise ValueError(
                "operation is already in progress; retry with the same operation_id"
            )
        return str(row["result_json"])

    def operation_record(
        self,
        review_session_id: str,
        operation_id: str,
        *,
        operation_type: str,
        request_digest: str,
    ) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT operation_type, request_digest, status, result_json,
                       metadata_json
                FROM review_operations
                WHERE review_session_id = ? AND operation_id = ?
                """,
                (review_session_id, operation_id),
            ).fetchone()
        if row is None:
            return None
        self._validate_operation(row, operation_type, request_digest)
        return {
            "status": row["status"],
            "result_json": row["result_json"],
            "metadata": json.loads(row["metadata_json"] or "{}"),
        }

    def reserve_operation(
        self,
        review_session_id: str,
        *,
        expected_version: int,
        operation_id: str,
        operation_type: str,
        request_digest: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not operation_id.strip():
            raise ValueError("operation_id must not be blank")
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    "SELECT operation_type, request_digest, status, result_json "
                    "FROM review_operations WHERE review_session_id = ? "
                    "AND operation_id = ?",
                    (review_session_id, operation_id),
                ).fetchone()
                if existing is not None:
                    self._validate_operation(
                        existing, operation_type, request_digest
                    )
                    raise ValueError("operation is already in progress or completed")
                row = connection.execute(
                    "SELECT session_version FROM review_sessions "
                    "WHERE review_session_id = ?",
                    (review_session_id,),
                ).fetchone()
                if row is None:
                    raise KeyError(f"unknown review_session_id {review_session_id!r}")
                if row["session_version"] != expected_version:
                    self._raise_stale(row["session_version"], expected_version)
                pending = connection.execute(
                    "SELECT operation_id FROM review_operations "
                    "WHERE review_session_id = ? AND status = 'pending'",
                    (review_session_id,),
                ).fetchone()
                if pending is not None:
                    raise ValueError("another operation is already in progress")
                connection.execute(
                    "INSERT INTO review_operations "
                    "(review_session_id, operation_id, operation_type, "
                    "request_digest, status, result_json, metadata_json, created_at) "
                    "VALUES (?, ?, ?, ?, 'pending', '', ?, ?)",
                    (
                        review_session_id,
                        operation_id,
                        operation_type,
                        request_digest,
                        json.dumps(metadata or {}, sort_keys=True),
                        time.time(),
                    ),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def update_operation_metadata(
        self,
        review_session_id: str,
        operation_id: str,
        *,
        operation_type: str,
        request_digest: str,
        metadata: dict[str, Any],
    ) -> None:
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT operation_type, request_digest, status, result_json, "
                    "metadata_json FROM review_operations "
                    "WHERE review_session_id = ? AND operation_id = ?",
                    (review_session_id, operation_id),
                ).fetchone()
                if row is None:
                    raise KeyError(f"unknown operation_id {operation_id!r}")
                self._validate_operation(row, operation_type, request_digest)
                if row["status"] != "pending":
                    raise ValueError("operation is already completed")
                connection.execute(
                    "UPDATE review_operations SET metadata_json = ? "
                    "WHERE review_session_id = ? AND operation_id = ?",
                    (
                        json.dumps(metadata, sort_keys=True),
                        review_session_id,
                        operation_id,
                    ),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def cancel_operation(self, review_session_id: str, operation_id: str) -> None:
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                "DELETE FROM review_operations WHERE review_session_id = ? "
                "AND operation_id = ? AND status = 'pending'",
                (review_session_id, operation_id),
            )

    def update(
        self,
        review_session_id: str,
        *,
        expected_version: int,
        operation_id: str,
        state: RemediationState,
        workflow_state: WorkflowState,
        event_type: str,
        result_json: str,
        event_payload: dict[str, Any] | None = None,
        client_binding: ClientBinding | None = None,
        operation_type: str | None = None,
        request_digest: str = "",
        complete_reserved: bool = False,
    ) -> ReviewSession:
        if not operation_id.strip():
            raise ValueError("operation_id must not be blank")
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._validate_state_snapshot(state)
                operation_kind = operation_type or event_type
                cached = connection.execute(
                    """
                    SELECT operation_type, request_digest, status, result_json
                    FROM review_operations
                    WHERE review_session_id = ? AND operation_id = ?
                    """,
                    (review_session_id, operation_id),
                ).fetchone()
                if cached is not None:
                    self._validate_operation(
                        cached, operation_kind, request_digest
                    )
                    if cached["status"] == "completed":
                        connection.rollback()
                        return self.get(review_session_id)
                    if not complete_reserved:
                        raise ValueError("operation is already in progress")
                row = connection.execute(
                    "SELECT * FROM review_sessions WHERE review_session_id = ?",
                    (review_session_id,),
                ).fetchone()
                if row is None:
                    raise KeyError(f"unknown review_session_id {review_session_id!r}")
                if row["session_version"] != expected_version:
                    self._raise_stale(row["session_version"], expected_version)
                if (
                    row["snapshot_id"] != state.snapshot_id
                    or row["parser_fingerprint"] != state.parser_fingerprint
                    or row["normalized_hash"] != state.normalized_hash
                ):
                    raise ValueError("review session snapshot identity is immutable")
                pending = connection.execute(
                    "SELECT operation_id FROM review_operations "
                    "WHERE review_session_id = ? AND status = 'pending' "
                    "AND operation_id != ?",
                    (review_session_id, operation_id),
                ).fetchone()
                if pending is not None:
                    raise ValueError("another operation is already in progress")
                version = expected_version + 1
                now = time.time()
                binding = client_binding or ClientBinding(
                    client_name=row["client_name"],
                    client_version=row["client_version"],
                    host_conversation_id=row["host_conversation_id"],
                )
                connection.execute(
                    """
                    UPDATE review_sessions SET session_version = ?, workflow_state = ?,
                        state_json = ?, state_schema_version = ?,
                        evaluation_revision = ?, client_name = ?, client_version = ?,
                        host_conversation_id = ?, updated_at = ?, expires_at = ?
                    WHERE review_session_id = ? AND session_version = ?
                    """,
                    (
                        version,
                        workflow_state.value,
                        state.model_dump_json(),
                        state.state_schema_version,
                        state.evaluation_revision,
                        binding.client_name,
                        binding.client_version,
                        binding.host_conversation_id,
                        now,
                        now + self.ttl_seconds,
                        review_session_id,
                        expected_version,
                    ),
                )
                if cached is None:
                    connection.execute(
                        "INSERT INTO review_operations "
                        "(review_session_id, operation_id, operation_type, "
                        "request_digest, status, result_json, created_at) "
                        "VALUES (?, ?, ?, ?, 'completed', ?, ?)",
                        (
                            review_session_id,
                            operation_id,
                            operation_kind,
                            request_digest,
                            result_json,
                            now,
                        ),
                    )
                else:
                    connection.execute(
                        "UPDATE review_operations SET status = 'completed', "
                        "result_json = ? WHERE review_session_id = ? "
                        "AND operation_id = ?",
                        (result_json, review_session_id, operation_id),
                    )
                self._event(
                    connection,
                    review_session_id,
                    version,
                    event_type,
                    event_payload or {},
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return self.get(review_session_id)

    @staticmethod
    def _validate_operation(
        row: sqlite3.Row, operation_type: str, request_digest: str
    ) -> None:
        if row["operation_type"] != operation_type:
            raise ValueError(
                "operation_id was already used for a different operation type"
            )
        if row["request_digest"] != request_digest:
            raise ValueError(
                "operation_id was already used with a different request payload"
            )

    @staticmethod
    def _raise_stale(current: int, received: int) -> None:
        raise ValueError(
            "stale session_version: this review was updated in another "
            f"conversation (expected {current}, received {received}). "
            "Refresh before continuing."
        )

    def resume(
        self,
        review_session_id: str,
        *,
        source_path: str,
        client_binding: ClientBinding,
        confirm_client_change: bool,
        expected_version: int,
        operation_id: str,
        workspace_root: str | None = None,
        local_user: str | None = None,
    ) -> ReviewSession:
        session = self.get(review_session_id)
        source = Path(source_path).expanduser().resolve()
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        if source_hash != session.state.source_sha256:
            raise ValueError("review session belongs to a different source document")
        if workspace_fingerprint(str(source), workspace_root) != session.workspace_fingerprint:
            raise ValueError("review session belongs to a different workspace")
        if local_user_identity(local_user) != session.local_user:
            raise ValueError("review session belongs to a different local user")
        assert_current_source(session.state, str(source))
        current_snapshot = ingest_snapshot(source, SnapshotCache())
        current_rubric = load_rubric(session.state.rubric_name)
        reasons = self._session_compatibility_reasons(
            session, current_snapshot, current_rubric
        )
        if reasons:
            raise ValueError("review session is incompatible: " + "; ".join(reasons))
        changed = _binding_changed(session.client_binding, client_binding)
        if changed and not confirm_client_change:
            raise ValueError(
                "client binding changed; explicit confirm_client_change is required"
            )
        workflow = (
            session.workflow_state
            if session.workflow_state
            in {
                WorkflowState.AWAITING_DELTA_EXTRACTION,
                WorkflowState.AWAITING_REVISION_APPROVAL,
                WorkflowState.FINAL_ASSESSMENT_REQUIRED,
                WorkflowState.COMPLETE,
            }
            else workflow_for_turn(current_turn(session.state))
        )
        request_digest = operation_digest(
            "resume_review",
            {
                "source_sha256": source_hash,
                "client_binding": client_binding.model_dump(),
                "confirm_client_change": confirm_client_change,
            },
        )
        return self.update(
            review_session_id,
            expected_version=expected_version,
            operation_id=operation_id,
            state=session.state,
            workflow_state=workflow,
            event_type="client_binding_changed" if changed else "review_resumed",
            result_json=json.dumps({"resumed": True}),
            event_payload={
                "from": session.client_binding.model_dump(),
                "to": client_binding.model_dump(),
            },
            client_binding=client_binding,
            operation_type="resume_review",
            request_digest=request_digest,
        )

    def delete(self, review_session_id: str) -> None:
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                exists = connection.execute(
                    "SELECT 1 FROM review_sessions WHERE review_session_id = ?",
                    (review_session_id,),
                ).fetchone()
                if exists is None:
                    connection.rollback()
                    raise KeyError(f"unknown review_session_id {review_session_id!r}")
                self._unlink_pending_revision_temps(connection, [review_session_id])
                cursor = connection.execute(
                    "DELETE FROM review_sessions WHERE review_session_id = ?",
                    (review_session_id,),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        if cursor.rowcount == 0:
            raise KeyError(f"unknown review_session_id {review_session_id!r}")

    def purge_expired(self) -> int:
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                rows = connection.execute(
                    "SELECT review_session_id FROM review_sessions WHERE expires_at < ?",
                    (time.time(),),
                ).fetchall()
                review_ids = [str(row["review_session_id"]) for row in rows]
                self._unlink_pending_revision_temps(connection, review_ids)
                cursor = connection.execute(
                    "DELETE FROM review_sessions WHERE expires_at < ?",
                    (time.time(),),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return cursor.rowcount

    @staticmethod
    def _unlink_pending_revision_temps(
        connection: sqlite3.Connection, review_session_ids: list[str]
    ) -> None:
        for review_session_id in review_session_ids:
            rows = connection.execute(
                "SELECT operation_id, operation_type, metadata_json "
                "FROM review_operations WHERE review_session_id = ? "
                "AND status = 'pending' AND operation_type IN "
                "('write_revision', 'write_integrated_revision')",
                (review_session_id,),
            ).fetchall()
            for row in rows:
                metadata = json.loads(row["metadata_json"] or "{}")
                temp_path = metadata.get("temp_path")
                output_path = metadata.get("output_path")
                if not isinstance(temp_path, str) or not isinstance(output_path, str):
                    continue
                if is_revision_operation_temp_path(
                    temp_path,
                    output_path,
                    review_session_id,
                    str(row["operation_id"]),
                ):
                    Path(temp_path).expanduser().resolve().unlink(missing_ok=True)

    def events(self, review_session_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT session_version, event_type, payload_json, created_at
                FROM review_events WHERE review_session_id = ? ORDER BY event_id
                """,
                (review_session_id,),
            ).fetchall()
        return [
            {
                "session_version": row["session_version"],
                "event_type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def _event(
        self,
        connection: sqlite3.Connection,
        review_session_id: str,
        version: int,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        connection.execute(
            "INSERT INTO review_events(review_session_id, session_version, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                review_session_id,
                version,
                event_type,
                json.dumps(payload, sort_keys=True),
                time.time(),
            ),
        )

    @staticmethod
    def _put_snapshot(
        connection: sqlite3.Connection, snapshot: DocumentSnapshot | None
    ) -> None:
        if snapshot is None:
            raise ValueError("new review sessions require an exact source snapshot")
        connection.execute(
            """
            INSERT OR IGNORE INTO document_snapshots (
                snapshot_id, source_sha256, source_type, parser_fingerprint,
                normalized_hash, normalized_schema_version, snapshot_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.snapshot_id,
                snapshot.source.sha256,
                snapshot.source.source_type,
                snapshot.parser_fingerprint,
                snapshot.normalized_hash,
                snapshot.normalized_schema_version,
                snapshot.model_dump_json(),
                time.time(),
            ),
        )

    @staticmethod
    def _put_evaluation_artifacts(
        connection: sqlite3.Connection,
        review_session_id: str,
        artifacts: list[CriterionEvaluation],
        *,
        evaluation_revision: int,
        purpose: str,
    ) -> None:
        for artifact in artifacts:
            serialized = artifact.model_dump_json()
            connection.execute(
                """
                INSERT OR IGNORE INTO criterion_evaluation_artifacts (
                    evaluation_id, snapshot_id, rubric_id, rubric_version,
                    plan_fingerprint, evaluation_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.evaluation_id,
                    artifact.snapshot_id,
                    artifact.rubric_id,
                    artifact.rubric_version,
                    artifact.plan_fingerprint,
                    serialized,
                    time.time(),
                ),
            )
            existing = connection.execute(
                "SELECT evaluation_json FROM criterion_evaluation_artifacts "
                "WHERE evaluation_id = ?",
                (artifact.evaluation_id,),
            ).fetchone()
            if existing is None or CriterionEvaluation.model_validate_json(
                existing["evaluation_json"]
            ) != artifact:
                raise ValueError(
                    "criterion evaluation identity conflicts with stored content"
                )
            connection.execute(
                """
                INSERT OR IGNORE INTO review_evaluation_artifacts (
                    review_session_id, evaluation_id, evaluation_revision,
                    purpose, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    review_session_id,
                    artifact.evaluation_id,
                    evaluation_revision,
                    purpose,
                    time.time(),
                ),
            )

    @staticmethod
    def _get_evaluation_artifacts(
        connection: sqlite3.Connection, review_session_id: str
    ) -> list[CriterionEvaluation]:
        rows = connection.execute(
            """
            SELECT artifact.evaluation_json
            FROM review_evaluation_artifacts AS link
            JOIN criterion_evaluation_artifacts AS artifact
              ON artifact.evaluation_id = link.evaluation_id
            WHERE link.review_session_id = ?
            ORDER BY link.evaluation_revision, artifact.evaluation_id
            """,
            (review_session_id,),
        ).fetchall()
        return [
            CriterionEvaluation.model_validate_json(row["evaluation_json"])
            for row in rows
        ]

    @staticmethod
    def _get_snapshot(
        connection: sqlite3.Connection, snapshot_id: str
    ) -> DocumentSnapshot | None:
        row = connection.execute(
            "SELECT snapshot_json FROM document_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        return (
            DocumentSnapshot.model_validate_json(row["snapshot_json"])
            if row is not None
            else None
        )

    @staticmethod
    def _validate_state_snapshot(state: RemediationState) -> None:
        snapshot = state.source_snapshot
        if snapshot is None:
            raise ValueError("new review sessions require an exact source snapshot")
        if (
            state.snapshot_id != snapshot.snapshot_id
            or state.parser_fingerprint != snapshot.parser_fingerprint
            or state.normalized_hash != snapshot.normalized_hash
            or state.source_sha256 != snapshot.source.sha256
        ):
            raise ValueError("remediation state does not match its source snapshot")

    @classmethod
    def _compatibility_reasons(
        cls,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        current_snapshot: DocumentSnapshot,
        current_rubric: Rubric,
    ) -> list[str]:
        if row["snapshot_id"] is None:
            return ["legacy session has no durable snapshot identity"]
        stored_snapshot = cls._get_snapshot(connection, row["snapshot_id"])
        if stored_snapshot is None:
            return ["durable source snapshot is missing"]
        reasons: list[str] = []
        if stored_snapshot.source.source_type != current_snapshot.source.source_type:
            reasons.append("source type changed")
        if row["parser_fingerprint"] != current_snapshot.parser_fingerprint:
            reasons.append("parser fingerprint changed")
        if row["normalized_hash"] != current_snapshot.normalized_hash:
            reasons.append("normalized document changed")
        if row["snapshot_id"] != current_snapshot.snapshot_id:
            reasons.append("snapshot identity changed")
        if (
            row["rubric_id"] != current_rubric.id
            or row["rubric_version"] != current_rubric.version
        ):
            reasons.append("rubric identity changed")
        return reasons

    @staticmethod
    def _session_compatibility_reasons(
        session: ReviewSession,
        current_snapshot: DocumentSnapshot,
        current_rubric: Rubric,
    ) -> list[str]:
        state = session.state
        if state.source_snapshot is None or state.snapshot_id is None:
            return ["legacy session has no durable snapshot identity"]
        reasons: list[str] = []
        if state.source_snapshot.source.source_type != current_snapshot.source.source_type:
            reasons.append("source type changed")
        if state.parser_fingerprint != current_snapshot.parser_fingerprint:
            reasons.append("parser fingerprint changed")
        if state.normalized_hash != current_snapshot.normalized_hash:
            reasons.append("normalized document changed")
        if state.snapshot_id != current_snapshot.snapshot_id:
            reasons.append("snapshot identity changed")
        if (
            state.rubric_id != current_rubric.id
            or state.rubric_version != current_rubric.version
        ):
            reasons.append("rubric identity changed")
        return reasons

    def _session(
        self,
        row: sqlite3.Row,
        *,
        connection: sqlite3.Connection | None = None,
        require_snapshot: bool = True,
    ) -> ReviewSession:
        workflow = WorkflowState(row["workflow_state"])
        state_payload = json.loads(row["state_json"])
        if row["state_schema_version"] == 1:
            for pending in state_payload.get("pending_answers", []):
                answer = pending.get("answer")
                if isinstance(answer, dict) and not answer.get("answer_id"):
                    answer["answer_id"] = pending.get("answer_id")
        state = RemediationState.model_validate(state_payload)
        state.state_schema_version = row["state_schema_version"]
        state.evaluation_revision = row["evaluation_revision"]
        state.snapshot_id = row["snapshot_id"]
        state.parser_fingerprint = row["parser_fingerprint"]
        state.normalized_hash = row["normalized_hash"]
        state.source_snapshot = None
        if row["snapshot_id"] is not None:
            if connection is None:
                with closing(self._connect()) as snapshot_connection:
                    snapshot = self._get_snapshot(
                        snapshot_connection, row["snapshot_id"]
                    )
            else:
                snapshot = self._get_snapshot(connection, row["snapshot_id"])
            if snapshot is None and require_snapshot:
                raise ValueError("review session's durable source snapshot is missing")
            if snapshot is not None:
                snapshot = rebind_snapshot_origin(snapshot, state.source_path)
            state.source_snapshot = snapshot
        if connection is None:
            with closing(self._connect()) as artifact_connection:
                state.criterion_evaluations = self._get_evaluation_artifacts(
                    artifact_connection, row["review_session_id"]
                )
        else:
            state.criterion_evaluations = self._get_evaluation_artifacts(
                connection, row["review_session_id"]
            )
        return ReviewSession(
            review_session_id=row["review_session_id"],
            session_version=row["session_version"],
            workflow_state=workflow,
            next_action=next_action_for(workflow),
            state=state,
            workspace_fingerprint=row["workspace_fingerprint"],
            local_user=row["local_user"],
            client_binding=ClientBinding(
                client_name=row["client_name"],
                client_version=row["client_version"],
                host_conversation_id=row["host_conversation_id"],
            ),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            expires_at=row["expires_at"],
        )

    @staticmethod
    def _summary(
        session: ReviewSession, incompatibility_reasons: list[str] | None = None
    ) -> ReviewSessionSummary:
        reasons = incompatibility_reasons or []
        return ReviewSessionSummary(
            review_session_id=session.review_session_id,
            display_name=session.state.display_name,
            source_path=session.state.source_path,
            source_sha256=session.state.source_sha256,
            current_band=session.state.assessment.band,
            workflow_state=session.workflow_state,
            verified_answer_count=len(session.state.verified_answers),
            pending_answer_count=len(session.state.pending_answers),
            client_name=session.client_binding.client_name,
            updated_at=session.updated_at,
            compatible=not reasons,
            incompatibility_reasons=reasons,
        )


def turn_for_session(session: ReviewSession) -> RemediationTurn:
    """Derive the current turn from durable state, honouring stored workflow.

    Everything a turn reports is recomputed from the persisted
    `RemediationState`, so a response can never disagree with what was actually
    saved. The one exception is `force_checkpoint`, which is caller intent
    rather than a property of the state; the persisted workflow state records
    it, so it wins here.
    """
    turn = current_turn(session.state)
    if (
        session.workflow_state is WorkflowState.CHECKPOINT_REQUIRED
        and not turn.checkpoint_due
    ):
        return turn.model_copy(
            update={
                "checkpoint_due": True,
                "checkpoint_reason": "explicit",
                "next_question": None,
            }
        )
    return turn


def status_for(session: ReviewSession) -> ReviewStatus:
    turn = turn_for_session(session)
    return ReviewStatus(
        review_session_id=session.review_session_id,
        session_version=session.session_version,
        workflow_state=session.workflow_state,
        next_action=session.next_action,
        next_question=(
            turn.next_question.model_dump() if turn.next_question is not None else None
        ),
        source_path=session.state.source_path,
        source_sha256=session.state.source_sha256,
        current_band=session.state.assessment.band,
        verified_answer_count=len(session.state.verified_answers),
        pending_answer_count=len(session.state.pending_answers),
        client_binding=session.client_binding,
    )


def _binding_changed(current: ClientBinding, requested: ClientBinding) -> bool:
    comparable = (
        "client_name",
        "client_version",
        "host_conversation_id",
    )
    return any(
        getattr(current, key) is not None
        and getattr(requested, key) is not None
        and getattr(current, key) != getattr(requested, key)
        for key in comparable
    )
