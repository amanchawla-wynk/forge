from __future__ import annotations

from pydantic import BaseModel, Field

from forge.extract.models import CriterionExtraction, Evidence, FieldExtraction
from forge.ingest.batching import DocumentBatch, plan_fingerprint
from forge.ingest.models import NormalizedDocument
from forge.rubric.models import Rubric


class ExtractionFragment(BaseModel):
    batch_id: str
    criteria: list[CriterionExtraction]
    run_index: int | None = None
    plan_fingerprint: str | None = None


class ExtractionRun(BaseModel):
    criteria: list[CriterionExtraction] = Field(default_factory=list)
    fragments: list[ExtractionFragment] = Field(default_factory=list)


class ExtractionBatch(BaseModel):
    runs: list[ExtractionRun] = Field(min_length=1)


def verify_extraction_batch(
    batches: list[DocumentBatch], batch: ExtractionBatch, rubric: Rubric
) -> list[list[CriterionExtraction]]:
    """Verify every submitted run against the prepared document batches."""
    _validate_run_indexes(batch.runs)
    return [verify_extraction_run(batches, run, rubric) for run in batch.runs]


def verify_extraction_run(
    batches: list[DocumentBatch], run: ExtractionRun, rubric: Rubric
) -> list[CriterionExtraction]:
    if run.criteria and run.fragments:
        raise ValueError("an extraction run cannot contain criteria and fragments")
    if run.fragments:
        by_id = {batch.id: batch for batch in batches}
        fragment_ids = [fragment.batch_id for fragment in run.fragments]
        if len(fragment_ids) != len(set(fragment_ids)):
            raise ValueError("an extraction run contains duplicate batch fragments")
        missing = sorted(set(by_id) - set(fragment_ids))
        unknown = sorted(set(fragment_ids) - set(by_id))
        if missing or unknown:
            details = []
            if missing:
                details.append("missing " + ", ".join(missing))
            if unknown:
                details.append("unknown " + ", ".join(unknown))
            raise ValueError("invalid extraction fragments: " + "; ".join(details))
        _validate_plan_fingerprint(batches, run, rubric)
        verified = [
            verify_run(
                by_id[fragment.batch_id].document,
                ExtractionRun(
                    criteria=_validate_fragment_schema(rubric, fragment.criteria)
                ),
            )
            for fragment in run.fragments
        ]
        return _consolidate_fragments(rubric, verified)

    if len(batches) > 1:
        raise ValueError(
            "document requires batched extraction; submit every prepared batch fragment"
        )
    return verify_run(batches[0].document, run)


def verify_run(
    document: NormalizedDocument, run: ExtractionRun
) -> list[CriterionExtraction]:
    """Return a copy with only source-verifiable evidence retained."""
    verified: list[CriterionExtraction] = []
    for criterion in run.criteria:
        criterion_copy = criterion.model_copy(deep=True)
        if criterion_copy.not_applicable:
            reason = criterion_copy.not_applicable_reason
            if not reason or document.locate_quote(reason) is None:
                criterion_copy.not_applicable = False
                criterion_copy.not_applicable_reason = None
        for field in criterion_copy.fields:
            field.item_evidence = []
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
                source_parent_block_id=block.parent_id,
                source_start_char=block.start_char,
                source_end_char=block.end_char,
            )
            if isinstance(field.value, list):
                for item in field.value:
                    item_block = document.locate_quote(item)
                    if item_block is None:
                        continue
                    if (
                        item_block.provenance == "supplemental_answer"
                        and item_block.criterion_id != criterion.criterion_id
                    ):
                        continue
                    field.item_evidence.append(
                        Evidence(
                            quote=item,
                            section=item_block.section,
                            page=item_block.page,
                            provenance=item_block.provenance,
                            source_block_id=item_block.id,
                            source_parent_block_id=item_block.parent_id,
                            source_start_char=item_block.start_char,
                            source_end_char=item_block.end_char,
                        )
                    )
        verified.append(criterion_copy)
    return verified


def _validate_plan_fingerprint(
    batches: list[DocumentBatch], run: ExtractionRun, rubric: Rubric
) -> None:
    """Reject fragments that were produced from different inputs.

    Supplemental answers change batch boundaries, so a fragment extracted
    before the latest answer cannot be scored as current evidence.
    """
    supplied = {
        fragment.plan_fingerprint
        for fragment in run.fragments
        if fragment.plan_fingerprint is not None
    }
    if not supplied:
        return
    expected = plan_fingerprint(batches, rubric.version)
    stale = sorted(value for value in supplied if value != expected)
    if stale:
        raise ValueError(
            "extraction fragments were produced from a stale batch plan "
            f"({', '.join(stale)}; expected {expected}). Re-run list_prd_batches "
            "and assess_prd_batch with the current supplemental answers."
        )


