"""What the extractor returns, and how a raw extraction becomes a verdict.

The extractor is deliberately *not* asked to judge quality. It is asked to
locate facts and quote them. Extraction is far more reproducible than
evaluation, and it cannot be inflated by adjectives or document length.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from forge.rubric.models import Criterion, Verdict


class Evidence(BaseModel):
    """A verbatim quote from the document. Required for any satisfied field."""

    quote: str = Field(min_length=1)
    section: str | None = None
    page: int | None = None
    provenance: Literal["document", "supplemental_answer"] = "document"
    source_block_id: str | None = None


class FieldExtraction(BaseModel):
    name: str
    value: str | None = None
    evidence: Evidence | None = None

    def is_satisfied(self, reject_values: list[str]) -> bool:
        """A field counts only if it has a real value AND a citation.

        The evidence requirement is the anti-hallucination mechanism: the model
        cannot award itself credit for content that isn't in the document.
        """
        if self.value is None or self.evidence is None:
            return False
        normalised = self.value.strip().lower()
        if not normalised:
            return False
        return normalised not in {v.lower() for v in reject_values}


class CriterionExtraction(BaseModel):
    """One extractor run against one criterion."""

    criterion_id: str
    fields: list[FieldExtraction]
    not_applicable: bool = False
    not_applicable_reason: str | None = None

    def field(self, name: str) -> FieldExtraction | None:
        return next((f for f in self.fields if f.name == name), None)


def derive_verdict(criterion: Criterion, extraction: CriterionExtraction) -> Verdict:
    """Ternary verdict, mechanically derived. No model judgement involved.

    all required fields satisfied  -> PRESENT
    some but not all               -> PARTIAL
    none                           -> ABSENT
    """
    if extraction.not_applicable:
        if not criterion.allow_not_applicable:
            # The model tried to opt out of a criterion that has no opt-out.
            # Treat as absent rather than trusting it.
            return Verdict.ABSENT
        if not extraction.not_applicable_reason:
            return Verdict.ABSENT
        return Verdict.NOT_APPLICABLE

    required = criterion.required_fields
    hits = 0
    for spec in required:
        found = extraction.field(spec.name)
        if found is not None and found.is_satisfied(spec.reject_values):
            hits += 1

    if hits == len(required):
        return Verdict.PRESENT
    if hits == 0:
        return Verdict.ABSENT
    return Verdict.PARTIAL


def missing_fields(
    criterion: Criterion, extraction: CriterionExtraction
) -> list[str]:
    """Required field names that were not satisfied. Drives the question loop."""
    out: list[str] = []
    for spec in criterion.required_fields:
        found = extraction.field(spec.name)
        if found is None or not found.is_satisfied(spec.reject_values):
            out.append(spec.name)
    return out
