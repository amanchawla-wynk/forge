"""Rubric data model.

Design invariants (do not relax these without re-running calibration):

1. No criterion is scored on an open numeric scale. Verdicts are ternary.
2. A verdict is *derived* from a structured extraction, never asserted by the
   model. The model's only job is to fill a schema and cite the document.
3. Every satisfied field must carry an evidence span. No span => not satisfied.
4. Aggregation happens in Python. The model never sees the weights.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Verdict(str, Enum):
    PRESENT = "present"
    PARTIAL = "partial"
    ABSENT = "absent"
    NOT_APPLICABLE = "not_applicable"


VERDICT_CREDIT: dict[Verdict, float] = {
    Verdict.PRESENT: 1.0,
    Verdict.PARTIAL: 0.5,
    Verdict.ABSENT: 0.0,
    Verdict.NOT_APPLICABLE: 0.0,  # excluded from the denominator, see scoring
}


class Consumer(str, Enum):
    """Downstream readers the document must serve.

    The rubric grades 'can this person act without a follow-up meeting?',
    not 'is this well written'. Tune this list to the company later.
    """

    ENGINEERING = "engineering"
    DESIGN = "design"
    QA = "qa"
    DATA = "data"
    RISK = "risk"  # legal / security / privacy / compliance
    LEADERSHIP = "leadership"
    GTM = "gtm"  # support, sales, marketing, docs


class FieldSpec(BaseModel):
    """One slot the extractor must fill from the document."""

    name: str
    description: str
    type: Literal["string", "number", "boolean", "date", "string[]"] = "string"
    required: bool = True
    # If set, the field only counts when the value is not in this list.
    # Guards against the model writing "TBD" / "N/A" and claiming a hit.
    reject_values: list[str] = Field(
        default_factory=lambda: ["tbd", "n/a", "na", "none", "unknown", "?", "-"]
    )


class GateLevel(str, Enum):
    """A gate caps the overall band regardless of points earned elsewhere.

    This is what stops a long, polished, unmeasurable document from scoring well.
    """

    NONE = "none"
    CAPS_AT_NEEDS_WORK = "caps_at_needs_work"
    CAPS_AT_READY_WITH_GAPS = "caps_at_ready_with_gaps"


class Criterion(BaseModel):
    id: str
    name: str
    # Why this matters, in downstream-consumer terms. Shown in the report.
    rationale: str
    consumers: list[Consumer]
    weight: float = Field(gt=0)
    gate: GateLevel = GateLevel.NONE
    # Verdict is derived from how many required fields were satisfied.
    fields: list[FieldSpec]
    # Question asked during the remediation loop when this criterion fails.
    remediation_prompt: str
    # Some criteria genuinely don't apply (e.g. no PII => no privacy section).
    # If set, the extractor may return not_applicable with a justification.
    allow_not_applicable: bool = False

    @model_validator(mode="after")
    def _require_at_least_one_required_field(self) -> Criterion:
        if not any(f.required for f in self.fields):
            raise ValueError(f"criterion {self.id!r} has no required fields")
        return self

    @property
    def required_fields(self) -> list[FieldSpec]:
        return [f for f in self.fields if f.required]


class Band(BaseModel):
    """Output is a band, not a number. Numbers imply precision we don't have."""

    id: str
    label: str
    min_score: float  # inclusive, on the 0..1 weighted scale
    description: str


class Rubric(BaseModel):
    id: str
    version: str
    doc_type: Literal["prd", "brd"]
    description: str
    criteria: list[Criterion]
    bands: list[Band]
    # Number of independent extraction runs. Disagreement lowers confidence
    # rather than being silently averaged away.
    extraction_runs: int = 3

    @model_validator(mode="after")
    def _validate(self) -> Rubric:
        ids = [c.id for c in self.criteria]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate criterion ids")
        if not self.bands:
            raise ValueError("rubric needs at least one band")
        return self

    def criterion(self, criterion_id: str) -> Criterion:
        for c in self.criteria:
            if c.id == criterion_id:
                return c
        raise KeyError(criterion_id)

    def bands_descending(self) -> list[Band]:
        return sorted(self.bands, key=lambda b: b.min_score, reverse=True)
