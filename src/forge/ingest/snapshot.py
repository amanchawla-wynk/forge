from __future__ import annotations

import hashlib
import json
from pathlib import Path
from threading import RLock
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from forge.ingest.adapters import SourceArtifact
from forge.ingest.models import NormalizedDocument
from forge.ingest.nodes import CanonicalNode
from forge.ingest.parsers import ParsedDocument


NORMALIZED_SCHEMA_VERSION = "1.0"


class DocumentSnapshot(BaseModel):
    """Immutable parse result identified only by content and behavior versions."""

    model_config = ConfigDict(
        frozen=True,
        ser_json_bytes="base64",
        val_json_bytes="base64",
    )

    snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_schema_version: str
    parser_fingerprint: str
    normalized_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: SourceArtifact
    document: NormalizedDocument
    canonical_nodes: tuple[CanonicalNode, ...]

    @model_validator(mode="after")
    def validate_identity(self) -> DocumentSnapshot:
        if self.document.source_type != self.source.source_type:
            raise ValueError("document source_type does not match snapshot source")
        metadata = {
            "snapshot_id": self.snapshot_id,
            "source_sha256": self.source.sha256,
            "parser_fingerprint": self.parser_fingerprint,
            "normalized_hash": self.normalized_hash,
            "normalized_schema_version": self.normalized_schema_version,
        }
        for field, expected in metadata.items():
            if getattr(self.document, field) != expected:
                raise ValueError(f"document {field} does not match snapshot identity")
        if normalized_hash(self.document, self.canonical_nodes) != self.normalized_hash:
            raise ValueError("normalized_hash does not match normalized snapshot content")
        if snapshot_id(
            self.source.sha256,
            self.source.source_type,
            self.parser_fingerprint,
            self.normalized_schema_version,
            self.normalized_hash,
        ) != self.snapshot_id:
            raise ValueError("snapshot_id does not match snapshot identity")
        return self


class SnapshotCacheKey(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_sha256: str
    source_type: str
    parser_fingerprint: str
    normalized_schema_version: str
    origin_locator: str | None

    def as_tuple(self) -> tuple[str, str, str, str, str | None]:
        return (
            self.source_sha256,
            self.source_type,
            self.parser_fingerprint,
            self.normalized_schema_version,
            self.origin_locator,
        )


class SnapshotRepository(Protocol):
    def get(self, key: SnapshotCacheKey) -> DocumentSnapshot | None: ...

    def put(self, key: SnapshotCacheKey, snapshot: DocumentSnapshot) -> None: ...


class SnapshotCache:
    """Thread-safe, in-process repository with no fuzzy or fallback lookup."""

    def __init__(self) -> None:
        self._snapshots: dict[
            tuple[str, str, str, str, str | None], DocumentSnapshot
        ] = {}
        self._lock = RLock()

    def get(self, key: SnapshotCacheKey) -> DocumentSnapshot | None:
        with self._lock:
            return self._snapshots.get(key.as_tuple())

    def put(self, key: SnapshotCacheKey, snapshot: DocumentSnapshot) -> None:
        with self._lock:
            self._snapshots[key.as_tuple()] = snapshot


def cache_key(
    artifact: SourceArtifact, parser_fingerprint: str
) -> SnapshotCacheKey:
    return SnapshotCacheKey(
        source_sha256=artifact.sha256,
        source_type=artifact.source_type,
        parser_fingerprint=parser_fingerprint,
        normalized_schema_version=NORMALIZED_SCHEMA_VERSION,
        origin_locator=artifact.origin_locator,
    )


def build_snapshot(
    artifact: SourceArtifact,
    parsed: ParsedDocument,
    parser_fingerprint: str,
) -> DocumentSnapshot:
    content_hash = normalized_hash(parsed.document, parsed.canonical_nodes)
    identity = snapshot_id(
        artifact.sha256,
        artifact.source_type,
        parser_fingerprint,
        NORMALIZED_SCHEMA_VERSION,
        content_hash,
    )
    document = parsed.document.model_copy(
        update={
            "snapshot_id": identity,
            "source_sha256": artifact.sha256,
            "parser_fingerprint": parser_fingerprint,
            "normalized_hash": content_hash,
            "normalized_schema_version": NORMALIZED_SCHEMA_VERSION,
        },
        deep=True,
    )
    return DocumentSnapshot(
        snapshot_id=identity,
        normalized_schema_version=NORMALIZED_SCHEMA_VERSION,
        parser_fingerprint=parser_fingerprint,
        normalized_hash=content_hash,
        source=artifact,
        document=document,
        canonical_nodes=parsed.canonical_nodes,
    )


def rebind_snapshot_origin(
    snapshot: DocumentSnapshot,
    source: SourceArtifact | str | Path,
) -> DocumentSnapshot:
    """Return the same content snapshot with current origin-facing metadata."""
    if isinstance(source, SourceArtifact):
        artifact = source
    else:
        path = Path(source).expanduser().resolve()
        source_type = path.suffix.lower().removeprefix(".")
        if source_type != snapshot.source.source_type:
            raise ValueError("local source type does not match snapshot source type")
        artifact = SourceArtifact(
            content=snapshot.source.content,
            sha256=snapshot.source.sha256,
            display_name=path.name,
            source_type=snapshot.source.source_type,
            media_type=snapshot.source.media_type,
            origin="local_file",
            origin_locator=str(path),
            origin_metadata={"resolved_path": str(path)},
        )

    if artifact.content != snapshot.source.content:
        raise ValueError("source content does not match snapshot content")
    if artifact.sha256 != snapshot.source.sha256:
        raise ValueError("source hash does not match snapshot identity")
    if artifact.source_type != snapshot.source.source_type:
        raise ValueError("source type does not match snapshot identity")

    document = snapshot.document.model_copy(
        update={"source_path": artifact.origin_locator or artifact.display_name},
        deep=True,
    )
    return DocumentSnapshot(
        snapshot_id=snapshot.snapshot_id,
        normalized_schema_version=snapshot.normalized_schema_version,
        parser_fingerprint=snapshot.parser_fingerprint,
        normalized_hash=snapshot.normalized_hash,
        source=artifact,
        document=document,
        canonical_nodes=snapshot.canonical_nodes,
    )


def normalized_hash(
    document: NormalizedDocument, canonical_nodes: tuple[CanonicalNode, ...]
) -> str:
    """Hash normalized content only; snapshot metadata is deliberately excluded."""
    return _hash_json(
        {
            "source_type": document.source_type,
            "blocks": [block.model_dump(mode="json") for block in document.blocks],
            "visual_assets": [
                asset.model_dump(mode="json") for asset in document.visual_assets
            ],
            "canonical_nodes": [
                node.model_dump(mode="json") for node in canonical_nodes
            ],
        }
    )


def snapshot_id(
    source_sha256: str,
    source_type: str,
    parser_fingerprint: str,
    normalized_schema_version: str,
    normalized_hash_value: str,
) -> str:
    return _hash_json(
        {
            "source_sha256": source_sha256,
            "source_type": source_type,
            "parser_fingerprint": parser_fingerprint,
            "normalized_schema_version": normalized_schema_version,
            "normalized_hash": normalized_hash_value,
        }
    )


def _hash_json(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
