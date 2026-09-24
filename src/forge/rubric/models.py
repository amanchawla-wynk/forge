"""Rubric data model.

Design invariants (do not relax these without re-running calibration):

1. No criterion is scored on an open numeric scale. Verdicts are ternary.
2. A verdict is *derived* from a structured extraction, never asserted by the
   model. The model's only job is to fill a schema and cite the document.
3. Every satisfied field must carry an evidence span. No span => not satisfied.
4. Aggregation happens in Python. The model never sees the weights.
"""

from __future__ import annotations

import re
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
    # If set, the value must match this regex to count. This is the only
    # defence against a field that is filled in with a fluent but
    # unfalsifiable phrase ("conversion is lower than we would like"), which
    # `reject_values` cannot catch. Keep it objective: a pattern must be
    # checkable without judgement, such as requiring a digit in a baseline.
    value_pattern: str | None = None
    # Shown to the extractor so it does not claim a field it cannot satisfy.
    value_requirement: str | None = None
    # Optional user-facing prompt for the one-field-at-a-time remediation loop.
    remediation_question: str | None = None
    # Optional per-framing rephrasings of `remediation_question`, keyed by
    # `Framing.id`. A PRD that opens a new market has no "what goes wrong
    # today", so the problem-fix phrasing is a category error for it. Every
    # variant is rubric-authored text; the model may only *select* a framing,
    # never write one. Missing key falls back to `remediation_question`.
    # See `docs/DECISIONS.md` D-036.
    framing_questions: dict[str, str] = Field(default_factory=dict)

    def question_for(self, framing: str | None) -> str | None:
        """Resolve the phrasing for a framing, falling back to the default."""
        if framing is not None:
            variant = self.framing_questions.get(framing)
            if variant and variant.strip():
                return variant.strip()
        return self.remediation_question

    @model_validator(mode="after")
    def _compile_value_pattern(self) -> FieldSpec:
        if self.value_pattern is not None:
            try:
                re.compile(self.value_pattern)
            except re.error as error:
                raise ValueError(f"invalid value_pattern: {error}") from error
        return self

    def matches_pattern(self, value: str) -> bool:
        if self.value_pattern is None:
            return True
        return re.search(self.value_pattern, value) is not None


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


class Framing(BaseModel):
    """What kind of bet the document describes.

    Framing changes which *phrasing* of a question is coherent, never which
    fields are required, what they are worth, or how they are scored. A
    compliance mandate and a growth bet both need a stated problem and a
    measurable target; only the sensible way to ask for them differs.
    """

    id: str
    label: str
    # Shown to the model during closed-set framing selection.
    description: str


class Band(BaseModel):
    """Output is a band, not a number. Numbers imply precision we don't have."""

    id: str
    label: str
    min_score: float  # inclusive, on the 0..1 weighted scale
    description: str
    # The highest readiness claim is stronger than a weighted average. When
    # enabled, every applicable criterion must be present for this band.
    requires_all_applicable_present: bool = False


class RubricSource(BaseModel):
    """Published guidance used to construct an expert-baseline rubric."""

    title: str
    url: str
    contribution: str


class Rubric(BaseModel):
    id: str
    version: str
    doc_type: Literal["prd", "brd"]
    description: str
    calibration_status: Literal["expert_baseline", "organization_validated"]
    sources: list[RubricSource] = Field(min_length=1)
    criteria: list[Criterion]
    bands: list[Band]
    # Selectable document framings. The default is used whenever framing is
    # unknown, undetected, or the model's selection fails validation, so the
    # rubric always behaves exactly as it did before framing existed.
    framings: list[Framing] = Field(default_factory=list)
    default_framing: str | None = None
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
        band_ids = [band.id for band in self.bands]
        if len(band_ids) != len(set(band_ids)):
            raise ValueError("duplicate band ids")
        if any(not 0 <= band.min_score <= 1 for band in self.bands):
            raise ValueError("band min_score must be between 0 and 1")
        if min(band.min_score for band in self.bands) != 0:
            raise ValueError("rubric needs a band with min_score 0")

        framing_ids = [framing.id for framing in self.framings]
        if len(framing_ids) != len(set(framing_ids)):
            raise ValueError("duplicate framing ids")
        known = set(framing_ids)
        if self.default_framing is not None and self.default_framing not in known:
            raise ValueError(
                f"default_framing {self.default_framing!r} is not a declared framing"
            )
        # A phrasing keyed to a framing that cannot be selected would be dead
        # configuration that silently never fires.
        for criterion in self.criteria:
            for field in criterion.fields:
                unknown = sorted(set(field.framing_questions) - known)
                if unknown:
                    raise ValueError(
                        f"{criterion.id}.{field.name} declares unknown framings: "
                        + ", ".join(unknown)
                    )
        return self

    def framing(self, framing_id: str) -> Framing | None:
        return next((f for f in self.framings if f.id == framing_id), None)

    def criterion(self, criterion_id: str) -> Criterion:
        for c in self.criteria:
            if c.id == criterion_id:
                return c
        raise KeyError(criterion_id)

    def bands_descending(self) -> list[Band]:
        return sorted(self.bands, key=lambda b: b.min_score, reverse=True)
