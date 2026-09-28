from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuestionEvidence(StrictModel):
    evidence_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    exact_quote: str = Field(min_length=1)
    section: str | None = None
    page: int | None = None


class QuestionSubject(StrictModel):
    assertion_id: str
    evidence: QuestionEvidence


class QuestionIssue(StrictModel):
    issue_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: str = Field(min_length=1)
    evidence_ids: list[str]
    left_evidence_ids: list[str] = Field(default_factory=list)
    right_evidence_ids: list[str] = Field(default_factory=list)
    missing_decisions: list[str] = Field(default_factory=list)


class ShadowQuestionTarget(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    plan_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluation_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    criterion_id: str
    criterion_name: str
    assertion_id: str
    assertion_description: str
    prerequisite_assertion_ids: list[str] = Field(default_factory=list)
    status: Literal["gap", "contradictory", "ambiguous"]
    agreement: float = Field(gt=0.5, le=1)
    run_count: int = Field(ge=3)
    issue_ids: list[str] = Field(min_length=1)
    evidence_ids: list[str]
    evidence: list[QuestionEvidence]
    issues: list[QuestionIssue]
    subject: QuestionSubject | None = None
    answer_contract: str = Field(min_length=1)
    fallback_question: str = Field(min_length=1)
    score_effect: Literal["none"] = "none"
    shadow: Literal[True] = True


class PreparedQuestionGeneration(StrictModel):
    target: ShadowQuestionTarget
    prompt: str


class QuestionGenerationSubmission(StrictModel):
    plan_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    issue_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    question: str = Field(min_length=1, max_length=300)


class ShadowQuestion(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    question_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    criterion_id: str
    assertion_id: str
    status: Literal["gap", "contradictory", "ambiguous"]
    issue_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_ids: list[str]
    question: str
    answer_contract: str
    generation_mode: Literal[
        "generated", "rubric_fallback", "deterministic_template"
    ]
    rejection_reason: str | None = None
    score_effect: Literal["none"] = "none"
    shadow: Literal[True] = True
