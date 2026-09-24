from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from threading import Lock

from pydantic import BaseModel, Field

from forge.extract.batch import ExtractionBatch, verify_extraction_batch
from forge.extract.delta import (
    DeltaExtractionPlan,
    PendingDeltaAnswer,
    build_delta_extraction_plan,
    merge_criterion_patches,
    parse_delta_extraction,
    verify_delta_extraction,
)
from forge.extract.models import CriterionExtraction
from forge.ingest.batching import batch_document
from forge.ingest.models import ProductContextTerm, SupplementalAnswer
from forge.rubric.loader import load_rubric
from forge.score.edge_coverage import (
    EdgeCaseCoverageLedger,
    apply_coverage_answers,
    edge_case_type,
    next_uncovered_item,
    render_coverage_question,
    verify_coverage_ledger,
)
from forge.score.engine import Assessment, score
from forge.score.planner import Question, document_display_name, plan_question_queue
from forge.score.report import NarrativeReport, build_narrative_report
from forge.service import prepare_assessment_input


class CheckpointPolicy(BaseModel):
    max_pending_answers: int = Field(default=5, ge=1, le=20)


class RemediationState(BaseModel):
    source_path: str
    source_sha256: str
    rubric_name: str = "prd"
    rubric_id: str
    rubric_version: str
    baseline_fingerprint: str
    runs: list[list[CriterionExtraction]]
    assessment: Assessment
    report: NarrativeReport
    question_queue: list[Question]
    verified_answers: list[SupplementalAnswer] = Field(default_factory=list)
    pending_answers: list[PendingDeltaAnswer] = Field(default_factory=list)
    uncredited_answers: list[SupplementalAnswer] = Field(default_factory=list)
    product_context: list[ProductContextTerm] = Field(default_factory=list)
    framing: str | None = None
    display_name: str
    edge_case_coverage: EdgeCaseCoverageLedger | None = None
    run_count: int
    expected_run_count: int
    client_models: list[str] = Field(default_factory=list)
    revision: int = 0
    delta_extraction_count: int = 0
    delta_input_characters: int = 0
    checkpoint_policy: CheckpointPolicy = Field(default_factory=CheckpointPolicy)


class RemediationTurn(BaseModel):
    state: RemediationState
    next_question: Question | None
    checkpoint_due: bool
    checkpoint_reason: str | None
    pending_answer_count: int
    verified_answer_count: int
    score_is_current: bool


class RemediationCheckpointResult(BaseModel):
    state: RemediationState
    next_question: Question | None
    credited_answer_ids: list[str]
    uncredited_answer_ids: list[str]
    previous_band: str
    current_band: str


