from __future__ import annotations

import pytest

from forge.deep_review import DeepReviewFinding, DeepReviewReport, FindingEvidence
from forge.review_eval import (
    ExpectedFinding,
    GoldenCase,
    GoldenLabel,
    GoldenSuite,
    ReviewEvalThresholds,
    evaluate_review,
    evaluate_thresholds,
    holdout_only,
    make_label_template,
    merge_labels,
)


def _finding(finding_id: str, kind: str, *quotes: str) -> DeepReviewFinding:
    return DeepReviewFinding(
        finding_id=finding_id,
        kind=kind,
        title="Conflict",
        summary="Two requirements conflict.",
        evidence=[
            FindingEvidence(
                claim_id=f"claim-{index}",
                quote=quote,
                source_block_id=f"block-{index}",
            )
            for index, quote in enumerate(quotes)
        ],
        affected_consumers=["engineering"],
        implementation_consequence="The implementation is ambiguous.",
        required_decision="Choose one rule.",
        review_order=1,
        confidence="classified",
    )


def _label(
    reviewer: str, expected_id: str, *quotes: str, case_id: str = "case-1"
) -> GoldenLabel:
    return GoldenLabel(
        case_id=case_id,
        reviewer_id=reviewer,
        expected=[
            ExpectedFinding(
                expected_id=expected_id,
                kind="precedence_conflict",
                quote_fragments=list(quotes),
            )
        ],
    )


def test_evaluate_review_reports_precision_recall_and_false_positives():
    first = "Use editorial rank before engagement."
    second = "Use engagement before editorial rank."
    report = DeepReviewReport(
        summary="Two findings need review.",
        findings=[
            _finding("matched", "precedence_conflict", first, second),
            _finding(
                "false-positive",
                "scoped_contradiction",
                "The empty state uses a retry button.",
            ),
        ],
    )
    suite = GoldenSuite(
        cases=[
            GoldenCase(
                case_id="case-1",
                predicted=report,
                labels=[
                    _label("reviewer-a", "a-1", first, second),
                    _label("reviewer-b", "b-1", first, second),
                ],
            )
        ]
    )

    result = evaluate_review(suite)

    assert result.scored_case_count == 1
    assert result.precision.rate == 0.5
    assert result.recall.rate == 1.0
    assert result.blocker_recall.rate == 1.0
    assert result.false_positives_per_case == 1.0
    assert result.evidence_completeness.rate == 1.0
    assert result.human_quote_alignment.rate == 0.5
    assert result.inter_reviewer_agreement.rate == 1.0
    assert result.cases[0].false_positives == ["false-positive"]
    assert result.by_kind["precedence_conflict"]["precision"].rate == 1.0
    assert result.by_kind["precedence_conflict"]["recall"].rate == 1.0
    assert result.by_kind["scoped_contradiction"]["precision"].rate == 0.0
    assert result.by_kind["scoped_contradiction"]["recall"].rate is None


def test_contested_labels_do_not_enter_consensus_recall():
    common = "Hard skip is at most five seconds."
    contested = "Soft skip is at least twenty seconds."
    labels = [
        _label("reviewer-a", "a-common", common),
        _label("reviewer-b", "b-common", common),
        _label("reviewer-c", "c-only", contested),
    ]
    suite = GoldenSuite(
        cases=[
            GoldenCase(
                case_id="case-1",
                predicted=DeepReviewReport(
                    summary="One finding.",
                    findings=[
                        _finding("common", "precedence_conflict", common)
                    ],
                ),
                labels=labels,
            )
        ]
    )

    result = evaluate_review(suite)

    assert result.recall.total == 1
    assert result.recall.rate == 1.0
    assert result.contested_expected == 1
    assert result.inter_reviewer_agreement.rate == 0.0


def test_single_reviewer_and_non_internal_cases_are_not_headline_evidence():
    finding = _finding(
        "synthetic-finding",
        "precedence_conflict",
        "Use the first rule.",
    )
    suite = GoldenSuite(
        cases=[
            GoldenCase(
                case_id="case-1",
                source_kind="synthetic",
                predicted=DeepReviewReport(summary="Finding.", findings=[finding]),
                labels=[_label("reviewer-a", "expected", "Use the first rule.")],
            )
        ]
    )

    result = evaluate_review(suite)

    assert result.scored_case_count == 0
    assert result.precision.rate is None
    assert any("fewer than two" in warning for warning in result.warnings)
    assert any("synthetic" in warning for warning in result.warnings)


def test_thresholds_fail_closed_when_metrics_are_undefined():
    report = evaluate_review(
        GoldenSuite(
            cases=[
                GoldenCase(
                    case_id="case-1",
                    predicted=DeepReviewReport(summary="No findings."),
                )
            ]
        )
    )

    decision = evaluate_thresholds(
        report, ReviewEvalThresholds(minimum_scored_cases=1)
    )

    assert not decision.passed
    assert set(decision.blockers) == {
        "blocker_recall",
        "false_positives_per_case",
        "inter_reviewer_agreement",
        "precision",
        "scored_cases",
    }


def test_label_template_merge_and_holdout_helpers():
    sheet = make_label_template("case-1", "reviewer-a", "prd.md")
    assert sheet.case_id == "case-1"
    assert sheet.source_ref == "prd.md"
    assert "<paste" in sheet.expected[0].quote_fragments[0]

    suite = GoldenSuite(
        cases=[
            GoldenCase(
                case_id="case-1",
                study_split="holdout",
                predicted=DeepReviewReport(summary="No findings."),
            )
        ]
    )
    merged = merge_labels(suite, [sheet])
    assert merged.cases[0].labels == [sheet]
    assert holdout_only(merged) == merged

    unknown = sheet.model_copy(update={"case_id": "missing"})
    with pytest.raises(ValueError, match="unknown cases"):
        merge_labels(suite, [unknown])

    duplicate = sheet.model_copy()
    with pytest.raises(ValueError, match="duplicate reviewer ids"):
        merge_labels(merged, [duplicate])
