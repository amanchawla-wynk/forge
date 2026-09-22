from __future__ import annotations

from pydantic import BaseModel, Field

from forge.extract.models import CriterionExtraction, Evidence
from forge.ingest.models import NormalizedDocument


class ExtractionRun(BaseModel):
    criteria: list[CriterionExtraction]


class ExtractionBatch(BaseModel):
    runs: list[ExtractionRun] = Field(min_length=1)


def verify_run(
    document: NormalizedDocument, run: ExtractionRun
) -> list[CriterionExtraction]:
    """Return a copy with only source-verifiable evidence retained."""
    verified: list[CriterionExtraction] = []
    for criterion in run.criteria:
        criterion_copy = criterion.model_copy(deep=True)
        for field in criterion_copy.fields:
            if field.evidence is None:
                continue
            block = document.locate_quote(field.evidence.quote)
            if block is None:
                field.evidence = None
                continue
            if (
                block.provenance == "supplemental_answer"
                and block.criterion_id != criterion.criterion_id
            ):
                field.evidence = None
                continue
            field.evidence = Evidence(
                quote=field.evidence.quote,
                section=block.section,
                page=block.page,
                provenance=block.provenance,
                source_block_id=block.id,
            )
        verified.append(criterion_copy)
    return verified
