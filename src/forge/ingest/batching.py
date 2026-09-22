from __future__ import annotations

import hashlib
from dataclasses import dataclass

import semchunk

from forge.ingest.models import NormalizedDocument, SourceBlock


MAX_BATCH_CHARS = 120_000
_BLOCK_OVERHEAD_CHARS = 256
_OVERLAP_CHARS = 256


@dataclass(frozen=True)
class DocumentBatch:
    id: str
    document: NormalizedDocument


def batch_document(
    document: NormalizedDocument, max_chars: int = MAX_BATCH_CHARS
) -> list[DocumentBatch]:
    if max_chars <= _BLOCK_OVERHEAD_CHARS:
        raise ValueError("max_chars is too small for source metadata")

    if not document.blocks:
        return [DocumentBatch(id="batch-1", document=document)]

    blocks = [
        part
        for block in document.blocks
        for part in _split_oversized_block(document, block, max_chars)
    ]
    grouped: list[list[SourceBlock]] = []
    current: list[SourceBlock] = []

    for block in blocks:
        candidate = [*current, block]
        if current and len(_with_blocks(document, candidate).text) > max_chars:
            grouped.append(current)
            current = [block]
        else:
            current = candidate

    if current:
        grouped.append(current)

    return [
        DocumentBatch(
            id=f"batch-{index}",
            document=_with_blocks(document, blocks),
        )
        for index, blocks in enumerate(grouped, start=1)
    ]


def _split_oversized_block(
    document: NormalizedDocument, block: SourceBlock, max_chars: int
) -> list[SourceBlock]:
    if len(_with_blocks(document, [block]).text) <= max_chars:
        return [block]

    probe = block.model_copy(
        update={"id": f"{block.id}-part-999999", "text": "x"}
    )
    metadata_chars = len(_with_blocks(document, [probe]).text) - 1
    available_chars = max_chars - metadata_chars - _BLOCK_OVERHEAD_CHARS
    if available_chars <= _OVERLAP_CHARS:
        raise ValueError(f"source metadata for block {block.id!r} exceeds batch limit")

    chunker = semchunk.chunkerify(len, available_chars)
    chunks, offsets = chunker(block.text, offsets=True, overlap=_OVERLAP_CHARS)
    return [
        block.model_copy(
            update={
                "id": f"{block.id}-part-{index}",
                "text": chunk,
                "parent_id": block.id,
                "start_char": start,
                "end_char": end,
            }
        )
        for index, (chunk, (start, end)) in enumerate(
            zip(chunks, offsets, strict=True), start=1
        )
    ]


def _with_blocks(
    document: NormalizedDocument, blocks: list[SourceBlock]
) -> NormalizedDocument:
    return document.model_copy(update={"blocks": blocks})


def plan_fingerprint(batches: list[DocumentBatch], rubric_version: str) -> str:
    """Identify the exact inputs a batch plan was derived from.

    Supplemental answers change the normalized document, and therefore the
    batch boundaries. Binding fragments to this value stops a stale extraction
    from being scored as if it had seen the current evidence.
    """
    digest = hashlib.sha256()
    digest.update(rubric_version.encode("utf-8"))
    for batch in batches:
        digest.update(b"\x00")
        digest.update(batch.id.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(batch.document.text.encode("utf-8"))
    return digest.hexdigest()[:32]
