"""What the extractor returns, and how a raw extraction becomes a verdict.

The extractor is deliberately *not* asked to judge quality. It is asked to
locate facts and quote them. Extraction is far more reproducible than
evaluation, and it cannot be inflated by adjectives or document length.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from forge.rubric.models import Criterion, FieldSpec, Verdict


class Evidence(BaseModel):
    """A verbatim quote from the document. Required for any satisfied field."""

    quote: str = Field(min_length=1)
    section: str | None = None
    page: int | None = None
    provenance: Literal["document", "supplemental_answer"] = "document"
    source_block_id: str | None = None
    source_parent_block_id: str | None = None
    source_start_char: int | None = None
    source_end_char: int | None = None
    quote_start_char: int | None = None
    quote_end_char: int | None = None


class FieldExtraction(BaseModel):
    name: str
    # `string[]` rubric fields (non-goals, requirements, acceptance criteria)
    # are legitimately extracted as lists, so both shapes are accepted.
    value: str | list[str] | None = None
    evidence: Evidence | None = None
    # Populated by `verify_run` for list-valued fields. The extractor still
    # submits one field-level citation, but each list item must independently
    # occur in the source before contextual question tools may reuse it.
    # Excluded from serialized extraction payloads because it is verifier
    # output, never model input.
    item_evidence: list[Evidence] = Field(default_factory=list, exclude=True)

    def is_satisfied(self, spec: FieldSpec) -> bool:
        """A field counts only if it has a real value AND a citation.

        The evidence requirement is the anti-hallucination mechanism: the model
        cannot award itself credit for content that isn't in the document. The
        rubric's optional `value_pattern` additionally rejects values that are
        fluent but unfalsifiable.
        """
        if self.value is None or self.evidence is None:
            return False
        if not spec.matches_pattern(self.evidence.quote):
            return False
        rejected = {value.lower() for value in spec.reject_values}
        entries = self.value if isinstance(self.value, list) else [self.value]
        return any(
            entry.strip().lower() not in rejected and spec.matches_pattern(entry)
            for entry in entries
            if isinstance(entry, str) and entry.strip()
        )


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
        if found is not None and found.is_satisfied(spec):
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
        if found is None or not found.is_satisfied(spec):
            out.append(spec.name)
    return out


class SatisfiedFieldEvidence(BaseModel):
    """A field that already passed verification, kept for question phrasing.

    This is the only bridge between real document content and remediation
    question text. It is never used for scoring: `derive_verdict` and
    `missing_fields` above already ran before this is built, and nothing here
    feeds back into them. See `forge/score/contextualize.py`.
    """

    field_name: str
    description: str
    value: str
    quote: str
    section: str | None = None


def satisfied_field_evidence(
    criterion: Criterion, extraction: CriterionExtraction
) -> list[SatisfiedFieldEvidence]:
    """Already-satisfied fields (required or optional) with their evidence.

    Every entry here already passed `FieldExtraction.is_satisfied`, which
    requires a value AND a quote that `document.locate_quote` will verify
    downstream. Nothing new is asserted; this only re-packages facts Forge has
    already checked, so it is safe to hand to a model as reference material.
    """
    out: list[SatisfiedFieldEvidence] = []
    for spec in criterion.fields:
        field = extraction.field(spec.name)
        if field is None or field.evidence is None or not field.is_satisfied(spec):
            continue
        value = field.value
        if isinstance(value, list) and field.item_evidence:
            for evidence in field.item_evidence:
                out.append(
                    SatisfiedFieldEvidence(
                        field_name=spec.name,
                        description=spec.description.strip(),
                        value=evidence.quote,
                        quote=evidence.quote,
                        section=evidence.section,
                    )
                )
            continue
        rendered = (
            "; ".join(str(v) for v in value)
            if isinstance(value, list)
            else str(value)
        )
        out.append(
            SatisfiedFieldEvidence(
                field_name=spec.name,
                description=spec.description.strip(),
                value=rendered,
                quote=field.evidence.quote,
                section=field.evidence.section,
            )
        )
    return out
