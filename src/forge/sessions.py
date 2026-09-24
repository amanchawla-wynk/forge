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

from pydantic import BaseModel

from forge.remediation import RemediationState, RemediationTurn, current_turn


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
            type="run_final_assessment", tool="assess_prd"
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
        self.ttl_seconds = ttl_seconds
        self._lock = Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        # `isolation_level=None` puts sqlite3 in autocommit mode so this module
        # controls transactions explicitly with BEGIN IMMEDIATE. Without it,
        # Python opens implicit transactions that make the read-modify-write in
        # `update()` race against a concurrent chat.
        connection = sqlite3.connect(self.path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(
                """
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
                    state_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS review_sessions_source_idx
                  ON review_sessions(source_sha256, workspace_fingerprint, local_user);
                CREATE TABLE IF NOT EXISTS review_operations (
                    review_session_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    result_json TEXT NOT NULL,
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

    def create(
        self,
        state: RemediationState,
        *,
        workspace_root: str | None = None,
        local_user: str | None = None,
        client_binding: ClientBinding | None = None,
    ) -> ReviewSession:
        now = time.time()
        review_id = "rvw_" + uuid.uuid4().hex
        binding = client_binding or ClientBinding()
        workflow = workflow_for_turn(current_turn(state))
        workspace = workspace_fingerprint(state.source_path, workspace_root)
        user = local_user_identity(local_user)
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    INSERT INTO review_sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        state.model_dump_json(),
                        now,
                        now,
                        now + self.ttl_seconds,
                    ),
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
        if row is None:
            raise KeyError(f"unknown review_session_id {review_session_id!r}")
        if row["expires_at"] < time.time():
            self.delete(review_session_id)
            raise KeyError(f"expired review_session_id {review_session_id!r}")
        return self._session(row)

    def find(
        self,
        source_path: str,
        *,
        workspace_root: str | None = None,
        local_user: str | None = None,
    ) -> list[ReviewSessionSummary]:
        source = Path(source_path).expanduser().resolve()
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"document not found: {source}")
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        workspace = workspace_fingerprint(str(source), workspace_root)
        user = local_user_identity(local_user)
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
        return [self._summary(self._session(row)) for row in rows]

    def operation_result(self, review_session_id: str, operation_id: str) -> str | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT result_json FROM review_operations
                WHERE review_session_id = ? AND operation_id = ?
                """,
                (review_session_id, operation_id),
            ).fetchone()
        return None if row is None else str(row["result_json"])

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
    ) -> ReviewSession:
        if not operation_id.strip():
            raise ValueError("operation_id must not be blank")
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                cached = connection.execute(
                    """
                    SELECT result_json FROM review_operations
                    WHERE review_session_id = ? AND operation_id = ?
                    """,
                    (review_session_id, operation_id),
                ).fetchone()
                if cached is not None:
                    # Idempotent replay: the same operation_id already ran, so
                    # return the stored session instead of applying it twice.
                    connection.rollback()
                    return self.get(review_session_id)
                row = connection.execute(
                    "SELECT * FROM review_sessions WHERE review_session_id = ?",
                    (review_session_id,),
                ).fetchone()
                if row is None:
                    raise KeyError(f"unknown review_session_id {review_session_id!r}")
                if row["session_version"] != expected_version:
                    raise ValueError(
                        "stale session_version: this review was updated in another "
                        f"conversation (expected {row['session_version']}, received "
                        f"{expected_version}). Refresh before continuing."
                    )
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
                        state_json = ?, client_name = ?, client_version = ?,
                        host_conversation_id = ?, updated_at = ?, expires_at = ?
                    WHERE review_session_id = ? AND session_version = ?
                    """,
                    (
                        version,
                        workflow_state.value,
                        state.model_dump_json(),
                        binding.client_name,
                        binding.client_version,
                        binding.host_conversation_id,
                        now,
                        now + self.ttl_seconds,
                        review_session_id,
                        expected_version,
                    ),
                )
                connection.execute(
                    "INSERT INTO review_operations VALUES (?, ?, ?, ?)",
                    (review_session_id, operation_id, result_json, now),
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
        changed = _binding_changed(session.client_binding, client_binding)
        if changed and not confirm_client_change:
            raise ValueError(
                "client binding changed; explicit confirm_client_change is required"
            )
        workflow = workflow_for_turn(current_turn(session.state))
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
        )

    def delete(self, review_session_id: str) -> None:
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                "DELETE FROM review_sessions WHERE review_session_id = ?",
                (review_session_id,),
            )
        if cursor.rowcount == 0:
            raise KeyError(f"unknown review_session_id {review_session_id!r}")

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

    def _session(self, row: sqlite3.Row) -> ReviewSession:
        workflow = WorkflowState(row["workflow_state"])
        return ReviewSession(
            review_session_id=row["review_session_id"],
            session_version=row["session_version"],
            workflow_state=workflow,
            next_action=next_action_for(workflow),
            state=RemediationState.model_validate_json(row["state_json"]),
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
    def _summary(session: ReviewSession) -> ReviewSessionSummary:
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
