from __future__ import annotations

from pathlib import Path

import pymupdf
from docx import Document

from forge.ingest.models import NormalizedDocument, SourceBlock, SupplementalAnswer


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".md", ".txt"}


def ingest_document(source: str | Path) -> NormalizedDocument:
    path = Path(source).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"document not found: {path}")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"unsupported document type {path.suffix!r}; use {supported}")

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        blocks = _pdf_blocks(path)
    elif suffix == ".docx":
        blocks = _docx_blocks(path)
    else:
        blocks = _text_blocks(path)

    if not blocks:
        raise ValueError(f"document contains no extractable text: {path}")
    return NormalizedDocument(
        source_path=str(path), source_type=suffix.removeprefix("."), blocks=blocks
    )


def add_supplemental_answers(
    document: NormalizedDocument, answers: list[SupplementalAnswer]
) -> NormalizedDocument:
    blocks = list(document.blocks)
    blocks.extend(
        SourceBlock(
            id=f"supplemental-answer-{index}",
            text=answer.answer,
            provenance="supplemental_answer",
            criterion_id=answer.criterion_id,
        )
        for index, answer in enumerate(answers, start=1)
    )
    return document.model_copy(update={"blocks": blocks})


def _pdf_blocks(path: Path) -> list[SourceBlock]:
    blocks: list[SourceBlock] = []
    with pymupdf.open(path) as pdf:
        for page_number, page in enumerate(pdf, start=1):
            text = page.get_text("text").strip()
            if text:
                blocks.append(
                    SourceBlock(id=f"page-{page_number}", text=text, page=page_number)
                )
    return blocks


def _docx_blocks(path: Path) -> list[SourceBlock]:
    document = Document(path)
    blocks: list[SourceBlock] = []
    section: str | None = None
    index = 0

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        index += 1
        if paragraph.style and paragraph.style.name.startswith("Heading"):
            section = text
        blocks.append(
            SourceBlock(id=f"paragraph-{index}", text=text, section=section)
        )

    for table_number, table in enumerate(document.tables, start=1):
        for row_number, row in enumerate(table.rows, start=1):
            cells = [cell.text.strip() for cell in row.cells]
            text = " | ".join(cell for cell in cells if cell)
            if text:
                blocks.append(
                    SourceBlock(
                        id=f"table-{table_number}-row-{row_number}",
                        text=text,
                        section=section,
                    )
                )
    return blocks


def _text_blocks(path: Path) -> list[SourceBlock]:
    text = path.read_text(encoding="utf-8").strip()
    return [SourceBlock(id="text-1", text=text)] if text else []