def _validate_run_indexes(runs: list[ExtractionRun]) -> None:
    """Reject ambiguous or duplicated run identity in batched submissions."""
    indexed = [
        run
        for run in runs
        if any(fragment.run_index is not None for fragment in run.fragments)
    ]
    if not indexed:
        return
    if len(indexed) != len(runs):
        raise ValueError(
            "run_index must be supplied for every run or omitted from all of them"
        )

    seen: set[int] = set()
    for run in runs:
        indexes = {fragment.run_index for fragment in run.fragments}
        if None in indexes:
            raise ValueError(
                "every fragment in a run must carry the same run_index"
            )
        if len(indexes) != 1:
            raise ValueError(
                "fragments from different runs were submitted as one run: "
                + ", ".join(str(index) for index in sorted(indexes))
            )
        index = indexes.pop()
        if index in seen:
            raise ValueError(
                f"run_index {index} was submitted more than once; "
                "repeated runs cannot establish test/retest stability"
            )
        seen.add(index)


def _validate_fragment_schema(
    rubric: Rubric, criteria: list[CriterionExtraction]
) -> list[CriterionExtraction]:
    criterion_ids = [criterion.criterion_id for criterion in criteria]
    if len(criterion_ids) != len(set(criterion_ids)):
        raise ValueError("an extraction fragment contains duplicate criteria")

    expected_criteria = {criterion.id for criterion in rubric.criteria}
    actual_criteria = set(criterion_ids)
    if actual_criteria != expected_criteria:
        missing = sorted(expected_criteria - actual_criteria)
        unknown = sorted(actual_criteria - expected_criteria)
        details = []
        if missing:
            details.append("missing criteria " + ", ".join(missing))
        if unknown:
            details.append("unknown criteria " + ", ".join(unknown))
        raise ValueError("invalid extraction fragment schema: " + "; ".join(details))

    for extraction in criteria:
        criterion = rubric.criterion(extraction.criterion_id)
        field_names = [field.name for field in extraction.fields]
        if len(field_names) != len(set(field_names)):
            raise ValueError(
                f"criterion {criterion.id} contains duplicate fields"
            )
        expected_fields = {field.name for field in criterion.fields}
        actual_fields = set(field_names)
        if actual_fields != expected_fields:
            missing = sorted(expected_fields - actual_fields)
            unknown = sorted(actual_fields - expected_fields)
            details = []
            if missing:
                details.append("missing " + ", ".join(missing))
            if unknown:
                details.append("unknown " + ", ".join(unknown))
            raise ValueError(
                f"invalid fields for criterion {criterion.id}: "
                + "; ".join(details)
            )
    return criteria


def _consolidate_fragments(
    rubric: Rubric, fragments: list[list[CriterionExtraction]]
) -> list[CriterionExtraction]:
    consolidated: list[CriterionExtraction] = []
    for criterion in rubric.criteria:
        extractions = [
            extraction
            for fragment in fragments
            for extraction in fragment
            if extraction.criterion_id == criterion.id
        ]
        fields: list[FieldExtraction] = []
        for field_spec in criterion.fields:
            candidates = [
                field
                for extraction in extractions
                for field in extraction.fields
                if field.name == field_spec.name
            ]
            satisfied = next(
                (
                    field
                    for field in candidates
                    if field.is_satisfied(field_spec)
                ),
                None,
            )
            fields.append(
                (satisfied or candidates[0]).model_copy(deep=True)
                if satisfied or candidates
                else FieldExtraction(name=field_spec.name)
            )

        has_evidence = any(field.evidence is not None for field in fields)
        not_applicable = next(
            (
                extraction
                for extraction in extractions
                if extraction.not_applicable and extraction.not_applicable_reason
            ),
            None,
        )
        consolidated.append(
            CriterionExtraction(
                criterion_id=criterion.id,
                fields=fields,
                not_applicable=bool(not_applicable) and not has_evidence,
                not_applicable_reason=(
                    not_applicable.not_applicable_reason
                    if not_applicable and not has_evidence
                    else None
                ),
            )
        )
    return consolidated
