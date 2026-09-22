from __future__ import annotations

from pathlib import Path

import pytest

from forge.calibration import (
    CalibrationCase,
    CalibrationSuite,
    HumanLabel,
    evaluate_calibration,
    make_label_template,
)
from forge.rubric.loader import load_rubric
from forge.service import assess_extraction_json

CORPUS = Path(__file__).parent.parent / "fixtures" / "corpus"


def _assessment(case: str):
    return assess_extraction_json(
        str(CORPUS / f"{case}.md"),
        (CORPUS / f"{case}.extraction.json").read_text(),
    ).assessment


def _label(assessment, reviewer: str, band: str, **overrides):
    criteria = {
        result.criterion_id: result.verdict for result in assessment.criteria
    }
    criteria.update(overrides)
    return HumanLabel(
        reviewer_id=reviewer,
        band=band,
        criteria=criteria,
    )


def test_label_template_is_exhaustive_and_contains_no_document_text():
    assessment = _assessment("complete")

    suite = make_label_template(
        assessment,
        case_id="prd-001",
        reviewer_id="reviewer-a",
        source_ref="opaque-document-id",
    )

    case = suite.cases[0]
    assert case.source_ref == "opaque-document-id"
    assert case.labels[0].band is None
    assert set(case.labels[0].criteria) == {
        result.criterion_id for result in assessment.criteria
    }
    assert set(case.labels[0].criteria.values()) == {None}
    assert "Small-business sellers" not in suite.model_dump_json()


def test_calibration_reports_false_ready_and_false_not_ready():
    rubric = load_rubric("prd")
    complete = _assessment("complete")
    gaming = _assessment("gaming")
    suite = CalibrationSuite(
        rubric_id=rubric.id,
        rubric_version=rubric.version,
        cases=[
            CalibrationCase(
                case_id="false-ready",
                source_kind="internal",
                prediction=complete,
                labels=[
                    _label(
                        complete,
                        "reviewer-a",
                        "needs_work",
                        problem_statement="absent",
                    ),
                    _label(
                        complete,
                        "reviewer-b",
                        "needs_work",
                        problem_statement="absent",
                    ),
                ],
            ),
            CalibrationCase(
                case_id="false-not-ready",
                source_kind="synthetic",
                prediction=gaming,
                labels=[
                    _label(gaming, "reviewer-a", "ready_with_gaps"),
                    _label(gaming, "reviewer-b", "ready_with_gaps"),
                ],
            ),
        ],
    )

    report = evaluate_calibration(rubric, suite)

    assert report.band_agreement.rate == 0.0
    assert report.mean_band_distance == 1.5
    assert report.false_ready.rate == 0.5
    assert report.false_not_ready.rate == 0.5
    assert report.inter_reviewer_band_agreement.rate == 1.0
    assert report.criteria["problem_statement"].model_human.rate == 0.5
    assert report.source_counts == {"internal": 1, "synthetic": 1}


def test_tied_human_labels_are_contested_not_resolved():
    rubric = load_rubric("prd")
    assessment = _assessment("complete")
    suite = CalibrationSuite(
        rubric_id=rubric.id,
        rubric_version=rubric.version,
        cases=[
            CalibrationCase(
                case_id="contested",
                source_kind="public",
                prediction=assessment,
                labels=[
                    _label(assessment, "reviewer-a", "ready_to_build"),
                    _label(
                        assessment,
                        "reviewer-b",
                        "needs_work",
                        acceptance_criteria="absent",
                    ),
                ],
            )
        ],
    )

    report = evaluate_calibration(rubric, suite)

    assert report.band_agreement.compared == 0
    assert report.contested_band_cases == 1
    assert report.inter_reviewer_band_agreement.rate == 0.0
    assert report.criteria["acceptance_criteria"].contested_cases == 1
    assert any("No internal PRDs" in warning for warning in report.warnings)


def test_calibration_rejects_non_exhaustive_labels():
    rubric = load_rubric("prd")
    assessment = _assessment("complete")
    suite = CalibrationSuite(
        rubric_id=rubric.id,
        rubric_version=rubric.version,
        cases=[
            CalibrationCase(
                case_id="incomplete",
                source_kind="internal",
                prediction=assessment,
                labels=[
                    HumanLabel(
                        reviewer_id="reviewer-a",
                        band="ready_to_build",
                        criteria={"problem_statement": "present"},
                    )
                ],
            )
        ],
    )

    with pytest.raises(ValueError, match="label criteria do not match"):
        evaluate_calibration(rubric, suite)
