from __future__ import annotations

from forge.evaluate.labels import (
    AssertionReviewStatus,
    compare_proxy_consensus,
    evaluate_reviewer_sheets,
    make_reviewer_sheet,
)
from forge.rubric.loader import load_rubric


def test_reviewer_sheet_is_blinded_and_contains_every_assertion():
    rubric = load_rubric("prd")

    sheet = make_reviewer_sheet(
        rubric,
        reviewer_id="reviewer-a",
        cases=[("micro-dramas", "sampleDoc/Micro Dramas.docx")],
    )

    assert sheet.rubric_version == rubric.version
    assert sheet.label_authority == "synthetic_ai_proxy"
    assert sheet.calibration_eligible is False
    assert len(sheet.cases[0].criteria) == len(rubric.criteria)
    assert all(
        assertion.status is None
        for criterion in sheet.cases[0].criteria
        for assertion in criterion.assertions
    )
    def keys(value):
        if isinstance(value, dict):
            return set(value) | {
                nested for item in value.values() for nested in keys(item)
            }
        if isinstance(value, list):
            return {nested for item in value for nested in keys(item)}
        return set()

    payload_keys = keys(sheet.model_dump(mode="json"))
    assert payload_keys.isdisjoint(
        {"prediction", "native_status", "legacy_status", "weight", "gate"}
    )


def test_reviewer_disagreement_is_contested_not_resolved():
    rubric = load_rubric("prd")
    cases = [("micro-dramas", "sampleDoc/Micro Dramas.docx")]
    first = make_reviewer_sheet(rubric, reviewer_id="a", cases=cases)
    second = make_reviewer_sheet(rubric, reviewer_id="b", cases=cases)
    first_assertion = first.cases[0].criteria[0].assertions[0]
    second_assertion = second.cases[0].criteria[0].assertions[0]
    first_assertion.status = AssertionReviewStatus.SUPPORTED
    second_assertion.status = AssertionReviewStatus.GAP

    report = evaluate_reviewer_sheets([first, second])

    assert report.compared == 1
    assert report.matches == 0
    assert report.agreement_rate == 0.0
    assert report.contested == [
        f"micro-dramas:{first.cases[0].criteria[0].criterion_id}:{first_assertion.assertion_id}"
    ]
    assert report.consensus == {}


def test_three_proxy_reviewers_use_strict_majority_without_claiming_calibration():
    rubric = load_rubric("prd")
    cases = [("micro-dramas", "sampleDoc/Micro Dramas.docx")]
    sheets = [
        make_reviewer_sheet(rubric, reviewer_id=f"proxy-{index}", cases=cases)
        for index in range(1, 4)
    ]
    statuses = [
        AssertionReviewStatus.SUPPORTED,
        AssertionReviewStatus.SUPPORTED,
        AssertionReviewStatus.AMBIGUOUS,
    ]
    for sheet, status in zip(sheets, statuses, strict=True):
        sheet.cases[0].criteria[0].assertions[0].status = status

    report = evaluate_reviewer_sheets(sheets)
    key = "micro-dramas:problem_statement:problem"

    assert report.label_authority == "synthetic_ai_proxy"
    assert report.calibration_eligible is False
    assert report.consensus[key] is AssertionReviewStatus.SUPPORTED
    assert report.contested == [key]

    comparison = compare_proxy_consensus(
        {
            key: "supported",
            "micro-dramas:problem_statement:affected_users": "unclear",
        },
        report.model_copy(
            update={
                "consensus": {
                    **report.consensus,
                    "micro-dramas:problem_statement:affected_users": (
                        AssertionReviewStatus.GAP
                    ),
                }
            }
        ),
    )
    assert comparison.calibration_eligible is False
    assert comparison.paired_assertions == 2
    assert comparison.exact_matches == 1
    assert comparison.agreement_rate == 0.5
    assert comparison.matrix == {
        "supported": {"supported": 1},
        "unclear": {"gap": 1},
    }
