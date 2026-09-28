from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


CANONICAL_NODE_SCHEMA_VERSION = "1.0"


class TableNodeMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    table_id: str
    row: int | None = None
    column: int | None = None


class LinkNodeMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    target: str
    title: str | None = None


class AssetNodeMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset_id: str
    media_type: str
    locator: str | None = None


class NodeProvenance(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_block_id: str | None = None
    parser: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CanonicalNode(BaseModel):
    """Versioned, source-neutral unit emitted by document parsers."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1.0"] = CANONICAL_NODE_SCHEMA_VERSION
    node_id: str = Field(min_length=1)
    parent_id: str | None = None
    order: int = Field(ge=0)
    kind: Literal[
        "paragraph",
        "page",
        "table_row",
        "heading",
        "header",
        "footer",
        "visual",
        "link",
    ]
    content: str = ""
    heading_path: tuple[str, ...] = ()
    page: int | None = Field(default=None, ge=1)
    bbox: tuple[float, float, float, float] | None = None
    table: TableNodeMetadata | None = None
    link: LinkNodeMetadata | None = None
    asset: AssetNodeMetadata | None = None
    provenance: NodeProvenance | None = None
