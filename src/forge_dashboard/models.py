from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from forge.ingest.models import ProductContextTerm, SupplementalAnswer
from forge.score.edge_coverage import EdgeCaseCoverageLedger
from forge.revise import RevisionEdit
from forge.service import AssessmentResponse
from forge.score.engine import Assessment
from forge.score.planner import Question
from forge.score.report import NarrativeReport
from forge.sessions import NextAction, WorkflowState

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
    start_new: bool = False


class DashboardAssessmentResponse(AssessmentResponse):
    """Same shape as the MCP assessment response, plus dashboard metadata."""

    document_id: str
    extraction_errors: list[str] = Field(default_factory=list)
    review_session_id: str | None = None
    session_version: int | None = None
    workflow_state: WorkflowState | None = None
    next_action: NextAction | None = None


class RecordAnswerRequest(BaseModel):
    session_version: int = Field(ge=1)
    operation_id: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    force_checkpoint: bool = False


class DashboardRemediationTurn(BaseModel):
    review_session_id: str
    session_version: int
    workflow_state: WorkflowState
    next_action: NextAction
    turn: "DashboardTurnData"


class DashboardTurnData(BaseModel):
    next_question: Question | None
    checkpoint_due: bool
    checkpoint_reason: str | None
    pending_answer_count: int
    verified_answer_count: int
    score_is_current: bool


class CheckpointRequest(BaseModel):
    llm: LLMConfig
    session_version: int = Field(ge=1)
    operation_id: str = Field(min_length=1)


class DashboardCheckpointResponse(BaseModel):
    review_session_id: str
    session_version: int
    workflow_state: WorkflowState
    next_action: NextAction
    result: "DashboardCheckpointResult"


class DashboardReviewState(BaseModel):
    assessment: Assessment
    report: NarrativeReport
    verified_answers: list[SupplementalAnswer]
    framing: str | None
    edge_case_coverage: EdgeCaseCoverageLedger | None


class DashboardCheckpointResult(BaseModel):
    state: DashboardReviewState
    next_question: Question | None
    credited_answer_ids: list[str]
    uncredited_answer_ids: list[str]
    previous_band: str
    current_band: str


class DashboardReviewDiscovery(BaseModel):
    document_id: str
    matches: list["DashboardReviewSummary"]
    choices: list[Literal["resume_review", "start_new_review", "cancel"]]


class DashboardReviewSummary(BaseModel):
    review_session_id: str
    display_name: str
    current_band: str
    workflow_state: WorkflowState
    verified_answer_count: int
    pending_answer_count: int
    client_name: str | None
    updated_at: float


class ResumeReviewRequest(BaseModel):
    operation_id: str = Field(min_length=1)
    confirm_client_change: bool = False


class RevisionPreviewRequest(BaseModel):
    review_session_id: str
    session_version: int = Field(ge=1)
    operation_id: str = Field(min_length=1)
    supplemental_answers: list[SupplementalAnswer] = Field(min_length=1)
    section_overrides: dict[str, str] = Field(default_factory=dict)


class DashboardRevisionPreview(BaseModel):
    plan_id: str
    plan_digest: str
    source_sha256: str
    edits: list[RevisionEdit]
    review_session_id: str
    session_version: int
    workflow_state: WorkflowState
    next_action: NextAction


class MaterializeRevisionRequest(BaseModel):
    review_session_id: str
    session_version: int = Field(ge=1)
    operation_id: str = Field(min_length=1)
    plan_id: str
    actions: dict[str, Literal["integrate", "audit_only", "skip"]]
    llm: LLMConfig
    rubric_name: str = "prd"


class DashboardRevisionResponse(BaseModel):
    document_id: str
    filename: str
    revision: "DashboardRevisionResult"
    assessment: DashboardAssessmentResponse


class DashboardRevisionResult(BaseModel):
    supplemental_answer_count: int
    note: str
    mode: Literal["appendix", "integrated"]
    plan_digest: str | None
    final_assessment_required: bool
