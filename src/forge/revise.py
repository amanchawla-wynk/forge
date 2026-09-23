"""Explicitly materialize conversational answers into a new PRD revision."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from docx import Document
from pydantic import BaseModel

from forge.ingest.document import SUPPORTED_EXTENSIONS
from forge.ingest.models import SupplementalAnswer


class RevisionResult(BaseModel):
    source_path: str
    output_path: str
    supplemental_answer_count: int
    note: str


def materialize_prd_revision(
    source_path: str | Path,
    output_path: str | Path,
    supplemental_answers: list[SupplementalAnswer],
) -> RevisionResult:
    """Write answers into a new document while preserving the original."""
    source = Path(source_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"document not found: {source}")
    if not supplemental_answers:
        raise ValueError("at least one supplemental answer is required")
    if source == output:
        raise ValueError("output_path must differ from source_path")
    if output.exists():
        raise ValueError(f"output already exists: {output}")
    if not output.parent.exists():
        raise FileNotFoundError(f"output directory not found: {output.parent}")

    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"unsupported document type {suffix!r}; use {supported}")
    if suffix == ".pdf":
        raise ValueError(
            "PDF revisions are not written in place; use the editable DOCX, "
            "Markdown, or text source"
        )
    if output.suffix.lower() != suffix:
        raise ValueError("output_path must use the same file type as source_path")

    grouped: dict[str, list[str]] = defaultdict(list)
    for answer in supplemental_answers:
        grouped[answer.criterion_id].append(answer.answer)

    if suffix == ".docx":
        _write_docx_revision(source, output, grouped)
    else:
        _write_text_revision(source, output, grouped, markdown=suffix == ".md")

    return RevisionResult(
        source_path=str(source),
        output_path=str(output),
        supplemental_answer_count=len(supplemental_answers),
        note=(
            "Created a new revision and preserved the original. Reassess the "
            "output without supplemental answers to score the materialized text."
        ),
    )


def _write_docx_revision(
    source: Path, output: Path, grouped: dict[str, list[str]]
) -> None:
    document = Document(source)
    document.add_page_break()
    document.add_heading("Forge Clarifications", level=1)
    document.add_paragraph(
        "User-provided clarifications added after the initial readiness review."
    )
    for criterion_id, answers in grouped.items():
        document.add_heading(_criterion_title(criterion_id), level=2)
        for answer in answers:
            document.add_paragraph(answer)
    document.save(output)


def _write_text_revision(
    source: Path,
    output: Path,
    grouped: dict[str, list[str]],
    *,
    markdown: bool,
) -> None:
    heading = "# Forge Clarifications" if markdown else "FORGE CLARIFICATIONS"
    rendered = [
        source.read_text(encoding="utf-8").rstrip(),
        "",
        heading,
        "",
        "User-provided clarifications added after the initial readiness review.",
    ]
    for criterion_id, answers in grouped.items():
        title = _criterion_title(criterion_id)
        rendered.extend(["", f"## {title}" if markdown else title.upper(), ""])
        rendered.extend(answers)
    output.write_text("\n".join(rendered).rstrip() + "\n", encoding="utf-8")


def _criterion_title(criterion_id: str) -> str:
    return criterion_id.replace("_", " ").title()
