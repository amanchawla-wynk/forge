from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from forge.ingest.models import ProductContextTerm, SupplementalAnswer
from forge.score.edge_coverage import EdgeCaseCoverageLedger
from forge.remediation import RemediationCheckpointResult, RemediationTurn
from forge.revise import RevisionEdit, RevisionResult
from forge.service import AssessmentResponse

# "cursor" is not an LLM provider: it authenticates to Cursor's Cloud Agents
# API with a Cursor-issued key and is handled separately from the LiteLLM
# providers. See docs/DECISIONS.md D-034.
Provider = Literal["anthropic", "openai", "gemini", "cursor"]


class LLMConfig(BaseModel):
    """Per-request, never-persisted model configuration.

    The dashboard backend forwards `api_key` to LiteLLM (or, for `cursor`, to
    Cursor's Cloud Agents API) for the duration of one request only. It is
    never written to disk, a database, or a log.
    """

    provider: Provider
    # Required for anthropic/openai/gemini. Optional for cursor, which falls
    # back to the caller's configured Cursor default model when blank.
    model: str = ""
    api_key: str = Field(min_length=1)

    @model_validator(mode="after")
    def _require_model_for_direct_providers(self) -> "LLMConfig":
        if self.provider != "cursor" and not self.model.strip():
            raise ValueError(f"model is required for provider {self.provider!r}")
        return self


class UploadResponse(BaseModel):
    document_id: str
    filename: str
    source_type: str


class AssessRequest(BaseModel):
    document_id: str
    llm: LLMConfig
    rubric_name: str = "prd"
    supplemental_answers: list[SupplementalAnswer] = Field(default_factory=list)
    product_context: list[ProductContextTerm] = Field(default_factory=list)
    # Detected once on the first assessment, then echoed by the response and
    # resubmitted on every remediation turn so question phrasing cannot drift.
    framing: str | None = None
    edge_case_coverage: EdgeCaseCoverageLedger | None = None


class DashboardAssessmentResponse(AssessmentResponse):
    """Same shape as the MCP assessment response, plus dashboard metadata."""

    document_id: str
    extraction_errors: list[str] = Field(default_factory=list)
    remediation_session_id: str | None = None


class RecordAnswerRequest(BaseModel):
    answer: str = Field(min_length=1)
    force_checkpoint: bool = False


class DashboardRemediationTurn(BaseModel):
    session_id: str
    turn: RemediationTurn


class CheckpointRequest(BaseModel):
    llm: LLMConfig


class DashboardCheckpointResponse(BaseModel):
    session_id: str
    result: RemediationCheckpointResult


class RevisionPreviewRequest(BaseModel):
    supplemental_answers: list[SupplementalAnswer] = Field(min_length=1)
    section_overrides: dict[str, str] = Field(default_factory=dict)


class DashboardRevisionPreview(BaseModel):
    plan_id: str
    plan_digest: str
    source_sha256: str
    edits: list[RevisionEdit]


class MaterializeRevisionRequest(BaseModel):
    plan_id: str
    actions: dict[str, Literal["integrate", "audit_only", "skip"]]
    llm: LLMConfig
    rubric_name: str = "prd"


class DashboardRevisionResponse(BaseModel):
    document_id: str
    filename: str
    revision: RevisionResult
    assessment: DashboardAssessmentResponse
