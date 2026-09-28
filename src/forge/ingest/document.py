from __future__ import annotations

from pathlib import Path

from forge.ingest.adapters import (
    SUPPORTED_EXTENSIONS,
    LocalFileSourceAdapter,
    SourceRef,
)

from forge.ingest.models import (
    NormalizedDocument,
    ProductContextTerm,
    SourceBlock,
    SupplementalAnswer,
)
from forge.ingest.parsers import LegacyDocumentParser
from forge.ingest.snapshot import (
    DocumentSnapshot,
    SnapshotCache,
    SnapshotRepository,
    build_snapshot,
    cache_key,
)


_SNAPSHOT_CACHE = SnapshotCache()


def ingest_document(source: str | Path) -> NormalizedDocument:
    return ingest_snapshot(source).document.model_copy(deep=True)


def ingest_snapshot(
    source: str | Path,
    repository: SnapshotRepository | None = None,
) -> DocumentSnapshot:
    adapter = LocalFileSourceAdapter()
    parser = LegacyDocumentParser()
    artifact = adapter.acquire(SourceRef.local_file(source))
    repository = repository or _SNAPSHOT_CACHE
    key = cache_key(artifact, parser.fingerprint)
    cached = repository.get(key)
    if cached is not None:
        return cached
    snapshot = build_snapshot(artifact, parser.parse(artifact), parser.fingerprint)
    repository.put(key, snapshot)
    return snapshot


def add_supplemental_answers(
    document: NormalizedDocument, answers: list[SupplementalAnswer]
) -> NormalizedDocument:
    answer_ids = [
        answer.answer_id for answer in answers if answer.answer_id is not None
    ]
    if len(answer_ids) != len(set(answer_ids)):
        raise ValueError("supplemental answer_id values must be unique")
    blocks = list(document.blocks)
    blocks.extend(
        SourceBlock(
            id=(
                f"supplemental-answer-{answer.answer_id}"
                if answer.answer_id is not None
                else f"supplemental-answer-{index}"
            ),
            text=answer.answer,
            provenance="supplemental_answer",
            criterion_id=answer.criterion_id,
        )
        for index, answer in enumerate(answers, start=1)
    )
    return document.model_copy(update={"blocks": blocks})


def add_product_context(
    document: NormalizedDocument, terms: list[ProductContextTerm]
) -> NormalizedDocument:
    """Attach non-evidence terminology context for extraction disambiguation."""
    return document.model_copy(update={"product_context": terms})
