from __future__ import annotations

from docx import Document
import pytest

from forge.ingest.document import ingest_document
from forge.ingest.models import SupplementalAnswer
from forge.revise import materialize_prd_revision


def test_materializes_answers_into_new_markdown_revision(tmp_path):
    source = tmp_path / "prd.md"
    output = tmp_path / "prd-revised.md"
    source.write_text("# Original PRD\n\nUsers cannot export invoices.\n")
    answers = [
        SupplementalAnswer(
            criterion_id="problem_statement",
            answer="Finance administrators are affected, based on 42 tickets.",
        ),
        SupplementalAnswer(
            criterion_id="success_metrics",
            answer="Reduce export failures from 8% to 1% within 30 days.",
        ),
    ]

    result = materialize_prd_revision(source, output, answers)

    assert source.read_text() == "# Original PRD\n\nUsers cannot export invoices.\n"
    assert result.supplemental_answer_count == 2
    revised = output.read_text()
    assert "# Forge Clarifications" in revised
    assert "## Problem Statement" in revised
    assert answers[0].answer in revised
    assert ingest_document(output).locate_quote(answers[1].answer) is not None


def test_materializes_answers_into_new_docx_revision(tmp_path):
    source = tmp_path / "prd.docx"
    output = tmp_path / "prd-revised.docx"
    document = Document()
    document.add_heading("Original PRD", level=1)
    document.add_paragraph("Users cannot export invoices.")
    document.save(source)
    answer = SupplementalAnswer(
        criterion_id="problem_statement",
        answer="Finance administrators are affected, based on 42 tickets.",
    )

    materialize_prd_revision(source, output, [answer])

    assert answer.answer in [paragraph.text for paragraph in Document(output).paragraphs]
    assert ingest_document(output).locate_quote(answer.answer) is not None


def test_revision_never_overwrites_source_or_existing_output(tmp_path):
    source = tmp_path / "prd.txt"
    source.write_text("Original")
    answer = SupplementalAnswer(criterion_id="non_goals", answer="Mobile is excluded.")

    with pytest.raises(ValueError, match="must differ"):
        materialize_prd_revision(source, source, [answer])

    output = tmp_path / "existing.txt"
    output.write_text("Do not replace")
    with pytest.raises(ValueError, match="already exists"):
        materialize_prd_revision(source, output, [answer])
