from __future__ import annotations

import json
from pathlib import Path

from forge.proxy_diagnostics import _null_extraction_json, run_proxy_diagnostics
from forge.rubric.loader import load_rubric

ROOT = Path(__file__).parents[1]
ARTIFACT = (
    ROOT / "fixtures" / "proxy" / "microdrama-recommendations.proxy-panel.v1.json"
)


def test_proxy_diagnostics_null_extraction_matches_the_current_rubric():
    rubric = load_rubric("prd")
    extraction = json.loads(_null_extraction_json())

    assert [item["criterion_id"] for item in extraction["criteria"]] == [
        criterion.id for criterion in rubric.criteria
    ]
    for item, criterion in zip(extraction["criteria"], rubric.criteria, strict=True):
        assert [field["name"] for field in item["fields"]] == [
            field.name for field in criterion.fields
        ]
        assert all(field["value"] is None for field in item["fields"])
        assert all(field["evidence"] is None for field in item["fields"])


def test_proxy_diagnostics_measure_recall_without_claiming_calibration():
    report = run_proxy_diagnostics(ARTIFACT, workspace_root=ROOT)

    assert report.calibration_eligible is False
    assert report.label_authority == "synthetic_ai_proxy"
    assert any("transfer diagnostic" in note for note in report.notes)

    # Recall is currently low and must be reported honestly rather than hidden.
    assert report.finding_recall.total == 19
    assert report.finding_recall.matched >= 3
    assert report.blocker_finding_recall.total == 9
    assert report.candidate_count > 0

    # The expensive failure is accusing the author of a defect the panel
    # explicitly rejected, so this must stay empty.
    assert report.hard_negative_violations == []


def test_proxy_diagnostics_cover_the_deterministic_contract_findings():
    report = run_proxy_diagnostics(ARTIFACT, workspace_root=ROOT)
    matched = {
        outcome.label_id
        for outcome in report.outcomes
        if outcome.finding_matched
    }

    # The two contract defects D-049 targeted, plus the skip-threshold conflict.
    assert {"PXY-MD-003", "PXY-MD-004", "PXY-MD-011"} <= matched
