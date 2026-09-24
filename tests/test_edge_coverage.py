from __future__ import annotations

import json

import pytest

from forge.ingest.document import add_supplemental_answers, ingest_document
from forge.ingest.models import SupplementalAnswer
from forge.rubric.models import Verdict
from forge.score.edge_coverage import (
    CoverageStatus,
    EdgeCaseCoverageItem,
    EdgeCaseCoverageLedger,
    apply_coverage_answers,
    coverage_verdict,
    consolidate_coverage_ledgers,
    next_uncovered_item,
    verify_coverage_ledger,
)
from forge.service import assess_extraction_json


REQUIREMENT = "Progress syncs with the backend every 10 seconds."
COVERAGE = "When offline, progress is queued and synced after reconnection."


def _item(
    status: CoverageStatus, evidence_quote: str | None = None
) -> EdgeCaseCoverageItem:
    return EdgeCaseCoverageItem(
        requirement_criterion_id="functional_requirements",
        requirement_field="requirements",
        requirement_quote=REQUIREMENT,
        edge_case_id="connectivity_loss",
        status=status,
        evidence_quote=evidence_quote,
    )


def test_coverage_verification_accepts_source_backed_positive_claim(tmp_path):
    path = tmp_path / "prd.md"
    path.write_text(f"{REQUIREMENT}\n{COVERAGE}")
    ledger = verify_coverage_ledger(
        ingest_document(path),
        EdgeCaseCoverageLedger(items=[_item(CoverageStatus.COVERED, COVERAGE)]),
    )

    assert ledger.items[0].status is CoverageStatus.COVERED
    assert ledger.items[0].requirement_block_id is not None
    assert ledger.items[0].evidence_block_id is not None
    assert ledger.is_complete
    assert coverage_verdict(ledger) is Verdict.PRESENT


def test_unverified_positive_claim_is_downgraded_to_unclear(tmp_path):
    path = tmp_path / "prd.md"
    path.write_text(REQUIREMENT)
    ledger = verify_coverage_ledger(
        ingest_document(path),
        EdgeCaseCoverageLedger(
            items=[_item(CoverageStatus.COVERED, "Invented offline behavior.")]
        ),
    )

    assert ledger.items[0].status is CoverageStatus.UNCLEAR
    assert ledger.items[0].evidence_quote is None
    assert not ledger.is_complete
    assert coverage_verdict(ledger) is Verdict.ABSENT


def test_criterion_bound_supplemental_answer_can_cover_one_cell(tmp_path):
    path = tmp_path / "prd.md"
    path.write_text(REQUIREMENT)
    answer = SupplementalAnswer(
        criterion_id="edge_cases_and_states",
        answer=COVERAGE,
        requirement_quote=REQUIREMENT,
        edge_case_id="connectivity_loss",
        taxonomy_version="1.0",
    )
    document = add_supplemental_answers(ingest_document(path), [answer])
    supplied = EdgeCaseCoverageLedger(items=[_item(CoverageStatus.MISSING)])
    updated = apply_coverage_answers(supplied, [answer])
    ledger = verify_coverage_ledger(
        document,
        updated,
    )

    assert ledger.items[0].status is CoverageStatus.COVERED
    assert ledger.items[0].evidence_block_id == "supplemental-answer-1"


def test_duplicate_requirement_taxonomy_pair_is_rejected(tmp_path):
    path = tmp_path / "prd.md"
    path.write_text(REQUIREMENT)
    ledger = EdgeCaseCoverageLedger(
        items=[_item(CoverageStatus.MISSING), _item(CoverageStatus.UNCLEAR)]
    )
    with pytest.raises(ValueError, match="duplicate pair"):
        verify_coverage_ledger(ingest_document(path), ledger)


def test_stopping_rule_requires_every_pair_covered_or_not_applicable():
    covered = _item(CoverageStatus.COVERED, COVERAGE)
    second = _item(CoverageStatus.NOT_APPLICABLE, REQUIREMENT)
    second.edge_case_id = "duplicate_or_retry"
    complete = EdgeCaseCoverageLedger(items=[covered, second])
    assert complete.is_complete
    assert next_uncovered_item(complete) is None

    second.status = CoverageStatus.MISSING
    second.evidence_quote = None
    incomplete = EdgeCaseCoverageLedger(items=[covered, second])
    assert not incomplete.is_complete
    assert next_uncovered_item(incomplete) == second


def test_coverage_runs_use_modal_status_and_pessimistic_tie_break():
    covered = EdgeCaseCoverageLedger(
        items=[_item(CoverageStatus.COVERED, COVERAGE)]
    )
    missing = EdgeCaseCoverageLedger(items=[_item(CoverageStatus.MISSING)])
    consolidated, agreement = consolidate_coverage_ledgers(
        [covered, missing, missing]
    )
    assert consolidated.items[0].status is CoverageStatus.MISSING
    assert agreement == [pytest.approx(2 / 3)]

    tied, agreement = consolidate_coverage_ledgers([covered, missing])
    assert tied.items[0].status is CoverageStatus.MISSING
    assert agreement == [0.5]


def test_ledger_overrides_coarse_edge_field_and_drives_question(tmp_path):
    path = tmp_path / "Micro Dramas.md"
    generic = "1 WCAG mobile dashboard retention behavior."
    path.write_text(f"{REQUIREMENT}\n{generic}")
    extraction = {
        "runs": [
            {
                "criteria": [
                    {
                        "criterion_id": "edge_cases_and_states",
                        "fields": [
                            {
                                "name": name,
                                "value": generic,
                                "evidence": {"quote": generic},
                            }
                            for name in [
                                "error_states",
                                "empty_or_edge_states",
                                "transitional_or_degraded_states",
                                "supported_platforms",
                                "accessibility_approach",
                            ]
                        ],
                    }
                ]
            }
        ]
    }
    ledger = EdgeCaseCoverageLedger(items=[_item(CoverageStatus.MISSING)])
    response = assess_extraction_json(
        str(path), json.dumps(extraction), edge_case_coverage=ledger
    )
    edge = next(
        item
        for item in response.assessment.criteria
        if item.criterion_id == "edge_cases_and_states"
    )

    assert edge.verdict is Verdict.PARTIAL
    assert edge.missing == ["edge_case_coverage"]
    edge_question = next(
        gap
        for gap in response.report.gaps
        if gap.criterion_id == "edge_cases_and_states"
    )
    assert edge_question.missing_fields == ["edge_case_coverage"]
