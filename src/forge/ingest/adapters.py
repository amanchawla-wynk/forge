from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


SUPPORTED_SOURCE_TYPES = frozenset({"pdf", "docx", "md", "txt"})
SUPPORTED_EXTENSIONS = frozenset(f".{source_type}" for source_type in SUPPORTED_SOURCE_TYPES)

_MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "md": "text/markdown",
    "txt": "text/plain",
}


class SourceRef(BaseModel):
    """Source-neutral reference to content that an acquisition adapter can load."""

    model_config = ConfigDict(frozen=True)

    origin: Literal["local_file", "inline", "external"]
    locator: str | None = None
    display_name: str | None = None
    source_type: str | None = None
    media_type: str | None = None
    origin_metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def local_file(cls, source: str | Path) -> SourceRef:
        return cls(origin="local_file", locator=str(source))


class SourceArtifact(BaseModel):
    """Acquired source bytes plus identity and origin metadata."""

    model_config = ConfigDict(
        frozen=True,
        ser_json_bytes="base64",
        val_json_bytes="base64",
    )

    content: bytes
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    display_name: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    origin: Literal["local_file", "inline", "external"]
    origin_locator: str | None = None
    origin_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_content_hash(self) -> SourceArtifact:
        if hashlib.sha256(self.content).hexdigest() != self.sha256:
            raise ValueError("sha256 does not match source content")
        return self


class SourceAdapter(Protocol):
    def acquire(self, source: SourceRef) -> SourceArtifact: ...


class LocalFileSourceAdapter:
    """Acquire one supported local file without leaking path reads into parsers."""

    def acquire(self, source: SourceRef) -> SourceArtifact:
        if source.origin != "local_file":
            raise ValueError(
                "LocalFileSourceAdapter only supports local_file origins; "
                "inline and external acquisition are not implemented"
            )
        if source.locator is None:
            raise ValueError("local_file source requires a locator")

        path = Path(source.locator).expanduser().resolve()
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"document not found: {path}")
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
            raise ValueError(f"unsupported document type {path.suffix!r}; use {supported}")

        source_type = suffix.removeprefix(".")
        if source.source_type is not None and source.source_type.lower() != source_type:
            raise ValueError(
                f"source type {source.source_type!r} does not match file extension {suffix!r}"
            )
        media_type = _MEDIA_TYPES[source_type]
        if source.media_type is not None and source.media_type != media_type:
            raise ValueError(
                f"media type {source.media_type!r} does not match source type {source_type!r}"
            )

        content = path.read_bytes()
        return SourceArtifact(
            content=content,
            sha256=hashlib.sha256(content).hexdigest(),
            display_name=source.display_name or path.name,
            source_type=source_type,
            media_type=media_type,
            origin="local_file",
            origin_locator=str(path),
            origin_metadata={**source.origin_metadata, "resolved_path": str(path)},
        )
