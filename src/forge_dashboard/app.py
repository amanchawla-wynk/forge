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
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel

from forge_dashboard.llm import LLMCallError, call_model
from forge_dashboard.models import (
    AssessRequest,
    DashboardAssessmentResponse,
    LLMConfig,
    UploadResponse,
)
from forge_dashboard.runner import ExtractionFailed, run_assessment
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
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_store = DocumentStore()


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
        result = await run_assessment(
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
    return DashboardAssessmentResponse.model_validate(payload)


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
