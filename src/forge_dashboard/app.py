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
import uuid

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
    DashboardRemediationTurn,
    DashboardRevisionPreview,
    DashboardRevisionResponse,
    LLMConfig,
    RecordAnswerRequest,
    MaterializeRevisionRequest,
    RevisionPreviewRequest,
    UploadResponse,
)
from forge.remediation import (
    RemediationSessionStore,
    apply_checkpoint,
    prepare_checkpoint,
    record_answer,
)
from forge.revise import (
    RevisionPlan,
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
_remediation_store = RemediationSessionStore()
_revision_plans: dict[str, tuple[str, RevisionPlan]] = {}


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
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="the uploaded file is empty")
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
    payload["remediation_session_id"] = (
        _remediation_store.create(remediation_state)
        if remediation_state is not None
        else None
    )
    return DashboardAssessmentResponse.model_validate(payload)


@app.post(
    "/api/remediation/{session_id}/answers",
    response_model=DashboardRemediationTurn,
)
def record_remediation_answer(
    session_id: str, request: RecordAnswerRequest
) -> DashboardRemediationTurn:
    try:
        state = _remediation_store.get(session_id)
        turn = record_answer(
            state,
            request.answer,
            force_checkpoint=request.force_checkpoint,
        )
        _remediation_store.put(session_id, turn.state)
    except (KeyError, ValueError, FileNotFoundError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return DashboardRemediationTurn(session_id=session_id, turn=turn)


@app.post(
    "/api/remediation/{session_id}/checkpoint",
    response_model=DashboardCheckpointResponse,
)
async def checkpoint_remediation(
    session_id: str, request: CheckpointRequest
) -> DashboardCheckpointResponse:
    try:
        state = _remediation_store.get(session_id)
        plan = prepare_checkpoint(state)
        completion = await call_model(
            request.llm,
            plan.extraction_prompt,
            max_tokens=4_000,
            temperature=0,
        )
        result = apply_checkpoint(state, completion.text)
        _remediation_store.put(session_id, result.state)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except LLMCallError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except (ValueError, FileNotFoundError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return DashboardCheckpointResponse(session_id=session_id, result=result)


@app.delete("/api/remediation/{session_id}")
def delete_remediation(session_id: str) -> dict[str, object]:
    try:
        _remediation_store.delete(session_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"session_id": session_id, "deleted": True}


@app.post(
    "/api/documents/{document_id}/revisions/preview",
    response_model=DashboardRevisionPreview,
)
def preview_revision(
    document_id: str, request: RevisionPreviewRequest
) -> DashboardRevisionPreview:
    try:
        stored = _store.get(document_id)
        plan = preview_integrated_revision(
            stored.path,
            request.supplemental_answers,
            section_overrides=request.section_overrides,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ValueError, FileNotFoundError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    plan_id = uuid.uuid4().hex
    _revision_plans[plan_id] = (document_id, plan)
    return DashboardRevisionPreview(
        plan_id=plan_id,
        plan_digest=plan.plan_digest,
        source_sha256=plan.source_sha256,
        edits=plan.edits,
    )


@app.post(
    "/api/documents/{document_id}/revisions",
    response_model=DashboardRevisionResponse,
)
async def create_revision(
    document_id: str, request: MaterializeRevisionRequest
) -> DashboardRevisionResponse:
    try:
        stored = _store.get(document_id)
        planned_document_id, plan = _revision_plans[request.plan_id]
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
        del _revision_plans[request.plan_id]
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ValueError, FileNotFoundError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except ExtractionFailed as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    payload = result.model_dump()
    payload["source_path"] = filename
    payload["document_id"] = generated.document_id
    payload["remediation_session_id"] = (
        _remediation_store.create(remediation_state)
        if remediation_state is not None
        else None
    )
    assessment = DashboardAssessmentResponse.model_validate(payload)
    return DashboardRevisionResponse(
        document_id=generated.document_id,
        filename=filename,
        revision=revision,
        assessment=assessment,
    )


@app.get("/api/documents/{document_id}/download")
def download_document(document_id: str) -> FileResponse:
    try:
        stored = _store.get(document_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return FileResponse(stored.path, filename=stored.filename)


def main() -> None:
    import uvicorn

    uvicorn.run(
        "forge_dashboard.app:app",
        host=os.environ.get("FORGE_DASHBOARD_HOST", "127.0.0.1"),
        port=int(os.environ.get("FORGE_DASHBOARD_PORT", "8000")),
        reload=False,
    )


if __name__ == "__main__":
    main()
