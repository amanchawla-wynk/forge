from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from forge.extract.models import CriterionExtraction


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Applicability(str, Enum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    UNCLEAR = "unclear"


class SemanticStatus(str, Enum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    CONTRADICTORY = "contradictory"
    UNCLEAR = "unclear"
    NOT_APPLICABLE = "not_applicable"


class SupportRelation(str, Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    CONTEXT = "context"
    UNCLEAR = "unclear"


class EvidenceReference(StrictModel):
    ref_id: str = Field(min_length=1)
    source_block_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    quote_start_char: int | None = Field(default=None, ge=0)
    quote_end_char: int | None = Field(default=None, ge=1)


class SubmittedClaim(StrictModel):
    claim_ref: str = Field(min_length=1)
    assertion_id: str = Field(min_length=1)
    value: str | list[str] | None = None
    evidence_refs: list[str] = Field(min_length=1)


class SubmittedEvidenceSet(StrictModel):
    evidence_set_ref: str = Field(min_length=1)
    role: str = "supporting"
    assertion_ids: list[str] = Field(min_length=1)
    claim_refs: list[str] = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    relation: SupportRelation


class SubmittedGap(StrictModel):
    gap_ref: str = Field(min_length=1)
    assertion_ids: list[str] = Field(min_length=1)
    kind: Literal[
        "missing_decision",
        "unsupported_claim",
        "missing_evidence",
        "ambiguous_requirement",
    ]
    missing_decision: str | None = Field(default=None, min_length=1, max_length=300)


class SubmittedAmbiguity(StrictModel):
    issue_ref: str = Field(min_length=1)
    assertion_ids: list[str] = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    alternatives: list[str] = Field(min_length=2)


class SubmittedContradiction(StrictModel):
    issue_ref: str = Field(min_length=1)
    assertion_ids: list[str] = Field(min_length=1)
    left_evidence_refs: list[str] = Field(min_length=1)
    right_evidence_refs: list[str] = Field(min_length=1)
    relation: Literal[
        "precedence_conflict",
        "scoped_contradiction",
        "superseded_requirement",
        "implied_exception",
        "ambiguous_scope",
        "unclear",
    ]


class CriterionEvaluationSubmission(StrictModel):
    criterion_id: str = Field(min_length=1)
    applicability: Applicability = Applicability.APPLICABLE
    evidence: list[EvidenceReference] = Field(default_factory=list)
    claims: list[SubmittedClaim] = Field(default_factory=list)
    evidence_sets: list[SubmittedEvidenceSet] = Field(default_factory=list)
    gaps: list[SubmittedGap] = Field(default_factory=list)
    ambiguities: list[SubmittedAmbiguity] = Field(default_factory=list)
    contradictions: list[SubmittedContradiction] = Field(default_factory=list)
    not_applicable_evidence_refs: list[str] = Field(default_factory=list)


class EvidenceSpan(StrictModel):
    evidence_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_id: str
    source_block_id: str
    source_parent_block_id: str | None = None
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=1)
    exact_quote: str = Field(min_length=1)
    provenance: Literal["document", "supplemental_answer"]
    page: int | None = None
    section: str | None = None


class EvaluationClaim(StrictModel):
    claim_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    assertion_id: str
    value: str | list[str] | None = None
    evidence_ids: list[str]
    run_ids: list[str]


class EvidenceSet(StrictModel):
    evidence_set_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    role: str
    assertion_ids: list[str]
    claim_ids: list[str]
    evidence_ids: list[str]
    relation: SupportRelation
    run_ids: list[str]
    batch_ids: list[str]


class EvaluationGap(StrictModel):
    gap_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    assertion_ids: list[str]
    kind: str
    question: str
    missing_decisions: list[str] = Field(default_factory=list)


class EvaluationAmbiguity(StrictModel):
    issue_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    assertion_ids: list[str]
    evidence_ids: list[str]
    alternatives: list[str]
    run_ids: list[str]


class EvaluationContradiction(StrictModel):
    issue_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    assertion_ids: list[str]
    left_evidence_ids: list[str]
    right_evidence_ids: list[str]
    relation: str
    run_ids: list[str]


class EvaluationConfidence(StrictModel):
    agreement: float = Field(ge=0, le=1)
    run_count: int = Field(ge=1)
    expected_run_count: int = Field(ge=1)
    basis: Literal[
        "single_evaluation_run",
        "independent_evaluation_runs",
        "legacy_extraction_runs",
    ]


class AssertionOutcome(StrictModel):
    assertion_id: str
    status: Literal[
        "supported", "gap", "contradictory", "ambiguous", "unclear"
    ]
    agreement: float = Field(ge=0, le=1)
    run_count: int = Field(ge=1)
    evidence_ids: list[str] = Field(default_factory=list)
    issue_ids: list[str] = Field(default_factory=list)


class CriterionEvaluation(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    evaluation_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    criterion_id: str
    snapshot_id: str
    rubric_id: str
    rubric_version: str
    plan_fingerprint: str
    run_ids: list[str]
    batch_ids: list[str]
    coverage_complete: bool
    applicability: Applicability
    status: SemanticStatus
    evidence: list[EvidenceSpan] = Field(default_factory=list)
    claims: list[EvaluationClaim] = Field(default_factory=list)
    evidence_sets: list[EvidenceSet] = Field(default_factory=list)
    gaps: list[EvaluationGap] = Field(default_factory=list)
    ambiguities: list[EvaluationAmbiguity] = Field(default_factory=list)
    contradictions: list[EvaluationContradiction] = Field(default_factory=list)
    assertion_outcomes: list[AssertionOutcome] = Field(default_factory=list)
    confidence: EvaluationConfidence
    origin: Literal["criterion_evaluation", "legacy_field_adapter"]
    legacy_extraction: CriterionExtraction | None = None