def _source_digest(source_path: str) -> str:
    path = Path(source_path).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"document not found: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _baseline_fingerprint(
    source_sha256: str,
    rubric_id: str,
    rubric_version: str,
    product_context: list[ProductContextTerm],
) -> str:
    digest = hashlib.sha256()
    digest.update(source_sha256.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(rubric_id.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(rubric_version.encode("utf-8"))
    for term in product_context:
        digest.update(b"\x00context\x00")
        digest.update(term.model_dump_json().encode("utf-8"))
    return digest.hexdigest()[:32]


def _assert_current_source(state: RemediationState) -> None:
    current = _source_digest(state.source_path)
    if current != state.source_sha256:
        raise ValueError(
            "the source PRD changed after remediation began; start a new assessment"
        )
    rubric = load_rubric(state.rubric_name)
    if rubric.id != state.rubric_id or rubric.version != state.rubric_version:
        raise ValueError(
            "the rubric changed after remediation began; start a new assessment"
        )


def _decorate_edge_question(
    queue: list[Question],
    assessment: Assessment,
    display_name: str,
    coverage: EdgeCaseCoverageLedger | None,
) -> None:
    if coverage is None:
        return
    uncovered = next_uncovered_item(coverage)
    if uncovered is None:
        return
    question = next(
        (
            item
            for item in queue
            if item.criterion_id == "edge_cases_and_states"
        ),
        None,
    )
    if question is None:
        return
    edge = edge_case_type(uncovered.edge_case_id)
    question.target_field = "edge_case_coverage"
    question.question = render_coverage_question(display_name, uncovered)
    question.base_question = edge.question
    question.answer_requirements = [
        "State the expected behavior for this requirement and edge case, "
        "including the user-visible result and recovery path."
    ]
    question.band_if_answered = assessment.band
    question.requirement_quote = uncovered.requirement_quote
    question.edge_case_id = uncovered.edge_case_id
    question.taxonomy_version = coverage.taxonomy_version


def _snapshot(
    state: RemediationState,
    runs: list[list[CriterionExtraction]],
    verified_answers: list[SupplementalAnswer],
    coverage: EdgeCaseCoverageLedger | None,
) -> tuple[Assessment, NarrativeReport, list[Question], EdgeCaseCoverageLedger | None]:
    rubric = load_rubric(state.rubric_name)
    document, _ = prepare_assessment_input(
        state.source_path,
        state.rubric_name,
        verified_answers,
        state.product_context,
    )
    verified_coverage = (
        verify_coverage_ledger(
            document,
            apply_coverage_answers(coverage, verified_answers),
        )
        if coverage is not None
        else None
    )
    assessment = score(rubric, runs, edge_case_coverage=verified_coverage)
    queue = plan_question_queue(
        rubric,
        assessment,
        display_name=state.display_name,
        framing=state.framing,
    )
    _decorate_edge_question(queue, assessment, state.display_name, verified_coverage)
    report = build_narrative_report(
        assessment,
        queue[:1],
        run_count=len(runs),
        expected_run_count=rubric.extraction_runs,
    )
    return assessment, report, queue, verified_coverage


def begin_remediation(
    source_path: str,
    extraction_json: str,
    *,
    rubric_name: str = "prd",
    product_context: list[ProductContextTerm] | None = None,
    framing: str | None = None,
    edge_case_coverage: EdgeCaseCoverageLedger | None = None,
    client_models: list[str] | None = None,
    display_name: str | None = None,
    checkpoint_policy: CheckpointPolicy | None = None,
) -> RemediationTurn:
    terms = product_context or []
    document, rubric = prepare_assessment_input(
        source_path, rubric_name, [], terms
    )
    payload = json.loads(extraction_json)
    if "runs" not in payload:
        payload = {"runs": [payload]}
    runs = verify_extraction_batch(
        batch_document(document), ExtractionBatch.model_validate(payload), rubric
    )
    source_sha = _source_digest(source_path)
    resolved_display_name = display_name or document_display_name(source_path)
    assessment = score(rubric, runs, edge_case_coverage=edge_case_coverage)
    queue = plan_question_queue(
        rubric,
        assessment,
        display_name=resolved_display_name,
        framing=framing,
    )
    _decorate_edge_question(queue, assessment, resolved_display_name, edge_case_coverage)
    report = build_narrative_report(
        assessment,
        queue[:1],
        run_count=len(runs),
        expected_run_count=rubric.extraction_runs,
    )
    state = RemediationState(
        source_path=str(Path(source_path).expanduser().resolve()),
        source_sha256=source_sha,
        rubric_name=rubric_name,
        rubric_id=rubric.id,
        rubric_version=rubric.version,
        baseline_fingerprint=_baseline_fingerprint(
            source_sha, rubric.id, rubric.version, terms
        ),
        runs=runs,
        assessment=assessment,
        report=report,
        question_queue=queue,
        product_context=terms,
        framing=queue[0].framing if queue else rubric.default_framing,
        display_name=resolved_display_name,
        edge_case_coverage=edge_case_coverage,
        run_count=len(runs),
        expected_run_count=rubric.extraction_runs,
        client_models=client_models or [],
        checkpoint_policy=checkpoint_policy or CheckpointPolicy(),
    )
    return _turn(state)


def _checkpoint_reason(state: RemediationState) -> str | None:
    if state.pending_answers and not state.question_queue:
        return "queue_exhausted"
    if len(state.pending_answers) >= state.checkpoint_policy.max_pending_answers:
        return "pending_limit"
    pending_by_criterion: dict[str, set[str]] = {}
    for pending in state.pending_answers:
        if pending.target_field is not None:
            pending_by_criterion.setdefault(
                pending.answer.criterion_id, set()
            ).add(pending.target_field)
    for result in state.assessment.criteria:
        if not result.gate_triggered:
            continue
        if set(result.missing).issubset(
            pending_by_criterion.get(result.criterion_id, set())
        ):
            return "failed_gate_fields_collected"
    return None


def _turn(
    state: RemediationState,
    *,
    forced_reason: str | None = None,
) -> RemediationTurn:
    reason = forced_reason or _checkpoint_reason(state)
    return RemediationTurn(
        state=state,
        next_question=None if reason else (state.question_queue[0] if state.question_queue else None),
        checkpoint_due=reason is not None,
        checkpoint_reason=reason,
        pending_answer_count=len(state.pending_answers),
        verified_answer_count=len(state.verified_answers),
        score_is_current=not state.pending_answers,
    )


def record_answer(
    state: RemediationState,
    answer: str,
    *,
    force_checkpoint: bool = False,
) -> RemediationTurn:
    _assert_current_source(state)
    if not state.question_queue:
        raise ValueError("no remediation question remains")
    question = state.question_queue[0]
    supplemental = SupplementalAnswer(
        criterion_id=question.criterion_id,
        answer=answer,
        requirement_quote=question.requirement_quote,
        edge_case_id=question.edge_case_id,
        taxonomy_version=question.taxonomy_version,
    )
    pending = PendingDeltaAnswer(
        answer_id=uuid.uuid4().hex,
        target_field=question.target_field,
        answer=supplemental,
    )
    updated = state.model_copy(deep=True)
    updated.pending_answers.append(pending)
    updated.question_queue.pop(0)
    return _turn(updated, forced_reason="explicit" if force_checkpoint else None)


def prepare_checkpoint(state: RemediationState) -> DeltaExtractionPlan:
    _assert_current_source(state)
    rubric = load_rubric(state.rubric_name)
    return build_delta_extraction_plan(
        state.baseline_fingerprint,
        rubric,
        state.pending_answers,
        state.runs[0],
    )


def apply_checkpoint(
    state: RemediationState,
    delta_json: str,
) -> RemediationCheckpointResult:
    _assert_current_source(state)
    plan = prepare_checkpoint(state)
    rubric = load_rubric(state.rubric_name)
    delta = parse_delta_extraction(delta_json)
    patches = verify_delta_extraction(plan, delta, rubric, state.pending_answers)
    runs = merge_criterion_patches(state.runs, patches)
    credited_block_ids = {
        field.evidence.source_block_id
        for patch in patches
        for field in patch.fields
        if field.evidence is not None and field.evidence.source_block_id is not None
    }
    credited = [
        pending
        for pending in state.pending_answers
        if (
            f"supplemental-answer-{pending.answer_id}" in credited_block_ids
            or (
                pending.answer.requirement_quote is not None
                and pending.answer.edge_case_id is not None
                and pending.answer.taxonomy_version is not None
            )
        )
    ]
    uncredited = [
        pending
        for pending in state.pending_answers
        if f"supplemental-answer-{pending.answer_id}" not in credited_block_ids
    ]
    verified_answers = [
        *state.verified_answers,
        *(pending.answer for pending in credited),
    ]
    assessment, report, queue, coverage = _snapshot(
        state,
        runs,
        verified_answers,
        state.edge_case_coverage,
    )
    updated = state.model_copy(
        update={
            "runs": runs,
            "assessment": assessment,
            "report": report,
            "question_queue": queue,
            "verified_answers": verified_answers,
            "pending_answers": [],
            "uncredited_answers": [
                *state.uncredited_answers,
                *(pending.answer for pending in uncredited),
            ],
            "edge_case_coverage": coverage,
            "revision": state.revision + 1,
            "delta_extraction_count": state.delta_extraction_count + 1,
            "delta_input_characters": (
                state.delta_input_characters + plan.input_character_count
            ),
        },
        deep=True,
    )
    return RemediationCheckpointResult(
        state=updated,
        next_question=queue[0] if queue else None,
        credited_answer_ids=[pending.answer_id for pending in credited],
        uncredited_answer_ids=[pending.answer_id for pending in uncredited],
        previous_band=state.assessment.band,
        current_band=assessment.band,
    )


class RemediationSessionStore:
    def __init__(self, *, ttl_seconds: int = 86_400) -> None:
        self._ttl_seconds = ttl_seconds
        self._sessions: dict[str, tuple[float, RemediationState]] = {}
        self._lock = Lock()

    def create(self, state: RemediationState) -> str:
        session_id = uuid.uuid4().hex
        with self._lock:
            self._sessions[session_id] = (time.monotonic(), state)
        return session_id

    def get(self, session_id: str) -> RemediationState:
        with self._lock:
            item = self._sessions.get(session_id)
            if item is None:
                raise KeyError(f"unknown remediation session {session_id!r}")
            created, state = item
            if time.monotonic() - created > self._ttl_seconds:
                del self._sessions[session_id]
                raise KeyError(f"expired remediation session {session_id!r}")
            return state

    def put(self, session_id: str, state: RemediationState) -> None:
        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(f"unknown remediation session {session_id!r}")
            self._sessions[session_id] = (time.monotonic(), state)

    def delete(self, session_id: str) -> None:
        with self._lock:
            if self._sessions.pop(session_id, None) is None:
                raise KeyError(f"unknown remediation session {session_id!r}")
