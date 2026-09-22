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


class SupplementalAnswer(BaseModel):
    criterion_id: str = Field(min_length=1)
    answer: str = Field(min_length=1)

    @field_validator("criterion_id", "answer")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class NormalizedDocument(BaseModel):
    source_path: str
    source_type: str
    blocks: list[SourceBlock]

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
        needle = normalize_for_match(quote)
        if not needle:
            return None
        for block in self.blocks:
            if needle in normalize_for_match(block.text):
                return block
        return None

    @property
    def name(self) -> str:
        return Path(self.source_path).name
