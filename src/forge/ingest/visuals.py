"""On-demand rendering of detected visual assets.

Image bytes are never stored on the normalized document: an assessment only
needs the text corpus, and carrying payloads would bloat every response. The
bytes are produced here, once, when a caller explicitly asks to look at one
asset.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf
from docx import Document

from forge.ingest.models import NormalizedDocument, VisualAsset


# Sampling transports carry base64 text, which is roughly a third larger than
# the raw bytes. Refuse early rather than emitting an unusable request.
MAX_VISUAL_BYTES = 4_000_000
_PDF_RENDER_DPI = 144


@dataclass(frozen=True)
class RenderedVisual:
    asset: VisualAsset
    data: bytes
    media_type: str


def render_visual_asset(
    document: NormalizedDocument, asset_id: str
) -> RenderedVisual:
    asset = next(
        (item for item in document.visual_assets if item.id == asset_id), None
    )
    if asset is None:
        known = ", ".join(item.id for item in document.visual_assets)
        raise ValueError(
            f"unknown asset_id {asset_id!r}; "
            + (f"expected one of: {known}" if known else "this document has none")
        )

    path = Path(document.source_path)
    if document.source_type == "pdf":
        rendered = _render_pdf_page(path, asset)
    elif document.source_type == "docx":
        rendered = _extract_docx_image(path, asset)
    else:
        raise ValueError(
            f"visual rendering is not supported for {document.source_type!r} sources"
        )

    if len(rendered.data) > MAX_VISUAL_BYTES:
        raise ValueError(
            f"visual asset {asset_id!r} is {len(rendered.data):,} bytes, above the "
            f"{MAX_VISUAL_BYTES:,} byte sampling limit"
        )
    return rendered


def _render_pdf_page(path: Path, asset: VisualAsset) -> RenderedVisual:
    if asset.page is None:
        raise ValueError(f"visual asset {asset.id!r} has no page to render")
    with pymupdf.open(path) as pdf:
        page = pdf[asset.page - 1]
        pixmap = page.get_pixmap(dpi=_PDF_RENDER_DPI)
        return RenderedVisual(
            asset=asset, data=pixmap.tobytes("png"), media_type="image/png"
        )


def _extract_docx_image(path: Path, asset: VisualAsset) -> RenderedVisual:
    if asset.locator is None:
        raise ValueError(f"visual asset {asset.id!r} has no embedded image locator")
    document = Document(path)
    relationship = document.part.rels.get(asset.locator)
    if relationship is None:
        raise ValueError(f"visual asset {asset.id!r} is no longer present")
    part = relationship.target_part
    return RenderedVisual(
        asset=asset, data=part.blob, media_type=part.content_type
    )
