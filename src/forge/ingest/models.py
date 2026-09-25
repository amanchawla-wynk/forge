from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


class SourceBlock(BaseModel):
    id: str
    text: str = Field(min_length=1)
    page: int | None = None
    section: str | None = None
    provenance: Literal["document", "supplemental_answer"] = "document"
    criterion_id: str | None = None
    parent_id: str | None = None
    start_char: int | None = None
    end_char: int | None = None


class VisualAsset(BaseModel):
    id: str
    media_type: str
    page: int | None = None
    section: str | None = None
    # Format-specific handle used to fetch the bytes again on demand, so the
    # document model never carries image payloads.
    locator: str | None = None


class SupplementalAnswer(BaseModel):
    criterion_id: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    # Optional identity for one cell in the edge-case coverage ledger. This
    # keeps repeated answers to the same broad criterion distinguishable.
    requirement_quote: str | None = None
    edge_case_id: str | None = None
    taxonomy_version: str | None = None

    @field_validator("criterion_id", "answer")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class ProductContextTerm(BaseModel):
    term: str = Field(min_length=1)
    meaning: str = Field(min_length=1)
    source_ref: str | None = None

    @field_validator("term", "meaning")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class NormalizedDocument(BaseModel):
    source_path: str
    source_type: str
    blocks: list[SourceBlock]
    visual_assets: list[VisualAsset] = Field(default_factory=list)
    product_context: list[ProductContextTerm] = Field(default_factory=list)

    @property
    def text(self) -> str:
        rendered: list[str] = []
        for block in self.blocks:
            location = [f"block={block.id}", f"provenance={block.provenance}"]
            if block.page is not None:
                location.append(f"page={block.page}")
            if block.section:
                location.append(f"section={block.section}")
            if block.criterion_id:
                location.append(f"criterion={block.criterion_id}")
            rendered.append(f"[{' '.join(location)}]\n{block.text}")
        return "\n\n".join(rendered)

    def locate_quote(self, quote: str) -> SourceBlock | None:
        located = self.locate_quote_span(quote)
        return located[0] if located is not None else None

    def locate_quote_span(self, quote: str) -> tuple[SourceBlock, int, int] | None:
        """Locate a quote and retain its exact span within the source block."""
        needle = normalize_for_match(quote)
        if not needle:
            return None
        for block in self.blocks:
            exact_start = block.text.find(quote)
            if exact_start >= 0:
                return block, exact_start, exact_start + len(quote)

            words = quote.strip().split()
            if not words:
                continue
            pattern = r"\s+".join(re.escape(word) for word in words)
            match = re.search(pattern, block.text, flags=re.IGNORECASE)
            if match is not None and normalize_for_match(match.group()) == needle:
                return block, match.start(), match.end()
        return None

    @property
    def name(self) -> str:
        return Path(self.source_path).name
