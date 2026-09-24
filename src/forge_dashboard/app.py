"""Local-only FastAPI backend for the optional Forge dashboard.

Run with `forge-dashboard-api` (installed by the `dashboard` extra) or
`uvicorn forge_dashboard.app:app --reload`. Binds to localhost by default.

This process accepts a per-request LLM API key from the browser (see
`docs/DECISIONS.md` D-033) and forwards it to LiteLLM for that request only.
It never writes the key to disk, a database, or a log.
"""

from __future__ import annotations

import os
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
    apply_checkpoint,
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
from forge.revise import (
    approve_revision_plan,
    materialize_integrated_prd_revision,
    preview_integrated_revision,
)
from forge_dashboard.runner import (
    ExtractionFailed,
    run_assessment_with_remediation,
)
from forge_dashboard.storage import DocumentStore

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

    matches = _reviews().find(str(stored.path), workspace_root=str(_store.root))
    if matches and not request.start_new:
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
        )
    except ExtractionFailed as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except (ValueError, FileNotFoundError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    # Never return the server's local filesystem path to the browser.
    payload = result.model_dump()
    payload["source_path"] = stored.filename
    payload["document_id"] = stored.document_id
    session = (
        _reviews().create(
            remediation_state,
            workspace_root=str(_store.root),
            client_binding=ClientBinding(client_name="dashboard"),
        )
        if remediation_state is not None
        else None
    )
    payload["review_session_id"] = session.review_session_id if session else None
    payload["session_version"] = session.session_version if session else None
    payload["workflow_state"] = session.workflow_state if session else None
    payload["next_action"] = session.next_action if session else None
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
    turn = turn_for_session(session)
    disputed = [
        item.criterion_id
        for item in session.state.assessment.criteria
        if item.agreement < 1.0
    ]
    return DashboardAssessmentResponse(
        source_path=stored.filename,
        document_id=document_id,
        report=session.state.report,
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
        warnings=[],
        extraction_errors=[],
        review_session_id=session.review_session_id,
        session_version=session.session_version,
        workflow_state=session.workflow_state,
        next_action=session.next_action,
    )


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
            },
        )
        cached = _reviews().operation_result(
            session_id,
            request.operation_id,
            operation_type="record_answer",
            request_digest=request_digest,
        )
        if cached is not None:
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
        )
        session = _reviews().update(
            session_id,
            expected_version=request.session_version,
            operation_id=request.operation_id,
            state=turn.state,
            workflow_state=workflow_for_turn(turn),
            event_type="answer_recorded",
            result_json=turn.model_dump_json(),
            event_payload={"checkpoint_due": turn.checkpoint_due},
            operation_type="record_answer",
            request_digest=request_digest,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ValueError, FileNotFoundError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return DashboardRemediationTurn(
        review_session_id=session_id,
        session_version=session.session_version,
        workflow_state=session.workflow_state,
        next_action=session.next_action,
        turn=DashboardTurnData.model_validate(
            turn_for_session(session).model_dump(exclude={"state"})
        ),
    )


@app.post(
    "/api/remediation/{session_id}/checkpoint",
    response_model=DashboardCheckpointResponse,
)
async def checkpoint_remediation(
    session_id: str, request: CheckpointRequest
) -> DashboardCheckpointResponse:
    reserved = False
    try:
        request_digest = operation_digest(
            "dashboard_checkpoint",
            {
                "session_version": request.session_version,
                "provider": request.llm.provider,
                "model": request.llm.model,
            },
        )
        cached = _reviews().operation_result(
            session_id,
            request.operation_id,
            operation_type="dashboard_checkpoint",
            request_digest=request_digest,
        )
        if cached is not None:
            session = _reviews().get(session_id)
            return DashboardCheckpointResponse(
                review_session_id=session_id,
                session_version=session.session_version,
                workflow_state=session.workflow_state,
                next_action=session.next_action,
                result=DashboardCheckpointResult.model_validate_json(cached),
            )
        session = _reviews().get(session_id)
        _require_workflow(
            session.workflow_state,
            {WorkflowState.CHECKPOINT_REQUIRED, WorkflowState.AWAITING_DELTA_EXTRACTION},
            "checkpoint",
        )
        _reviews().reserve_operation(
            session_id,
            expected_version=request.session_version,
            operation_id=request.operation_id,
            operation_type="dashboard_checkpoint",
            request_digest=request_digest,
        )
        reserved = True
        plan = prepare_checkpoint(session.state)
        completion = await call_model(
            request.llm,
            plan.extraction_prompt,
            max_tokens=4_000,
            temperature=0,
        )
        result = apply_checkpoint(session.state, completion.text)
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
        if reserved:
            _reviews().cancel_operation(session_id, request.operation_id)
        raise HTTPException(status_code=404, detail=str(error)) from error
    except LLMCallError as error:
        if reserved:
            _reviews().cancel_operation(session_id, request.operation_id)
        raise HTTPException(status_code=502, detail=str(error)) from error
    except (ValueError, FileNotFoundError) as error:
        if reserved:
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
    try:
        stored = _store.get(document_id)
        request_digest = operation_digest(
            "preview_revision",
            {
                "document_id": document_id,
                "answers": [
                    answer.model_dump(mode="json")
                    for answer in request.supplemental_answers
                ],
                "section_overrides": request.section_overrides,
            },
        )
        cached = _reviews().operation_result(
            request.review_session_id,
            request.operation_id,
            operation_type="preview_revision",
            request_digest=request_digest,
        )
        if cached is not None:
            return DashboardRevisionPreview.model_validate_json(cached)
        session = _reviews().get(request.review_session_id)
        _require_workflow(
            session.workflow_state,
            {WorkflowState.REVISION_READY},
            "preview revision",
        )
        plan = preview_integrated_revision(
            stored.path,
            request.supplemental_answers,
            section_overrides=request.section_overrides,
        )
        plan_id = _store.save_revision_plan(document_id, plan)
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
        session = _reviews().update(
            request.review_session_id,
            expected_version=request.session_version,
            operation_id=request.operation_id,
            state=session.state,
            workflow_state=WorkflowState.AWAITING_REVISION_APPROVAL,
            event_type="revision_previewed",
            result_json=response.model_dump_json(),
            event_payload={"plan_id": plan_id, "plan_digest": plan.plan_digest},
            operation_type="preview_revision",
            request_digest=request_digest,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ValueError, FileNotFoundError) as error:
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
    reserved = False
    generated = None
    try:
        stored = _store.get(document_id)
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
        cached = _reviews().operation_result(
            request.review_session_id,
            request.operation_id,
            operation_type="materialize_revision",
            request_digest=request_digest,
        )
        if cached is not None:
            return DashboardRevisionResponse.model_validate_json(cached)
        original_session = _reviews().get(request.review_session_id)
        _require_workflow(
            original_session.workflow_state,
            {WorkflowState.AWAITING_REVISION_APPROVAL},
            "materialize revision",
        )
        _reviews().reserve_operation(
            request.review_session_id,
            expected_version=request.session_version,
            operation_id=request.operation_id,
            operation_type="materialize_revision",
            request_digest=request_digest,
        )
        reserved = True
        planned_document_id, plan = _store.get_revision_plan(request.plan_id)
        if planned_document_id != document_id:
            raise ValueError("revision plan belongs to a different document")
        approved = approve_revision_plan(plan, actions=request.actions)
        filename = (
            f"{Path(stored.filename).stem} - Forge Revision"
            f"{Path(stored.filename).suffix}"
        )
        generated = _store.allocate_generated(filename)
        revision = materialize_integrated_prd_revision(
            stored.path, generated.path, approved
        )
        result, remediation_state = await run_assessment_with_remediation(
            str(generated.path),
            request.llm,
            rubric_name=request.rubric_name,
            display_name=Path(filename).stem,
        )
        _store.register_generated(generated)
    except KeyError as error:
        if reserved:
            _reviews().cancel_operation(
                request.review_session_id, request.operation_id
            )
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ValueError, FileNotFoundError) as error:
        if reserved:
            _reviews().cancel_operation(
                request.review_session_id, request.operation_id
            )
        raise HTTPException(status_code=400, detail=str(error)) from error
    except ExtractionFailed as error:
        if reserved:
            _reviews().cancel_operation(
                request.review_session_id, request.operation_id
            )
        if generated is not None:
            generated.path.unlink(missing_ok=True)
        raise HTTPException(status_code=502, detail=str(error)) from error
    payload = result.model_dump()
    payload["source_path"] = filename
    payload["document_id"] = generated.document_id
    session = (
        _reviews().create(
            remediation_state,
            workspace_root=str(_store.root),
            client_binding=ClientBinding(client_name="dashboard"),
        )
        if remediation_state is not None
        else None
    )
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
    original_session = _reviews().update(
        request.review_session_id,
        expected_version=request.session_version,
        operation_id=request.operation_id,
        state=original_session.state,
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
    _store.link_review_artifact(
        review_session_id=original_session.review_session_id,
        plan_id=request.plan_id,
        source_document_id=document_id,
        generated_document_id=generated.document_id,
        final_review_session_id=session.review_session_id if session else None,
    )
    _store.delete_revision_plan(request.plan_id)
    return response


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
