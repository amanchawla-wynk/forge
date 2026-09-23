from __future__ import annotations

from pathlib import Path

import pytest

from forge.calibration import (
    CalibrationCase,
    CalibrationSuite,
    HumanLabel,
    evaluate_calibration,
    make_label_template,
    merge_reviewer_labels,
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
        load_rubric("prd"),
        case_id="prd-001",
        reviewer_id="reviewer-a",
        source_ref="opaque-document-id",
    )

    case = suite.cases[0]
    assert case.source_ref == "opaque-document-id"
    assert case.band is None
    assert {criterion.criterion_id for criterion in case.criteria} == {
        result.criterion_id for result in assessment.criteria
    }
    assert {criterion.verdict for criterion in case.criteria} == {None}
    assert all(criterion.required_fields for criterion in case.criteria)
    assert suite.bands[0].id == "ready_to_build"
    assert "Small-business sellers" not in suite.model_dump_json()
    assert "prediction" not in suite.model_dump_json()


def test_blinded_reviewer_sheets_merge_after_labelling():
    rubric = load_rubric("prd")
    assessment = _assessment("complete")
    predictions = CalibrationSuite(
        rubric_id=rubric.id,
        rubric_version=rubric.version,
        cases=[
            CalibrationCase(
                case_id="prd-001",
                source_kind="internal",
                prediction=assessment,
            )
        ],
    )
    sheets = [
        make_label_template(
            assessment,
            rubric,
            case_id="prd-001",
            reviewer_id=reviewer,
        )
        for reviewer in ("reviewer-a", "reviewer-b")
    ]
    for sheet in sheets:
        sheet.cases[0].band = "ready_to_build"
        verdicts = {
            result.criterion_id: result.verdict for result in assessment.criteria
        }
        for criterion in sheet.cases[0].criteria:
            criterion.verdict = verdicts[criterion.criterion_id]

    merged = merge_reviewer_labels(predictions, sheets)

    assert [label.reviewer_id for label in merged.cases[0].labels] == [
        "reviewer-a",
        "reviewer-b",
    ]
    assert evaluate_calibration(rubric, merged).band_agreement.rate == 1.0


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
    assert report.mean_band_distance == 2.0
    assert report.false_ready.rate == 1.0
    assert report.false_not_ready.rate is None
    assert report.inter_reviewer_band_agreement.rate == 1.0
    assert report.criteria["problem_statement"].model_human.rate == 0.0
    assert report.source_counts == {"internal": 1, "synthetic": 1}
    assert report.calibration_case_count == 1
    assert any("Excluded 1" in warning for warning in report.warnings)


def test_tied_human_labels_are_contested_not_resolved():
    rubric = load_rubric("prd")
    assessment = _assessment("complete")
    suite = CalibrationSuite(
        rubric_id=rubric.id,
        rubric_version=rubric.version,
        cases=[
            CalibrationCase(
                case_id="contested",
                source_kind="internal",
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


def test_public_cases_are_diagnostics_not_calibration_truth():
    rubric = load_rubric("prd")
    assessment = _assessment("complete")
    suite = CalibrationSuite(
        rubric_id=rubric.id,
        rubric_version=rubric.version,
        cases=[
            CalibrationCase(
                case_id="public-example",
                source_kind="public",
                prediction=assessment,
                labels=[
                    _label(assessment, "reviewer-a", "ready_to_build"),
                    _label(assessment, "reviewer-b", "ready_to_build"),
                ],
            )
        ],
    )

    report = evaluate_calibration(rubric, suite)

    assert report.calibration_case_count == 0
    assert report.band_agreement.rate is None
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
