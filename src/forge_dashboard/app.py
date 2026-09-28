"""Local-only FastAPI backend for the optional Forge dashboard.

Run with `forge-dashboard-api` (installed by the `dashboard` extra) or
`uvicorn forge_dashboard.app:app --reload`. Binds to localhost by default.

This process accepts a per-request LLM API key from the browser (see
`docs/DECISIONS.md` D-033) and forwards it to LiteLLM for that request only.
It never writes the key to disk, a database, or a log.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel

from forge_dashboard.llm import LLMCallError, call_model
from forge_dashboard.models import (
    AssessRequest,
    CheckpointRequest,
    DashboardAssessmentResponse,
    DashboardCheckpointResponse,
    DashboardCheckpointResult,
    DashboardReviewState,
    DashboardRemediationTurn,
    DashboardTurnData,
    DashboardReviewDiscovery,
    DashboardReviewSummary,
    DashboardRevisionPreview,
    DashboardRevisionResponse,
    DashboardRevisionResult,
    LLMConfig,
    RecordAnswerRequest,
    ResumeReviewRequest,
    MaterializeRevisionRequest,
    RevisionPreviewRequest,
    UploadResponse,
)
from forge.remediation import (
    FinalVerification,
    RemediationState,
    apply_checkpoint,
    assert_current_source,
    current_turn,
    prepare_checkpoint,
    record_answer,
)
from forge.sessions import (
    ClientBinding,
    ReviewSessionRepository,
    WorkflowState,
    turn_for_session,
    workflow_for_turn,
    operation_digest,
    next_action_for,
)
from forge.service import AssessmentResponse
from forge.revise import (
    RevisionResult,
    approve_revision_plan,
    materialize_integrated_prd_revision,
    preview_integrated_revision,
)
from forge_dashboard.runner import (
    ExtractionFailed,
    run_assessment_with_remediation,
)
from forge_dashboard.storage import DocumentStore, StoredDocument

_VERIFY_PROMPT = "Reply with exactly the single word: OK"
_MAX_UPLOAD_BYTES = int(
    os.environ.get("FORGE_DASHBOARD_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024))
)


class VerifyLLMResponse(BaseModel):
    ok: bool
    model: str

app = FastAPI(
    title="Forge Dashboard API",
    description=(
        "Local-only bring-your-own-key adapter around Forge's PRD assessment "
        "core. Not a hosted service; see docs/DECISIONS.md D-033."
    ),
    version="0.1.0",
)

_allowed_origins = [
    origin.strip()
    for origin in os.environ.get(
        "FORGE_DASHBOARD_ALLOWED_ORIGINS", "http://localhost:3000"
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

_store = DocumentStore()
_review_repository: ReviewSessionRepository | None = None


def _reviews() -> ReviewSessionRepository:
    global _review_repository
    if _review_repository is None:
        _review_repository = ReviewSessionRepository()
    return _review_repository


def _require_workflow(
    workflow_state: WorkflowState, allowed: set[WorkflowState], operation: str
) -> None:
    if workflow_state not in allowed:
        raise ValueError(
            f"{operation} is not allowed while this review is "
            f"'{workflow_state.value}'"
        )


def _assert_document_matches_session(stored: StoredDocument, session) -> None:
    stored_path = stored.path.expanduser().resolve()
    session_path = Path(session.state.source_path).expanduser().resolve()
    if stored_path != session_path:
        raise ValueError("document belongs to a different review source")
    assert_current_source(session.state, str(stored_path))


def _assessment_from_session(
    stored: StoredDocument, document_id: str, session
) -> DashboardAssessmentResponse:
    turn = turn_for_session(session)
    disputed = [
        item.criterion_id
        for item in session.state.assessment.criteria
        if item.agreement < 1.0
    ]
    warnings = [
        "This assessment uses Forge's source-backed cross-industry expert "
        "baseline. It is operational without company data, but has not been "
        "validated against your organization's independent reviewer labels."
    ]
    snapshot = session.state.source_snapshot
    if snapshot is not None and snapshot.document.visual_assets:
        warnings.append(
            f"Detected {len(snapshot.document.visual_assets)} visual asset(s). Text "
            "found in the document may receive credit, but image and diagram "
            "interpretation is advisory and is not yet included in scoring."
        )
    if session.state.run_count < session.state.expected_run_count:
        warnings.append(
            f"Only {session.state.run_count} extraction run(s) were supplied; "
            f"the rubric expects {session.state.expected_run_count}. Confidence "
            "does not measure test/retest stability."
        )
    if session.state.product_context:
        warnings.append(
            "Product terminology context was used only to disambiguate names; "
            "it was excluded from evidence verification and scoring."
        )
    if session.state.edge_case_coverage is not None:
        coverage = session.state.edge_case_coverage
        covered = sum(
            item.status.value in {"covered", "not_applicable"}
            for item in coverage.items
        )
        warnings.append(
            f"Edge-case taxonomy {coverage.taxonomy_version} covers {covered} of "
            f"{len(coverage.items)} applicable/assessed pairs. Completeness is "
            "relative to this declared taxonomy, not every imaginable edge case."
        )
    return DashboardAssessmentResponse(
        source_path=stored.filename,
        document_id=document_id,
        report=session.state.report,
        deep_review=session.state.deep_review,
        assessment=session.state.assessment,
        next_question=turn.next_question,
        supplemental_answers=session.state.verified_answers,
        run_count=session.state.run_count,
        expected_run_count=session.state.expected_run_count,
        disputed_criteria=disputed,
        recommended_additional_runs=max(0, 5 - session.state.run_count)
        if disputed
        else 0,
        client_models=session.state.client_models,
        product_context=session.state.product_context,
        framing=session.state.framing,
        edge_case_coverage=session.state.edge_case_coverage,
        warnings=warnings,
        criterion_evaluations=session.state.criterion_evaluations,
        extraction_errors=[],
        review_session_id=session.review_session_id,
        session_version=session.session_version,
        workflow_state=session.workflow_state,
        next_action=session.next_action,
        question_mode=session.state.question_mode,
    )


def _generated_from_metadata(metadata: dict[str, object]) -> StoredDocument:
    try:
        return StoredDocument(
            document_id=str(metadata["generated_document_id"]),
            filename=str(metadata["generated_filename"]),
            path=Path(str(metadata["generated_path"])),
        )
    except KeyError as error:
        raise ValueError("pending revision operation metadata is incomplete") from error


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/llm/verify", response_model=VerifyLLMResponse)
async def verify_llm(config: LLMConfig) -> VerifyLLMResponse:
    """Make one minimal call to prove the key/model combination works.

    Used by the "Connect model" dialog to show a real connected/not-connected
    status instead of just "a key was typed." Never persists the key; see
    docs/DECISIONS.md D-033/D-034.
    """
    try:
        completion = await call_model(config, _VERIFY_PROMPT, max_tokens=5)
    except LLMCallError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return VerifyLLMResponse(ok=True, model=completion.model)


@app.post("/api/documents", response_model=UploadResponse)
async def upload_document(file: UploadFile = File(...)) -> UploadResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="a filename is required")
    content = await file.read(_MAX_UPLOAD_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="the uploaded file is empty")
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"document exceeds the {_MAX_UPLOAD_BYTES}-byte upload limit",
        )
    try:
        stored = _store.save(file.filename, content)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return UploadResponse(
        document_id=stored.document_id,
        filename=stored.filename,
        source_type=stored.path.suffix.removeprefix("."),
    )


@app.post("/api/assessments", response_model=DashboardAssessmentResponse)
async def create_assessment(request: AssessRequest) -> DashboardAssessmentResponse:
    try:
        stored = _store.get(request.document_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    review_session_id = None
    creation_digest = None
    if request.operation_id is not None:
        creation_digest = operation_digest(
            "dashboard_start_review",
            {
                "source_sha256": hashlib.sha256(stored.path.read_bytes()).hexdigest(),
                "rubric_name": request.rubric_name,
                "provider": request.llm.provider,
                "model": request.llm.model,
                "supplemental_answers": [
                    item.model_dump(mode="json")
                    for item in request.supplemental_answers
                ],
                "product_context": [
                    item.model_dump(mode="json") for item in request.product_context
                ],
                "framing": request.framing,
                "edge_case_coverage": (
                    request.edge_case_coverage.model_dump(mode="json")
                    if request.edge_case_coverage is not None
                    else None
                ),
                "question_mode": request.question_mode,
            },
        )
        review_session_id = "rvw_" + hashlib.sha256(
            f"{request.operation_id}\x00{creation_digest}".encode("utf-8")
        ).hexdigest()
        try:
            existing = _reviews().get(review_session_id)
        except KeyError:
            pass
        else:
            _assert_document_matches_session(stored, existing)
            return _assessment_from_session(stored, request.document_id, existing)
        reservation = _reviews().reserve_creation(
            review_session_id, creation_digest
        )
        if reservation == "completed":
            existing = _reviews().get(review_session_id)
            return _assessment_from_session(stored, request.document_id, existing)

    matches = _reviews().find(
        str(stored.path),
        workspace_root=str(_store.root),
        rubric_name=request.rubric_name,
    )
    if any(match.compatible for match in matches) and not request.start_new:
        if review_session_id is not None and creation_digest is not None:
            _reviews().cancel_creation(review_session_id, creation_digest)
        raise HTTPException(
            status_code=409,
            detail=(
                "matching reviews exist; explicitly resume one, start a new "
                "review, or cancel"
            ),
        )

    try:
        result, remediation_state = await run_assessment_with_remediation(
            str(stored.path),
            request.llm,
            rubric_name=request.rubric_name,
            supplemental_answers=request.supplemental_answers,
            product_context=request.product_context,
            framing=request.framing,
            edge_case_coverage=request.edge_case_coverage,
            display_name=Path(stored.filename).stem,
            question_mode=request.question_mode,
        )
    except ExtractionFailed as error:
        if review_session_id is not None and creation_digest is not None:
            _reviews().cancel_creation(review_session_id, creation_digest)
        raise HTTPException(status_code=502, detail=str(error)) from error
    except (ValueError, FileNotFoundError) as error:
        if review_session_id is not None and creation_digest is not None:
            _reviews().cancel_creation(review_session_id, creation_digest)
        raise HTTPException(status_code=400, detail=str(error)) from error

    # Never return the server's local filesystem path to the browser.
    payload = result.model_dump()
    payload["source_path"] = stored.filename
    payload["document_id"] = stored.document_id
    try:
        session = (
            _reviews().create(
                remediation_state,
                review_session_id=review_session_id,
                workspace_root=str(_store.root),
                client_binding=ClientBinding(client_name="dashboard"),
            )
            if remediation_state is not None
            else None
        )
        if (
            session is not None
            and review_session_id is not None
            and creation_digest is not None
        ):
            _reviews().complete_creation(review_session_id, creation_digest)
        elif review_session_id is not None and creation_digest is not None:
            _reviews().cancel_creation(review_session_id, creation_digest)
    except BaseException:
        if review_session_id is not None and creation_digest is not None:
            _reviews().cancel_creation(review_session_id, creation_digest)
        raise
    if session is not None:
        return _assessment_from_session(stored, stored.document_id, session)
    payload["review_session_id"] = session.review_session_id if session else None
    payload["session_version"] = session.session_version if session else None
    payload["workflow_state"] = session.workflow_state if session else None
    payload["next_action"] = session.next_action if session else None
    payload["question_mode"] = (
        session.state.question_mode if session else request.question_mode
    )
    return DashboardAssessmentResponse.model_validate(payload)


@app.get(
    "/api/documents/{document_id}/reviews",
    response_model=DashboardReviewDiscovery,
)
def find_document_reviews(document_id: str) -> DashboardReviewDiscovery:
    try:
        stored = _store.get(document_id)
        matches = _reviews().find(
            str(stored.path), workspace_root=str(_store.root)
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ValueError, FileNotFoundError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return DashboardReviewDiscovery(
        document_id=document_id,
        matches=[
            DashboardReviewSummary(
                review_session_id=item.review_session_id,
                display_name=item.display_name,
                current_band=item.current_band,
                workflow_state=item.workflow_state,
                verified_answer_count=item.verified_answer_count,
                pending_answer_count=item.pending_answer_count,
                client_name=item.client_name,
                updated_at=item.updated_at,
                compatible=item.compatible,
                incompatibility_reasons=item.incompatibility_reasons,
            )
            for item in matches
        ],
        choices=["resume_review", "start_new_review", "cancel"],
    )


@app.post(
    "/api/documents/{document_id}/reviews/{review_session_id}/resume",
    response_model=DashboardAssessmentResponse,
)
def resume_document_review(
    document_id: str,
    review_session_id: str,
    request: ResumeReviewRequest,
) -> DashboardAssessmentResponse:
    try:
        stored = _store.get(document_id)
        session = _reviews().get(review_session_id)
        session = _reviews().resume(
            review_session_id,
            source_path=str(stored.path),
            client_binding=ClientBinding(client_name="dashboard"),
            confirm_client_change=request.confirm_client_change,
            expected_version=session.session_version,
            operation_id=request.operation_id,
            workspace_root=str(_store.root),
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ValueError, FileNotFoundError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return _assessment_from_session(stored, document_id, session)


@app.post(
    "/api/remediation/{session_id}/answers",
    response_model=DashboardRemediationTurn,
)
def record_remediation_answer(
    session_id: str, request: RecordAnswerRequest
) -> DashboardRemediationTurn:
    try:
        request_digest = operation_digest(
            "record_answer",
            {
                "answer": request.answer,
                "force_checkpoint": request.force_checkpoint,
                "question_id": request.question_id,
                "evaluation_revision": request.evaluation_revision,
            },
        )
        cached = _reviews().operation_result(
            session_id,
            request.operation_id,
            operation_type="record_answer",
            request_digest=request_digest,
        )
        if cached is not None:
            try:
                return DashboardRemediationTurn.model_validate_json(cached)
            except ValueError:
                # Compatibility with operation rows written before D-073.
                session = _reviews().get(session_id)
                return DashboardRemediationTurn(
                    review_session_id=session_id,
                    session_version=session.session_version,
                    workflow_state=session.workflow_state,
                    next_action=session.next_action,
                    turn=DashboardTurnData.model_validate(
                        turn_for_session(session).model_dump(exclude={"state"})
                    ),
                )
        session = _reviews().get(session_id)
        _require_workflow(
            session.workflow_state,
            {WorkflowState.AWAITING_ANSWER, WorkflowState.COLLECTING_ANSWERS},
            "record answer",
        )
        turn = record_answer(
            session.state,
            request.answer,
            force_checkpoint=request.force_checkpoint,
            question_id=request.question_id,
            evaluation_revision=request.evaluation_revision,
        )
        workflow_state = workflow_for_turn(turn)
        operation_response = DashboardRemediationTurn(
            review_session_id=session_id,
            session_version=request.session_version + 1,
            workflow_state=workflow_state,
            next_action=next_action_for(workflow_state),
            turn=DashboardTurnData.model_validate(
                turn.model_dump(exclude={"state"})
            ),
        )
        session = _reviews().update(
            session_id,
            expected_version=request.session_version,
            operation_id=request.operation_id,
            state=turn.state,
            workflow_state=workflow_state,
            event_type="answer_recorded",
            result_json=operation_response.model_dump_json(),
            event_payload={"checkpoint_due": turn.checkpoint_due},
            operation_type="record_answer",
            request_digest=request_digest,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ValueError, FileNotFoundError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    persisted = _reviews().operation_result(
        session_id,
        request.operation_id,
        operation_type="record_answer",
        request_digest=request_digest,
    )
    if persisted is None:
        raise HTTPException(
            status_code=500, detail="recorded answer operation was not persisted"
        )
    return DashboardRemediationTurn.model_validate_json(persisted)


@app.post(
    "/api/remediation/{session_id}/checkpoint",
    response_model=DashboardCheckpointResponse,
)
async def checkpoint_remediation(
    session_id: str, request: CheckpointRequest
) -> DashboardCheckpointResponse:
    pending_operation = False
    try:
        request_digest = operation_digest(
            "dashboard_checkpoint",
            {
                "session_version": request.session_version,
                "provider": request.llm.provider,
                "model": request.llm.model,
            },
        )
        operation = _reviews().operation_record(
            session_id,
            request.operation_id,
            operation_type="dashboard_checkpoint",
            request_digest=request_digest,
        )
        if operation is not None and operation["status"] == "completed":
            session = _reviews().get(session_id)
            return DashboardCheckpointResponse(
                review_session_id=session_id,
                session_version=session.session_version,
                workflow_state=session.workflow_state,
                next_action=session.next_action,
                result=DashboardCheckpointResult.model_validate_json(
                    operation["result_json"]
                ),
            )
        session = _reviews().get(session_id)
        _require_workflow(
            session.workflow_state,
            {WorkflowState.CHECKPOINT_REQUIRED, WorkflowState.AWAITING_DELTA_EXTRACTION},
            "checkpoint",
        )
        if operation is None:
            _reviews().reserve_operation(
                session_id,
                expected_version=request.session_version,
                operation_id=request.operation_id,
                operation_type="dashboard_checkpoint",
                request_digest=request_digest,
                metadata={"stage": "reserved"},
            )
            metadata = {"stage": "reserved"}
        else:
            metadata = operation["metadata"]
        pending_operation = True
        plan = prepare_checkpoint(session.state)
        if metadata.get("stage") == "inference_completed":
            completion_text = str(metadata["completion_text"])
        else:
            completion = await call_model(
                request.llm,
                plan.extraction_prompt,
                max_tokens=4_000,
                temperature=0,
            )
            completion_text = completion.text
            metadata = {
                "stage": "inference_completed",
                "completion_text": completion_text,
            }
            _reviews().update_operation_metadata(
                session_id,
                request.operation_id,
                operation_type="dashboard_checkpoint",
                request_digest=request_digest,
                metadata=metadata,
            )
        result = apply_checkpoint(session.state, completion_text)
        turn = current_turn(result.state)
        session = _reviews().update(
            session_id,
            expected_version=request.session_version,
            operation_id=request.operation_id,
            state=result.state,
            workflow_state=workflow_for_turn(turn),
            event_type="checkpoint_applied",
            result_json=DashboardCheckpointResult(
                state=DashboardReviewState(
                    assessment=result.state.assessment,
                    report=result.state.report,
                    deep_review=result.state.deep_review,
                    evaluation_revision=result.state.evaluation_revision,
                    verified_answers=result.state.verified_answers,
                    framing=result.state.framing,
                    edge_case_coverage=result.state.edge_case_coverage,
                ),
                next_question=result.next_question,
                credited_answer_ids=result.credited_answer_ids,
                uncredited_answer_ids=result.uncredited_answer_ids,
                previous_band=result.previous_band,
                current_band=result.current_band,
            ).model_dump_json(),
            event_payload={
                "credited_answer_ids": result.credited_answer_ids,
                "uncredited_answer_ids": result.uncredited_answer_ids,
            },
            operation_type="dashboard_checkpoint",
            request_digest=request_digest,
            complete_reserved=True,
        )
    except KeyError as error:
        if pending_operation:
            _reviews().cancel_operation(session_id, request.operation_id)
        raise HTTPException(status_code=404, detail=str(error)) from error
    except LLMCallError as error:
        if pending_operation:
            _reviews().cancel_operation(session_id, request.operation_id)
        raise HTTPException(status_code=502, detail=str(error)) from error
    except (ValueError, FileNotFoundError) as error:
        if pending_operation:
            _reviews().cancel_operation(session_id, request.operation_id)
        raise HTTPException(status_code=400, detail=str(error)) from error
    return DashboardCheckpointResponse(
        review_session_id=session_id,
        session_version=session.session_version,
        workflow_state=session.workflow_state,
        next_action=session.next_action,
        result=DashboardCheckpointResult(
            state=DashboardReviewState(
                assessment=result.state.assessment,
                report=result.state.report,
                deep_review=result.state.deep_review,
                evaluation_revision=result.state.evaluation_revision,
                verified_answers=result.state.verified_answers,
                framing=result.state.framing,
                edge_case_coverage=result.state.edge_case_coverage,
            ),
            next_question=result.next_question,
            credited_answer_ids=result.credited_answer_ids,
            uncredited_answer_ids=result.uncredited_answer_ids,
            previous_band=result.previous_band,
            current_band=result.current_band,
        ),
    )


@app.delete("/api/remediation/{session_id}")
def delete_remediation(session_id: str) -> dict[str, object]:
    try:
        _reviews().delete(session_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"review_session_id": session_id, "deleted": True}


@app.post(
    "/api/documents/{document_id}/revisions/preview",
    response_model=DashboardRevisionPreview,
)
def preview_revision(
    document_id: str, request: RevisionPreviewRequest
) -> DashboardRevisionPreview:
    pending_operation = False
    plan_id: str | None = None
    try:
        stored = _store.get(document_id)
        session = _reviews().get(request.review_session_id)
        _assert_document_matches_session(stored, session)
        request_digest = operation_digest(
            "preview_revision",
            {
                "document_id": document_id,
                "section_overrides": request.section_overrides,
            },
        )
        operation = _reviews().operation_record(
            request.review_session_id,
            request.operation_id,
            operation_type="preview_revision",
            request_digest=request_digest,
        )
        if operation is not None and operation["status"] == "completed":
            return DashboardRevisionPreview.model_validate_json(
                operation["result_json"]
            )
        _require_workflow(
            session.workflow_state,
            {WorkflowState.REVISION_READY},
            "preview revision",
        )
        if operation is None:
            _reviews().reserve_operation(
                request.review_session_id,
                expected_version=request.session_version,
                operation_id=request.operation_id,
                operation_type="preview_revision",
                request_digest=request_digest,
                metadata={"stage": "reserved"},
            )
            metadata = {"stage": "reserved"}
        else:
            metadata = operation["metadata"]
        pending_operation = True
        if metadata.get("stage") == "plan_saved":
            plan_id = str(metadata["plan_id"])
            planned_document_id, plan = _store.get_revision_plan(plan_id)
            if planned_document_id != document_id:
                raise ValueError("pending revision plan belongs to a different document")
        else:
            plan_id = _store.revision_plan_id(
                request.review_session_id, request.operation_id
            )
            try:
                planned_document_id, plan = _store.get_revision_plan(plan_id)
                if planned_document_id != document_id:
                    raise ValueError(
                        "pending revision plan belongs to a different document"
                    )
            except KeyError:
                plan = preview_integrated_revision(
                    session.state.source_path,
                    session.state.verified_answers,
                    section_overrides=request.section_overrides,
                )
                _store.save_revision_plan(document_id, plan, plan_id=plan_id)
            _reviews().update_operation_metadata(
                request.review_session_id,
                request.operation_id,
                operation_type="preview_revision",
                request_digest=request_digest,
                metadata={"stage": "plan_saved", "plan_id": plan_id},
            )
        response = DashboardRevisionPreview(
            plan_id=plan_id,
            plan_digest=plan.plan_digest,
            source_sha256=plan.source_sha256,
            edits=plan.edits,
            review_session_id=session.review_session_id,
            session_version=request.session_version + 1,
            workflow_state=WorkflowState.AWAITING_REVISION_APPROVAL,
            next_action=next_action_for(WorkflowState.AWAITING_REVISION_APPROVAL),
        )
        previewed_state = session.state.model_copy(
            update={"revision_plan": plan}, deep=True
        )
        session = _reviews().update(
            request.review_session_id,
            expected_version=request.session_version,
            operation_id=request.operation_id,
            state=previewed_state,
            workflow_state=WorkflowState.AWAITING_REVISION_APPROVAL,
            event_type="revision_previewed",
            result_json=response.model_dump_json(),
            event_payload={"plan_id": plan_id, "plan_digest": plan.plan_digest},
            operation_type="preview_revision",
            request_digest=request_digest,
            complete_reserved=True,
        )
    except KeyError as error:
        if pending_operation:
            if plan_id is not None:
                try:
                    _store.delete_revision_plan(plan_id)
                except KeyError:
                    pass
            _reviews().cancel_operation(
                request.review_session_id, request.operation_id
            )
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ValueError, FileNotFoundError) as error:
        if pending_operation:
            if plan_id is not None:
                try:
                    _store.delete_revision_plan(plan_id)
                except KeyError:
                    pass
            _reviews().cancel_operation(
                request.review_session_id, request.operation_id
            )
        raise HTTPException(status_code=400, detail=str(error)) from error
    return response.model_copy(
        update={
            "session_version": session.session_version,
            "workflow_state": session.workflow_state,
            "next_action": session.next_action,
        }
    )


@app.post(
    "/api/documents/{document_id}/revisions",
    response_model=DashboardRevisionResponse,
)
async def create_revision(
    document_id: str, request: MaterializeRevisionRequest
) -> DashboardRevisionResponse:
    pending_operation = False
    metadata: dict[str, object] = {}
    generated: StoredDocument | None = None
    try:
        stored = _store.get(document_id)
        original_session = _reviews().get(request.review_session_id)
        _assert_document_matches_session(stored, original_session)
        if request.rubric_name != original_session.state.rubric_name:
            raise ValueError("final assessment must use the originating review rubric")
        request_digest = operation_digest(
            "materialize_revision",
            {
                "document_id": document_id,
                "plan_id": request.plan_id,
                "actions": request.actions,
                "provider": request.llm.provider,
                "model": request.llm.model,
                "rubric_name": request.rubric_name,
            },
        )
        operation = _reviews().operation_record(
            request.review_session_id,
            request.operation_id,
            operation_type="materialize_revision",
            request_digest=request_digest,
        )
        if operation is not None and operation["status"] == "completed":
            try:
                _store.delete_revision_plan(request.plan_id)
            except KeyError:
                pass
            return DashboardRevisionResponse.model_validate_json(
                operation["result_json"]
            )
        _require_workflow(
            original_session.workflow_state,
            {WorkflowState.AWAITING_REVISION_APPROVAL},
            "materialize revision",
        )
        if operation is None:
            _reviews().reserve_operation(
                request.review_session_id,
                expected_version=request.session_version,
                operation_id=request.operation_id,
                operation_type="materialize_revision",
                request_digest=request_digest,
                metadata={"stage": "reserved"},
            )
            metadata = {"stage": "reserved"}
        else:
            metadata = operation["metadata"]
        pending_operation = True

        def persist_stage(stage: str, **values: object) -> None:
            nonlocal metadata
            metadata = {**metadata, **values, "stage": stage}
            _reviews().update_operation_metadata(
                request.review_session_id,
                request.operation_id,
                operation_type="materialize_revision",
                request_digest=request_digest,
                metadata=metadata,
            )

        planned_document_id, plan = _store.get_revision_plan(request.plan_id)
        if planned_document_id != document_id:
            raise ValueError("revision plan belongs to a different document")
        if (
            original_session.state.revision_plan is None
            or original_session.state.revision_plan.plan_digest != plan.plan_digest
            or original_session.state.revision_plan != plan
        ):
            raise ValueError(
                "revision plan does not exactly match the plan previewed by this review session"
            )
        if (
            plan.source_path != original_session.state.source_path
            or plan.source_sha256 != original_session.state.source_sha256
        ):
            raise ValueError("revision plan belongs to a different review source")
        approved = approve_revision_plan(plan, actions=request.actions)
        filename = (
            f"{Path(stored.filename).stem} - Forge Revision"
            f"{Path(stored.filename).suffix}"
        )
        if "generated_document_id" in metadata:
            generated = _generated_from_metadata(metadata)
            if generated.filename != filename:
                raise ValueError("pending revision allocation does not match request")
        else:
            generated = _store.allocate_generated(filename)
            persist_stage(
                "allocated",
                generated_document_id=generated.document_id,
                generated_filename=generated.filename,
                generated_path=str(generated.path),
            )

        completed_stages = {
            "materialized",
            "assessed",
            "registered",
            "final_session",
            "linked",
        }
        if metadata.get("stage") in completed_stages:
            revision = RevisionResult.model_validate_json(str(metadata["revision_json"]))
            if (
                not generated.path.is_file()
                or hashlib.sha256(generated.path.read_bytes()).hexdigest()
                != metadata.get("artifact_sha256")
            ):
                raise ValueError("pending generated revision artifact is unavailable")
        else:
            generated.path.unlink(missing_ok=True)
            revision = materialize_integrated_prd_revision(
                original_session.state.source_path, generated.path, approved
            )
            persist_stage(
                "materialized",
                revision_json=revision.model_dump_json(),
                artifact_sha256=hashlib.sha256(generated.path.read_bytes()).hexdigest(),
            )

        if metadata.get("stage") in {"assessed", "registered", "final_session", "linked"}:
            result = AssessmentResponse.model_validate_json(
                str(metadata["assessment_json"])
            )
            remediation_state_json = metadata.get("remediation_state_json")
            remediation_state = (
                RemediationState.model_validate_json(str(remediation_state_json))
                if remediation_state_json is not None
                else None
            )
        else:
            result, remediation_state = await run_assessment_with_remediation(
                str(generated.path),
                request.llm,
                rubric_name=request.rubric_name,
                display_name=Path(filename).stem,
            )
            if (
                remediation_state is not None
                and remediation_state.source_snapshot is not None
            ):
                _reviews().put_snapshot(remediation_state.source_snapshot)
            persist_stage(
                "assessed",
                assessment_json=result.model_dump_json(),
                remediation_state_json=(
                    remediation_state.model_dump_json()
                    if remediation_state is not None
                    else None
                ),
            )

        _store.register_generated(generated)
        if metadata.get("stage") not in {"registered", "final_session", "linked"}:
            persist_stage("registered")

        final_review_session_id = metadata.get("final_review_session_id")
        session = None
        if remediation_state is not None:
            if final_review_session_id is None:
                final_review_session_id = "rvw_" + uuid.uuid4().hex
                persist_stage(
                    "registered",
                    final_review_session_id=final_review_session_id,
                )
            try:
                session = _reviews().get(str(final_review_session_id))
                if (
                    session.state.source_path != remediation_state.source_path
                    or session.state.source_sha256 != remediation_state.source_sha256
                    or session.state.snapshot_id != remediation_state.snapshot_id
                    or session.state.parser_fingerprint
                    != remediation_state.parser_fingerprint
                    or session.state.normalized_hash
                    != remediation_state.normalized_hash
                ):
                    raise ValueError(
                        "pending final review session belongs to a different artifact"
                    )
            except KeyError:
                session = _reviews().create(
                    remediation_state,
                    review_session_id=str(final_review_session_id),
                    workspace_root=str(_store.root),
                    client_binding=ClientBinding(client_name="dashboard"),
                )
        if metadata.get("stage") not in {"final_session", "linked"}:
            persist_stage("final_session")
    except KeyError as error:
        if pending_operation:
            _cleanup_dashboard_revision_operation(request, metadata, generated)
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ValueError, FileNotFoundError) as error:
        if pending_operation:
            _cleanup_dashboard_revision_operation(request, metadata, generated)
        raise HTTPException(status_code=400, detail=str(error)) from error
    except ExtractionFailed as error:
        if pending_operation:
            _cleanup_dashboard_revision_operation(request, metadata, generated)
        raise HTTPException(status_code=502, detail=str(error)) from error
    try:
        payload = result.model_dump()
        payload["source_path"] = filename
        payload["document_id"] = generated.document_id
        payload["review_session_id"] = session.review_session_id if session else None
        payload["session_version"] = session.session_version if session else None
        payload["workflow_state"] = session.workflow_state if session else None
        payload["next_action"] = session.next_action if session else None
        assessment = DashboardAssessmentResponse.model_validate(payload)
        response = DashboardRevisionResponse(
            document_id=generated.document_id,
            filename=filename,
            revision=DashboardRevisionResult(
                supplemental_answer_count=revision.supplemental_answer_count,
                note=revision.note,
                mode=revision.mode,
                plan_digest=revision.plan_digest,
                final_assessment_required=revision.final_assessment_required,
            ),
            assessment=assessment,
        )
        _store.link_review_artifact(
            review_session_id=original_session.review_session_id,
            plan_id=request.plan_id,
            source_document_id=document_id,
            generated_document_id=generated.document_id,
            final_review_session_id=session.review_session_id if session else None,
        )
        if metadata.get("stage") != "linked":
            persist_stage("linked")
        _reviews().update(
            request.review_session_id,
            expected_version=request.session_version,
            operation_id=request.operation_id,
            state=original_session.state.model_copy(
                update={
                    "revision_plan": None,
                    "revision_output_path": str(generated.path.resolve()),
                    "revision_output_sha256": str(metadata["artifact_sha256"]),
                    "final_verification": FinalVerification(
                        artifact_path=str(generated.path.resolve()),
                        artifact_sha256=str(metadata["artifact_sha256"]),
                        operation_id=request.operation_id,
                        rubric_id=original_session.state.rubric_id,
                        rubric_version=original_session.state.rubric_version,
                        supplemental_answer_count=0,
                        assessment=result,
                    ),
                },
                deep=True,
            ),
            workflow_state=WorkflowState.COMPLETE,
            event_type="revision_materialized_and_verified",
            result_json=response.model_dump_json(),
            event_payload={
                "plan_id": request.plan_id,
                "generated_document_id": generated.document_id,
                "final_review_session_id": session.review_session_id if session else None,
            },
            operation_type="materialize_revision",
            request_digest=request_digest,
            complete_reserved=True,
        )
        _store.delete_revision_plan(request.plan_id)
        return response
    except KeyError as error:
        _cleanup_dashboard_revision_operation(request, metadata, generated)
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ValueError, FileNotFoundError) as error:
        _cleanup_dashboard_revision_operation(request, metadata, generated)
        raise HTTPException(status_code=400, detail=str(error)) from error


def _cleanup_dashboard_revision_operation(
    request: MaterializeRevisionRequest,
    metadata: dict[str, object],
    generated: StoredDocument | None,
) -> None:
    """Compensate normal failures across the separate local SQLite stores."""
    _store.unlink_review_artifact(request.review_session_id, request.plan_id)
    final_review_session_id = metadata.get("final_review_session_id")
    if isinstance(final_review_session_id, str):
        try:
            _reviews().delete(final_review_session_id)
        except KeyError:
            pass
    if generated is not None:
        _store.discard_generated(generated)
    _reviews().cancel_operation(request.review_session_id, request.operation_id)


@app.get("/api/documents/{document_id}/download")
def download_document(document_id: str) -> FileResponse:
    try:
        stored = _store.get(document_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return FileResponse(stored.path, filename=stored.filename)


@app.delete("/api/documents/{document_id}")
def delete_document(document_id: str) -> dict[str, object]:
    try:
        _store.delete(document_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"document_id": document_id, "deleted": True}


def main() -> None:
    import uvicorn

    host = os.environ.get("FORGE_DASHBOARD_HOST", "127.0.0.1")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(
            "Forge dashboard is local-only and refuses a non-loopback host"
        )
    uvicorn.run(
        "forge_dashboard.app:app",
        host=host,
        port=int(os.environ.get("FORGE_DASHBOARD_PORT", "8000")),
        reload=False,
    )


if __name__ == "__main__":
    main()
