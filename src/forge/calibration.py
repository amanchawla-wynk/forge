"""Offline comparison of Forge assessments with human reviewer labels."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from forge.rubric.loader import load_rubric
from forge.rubric.models import Rubric, Verdict
from forge.score.engine import Assessment


class HumanLabel(BaseModel):
    reviewer_id: str = Field(min_length=1)
    band: str | None = None
    criteria: dict[str, Verdict | None]
    rationale: str | None = None


class CalibrationCase(BaseModel):
    case_id: str = Field(min_length=1)
    source_kind: Literal["internal", "public", "synthetic"]
    source_ref: str | None = None
    prediction: Assessment
    labels: list[HumanLabel] = Field(default_factory=list)
    study_split: Literal["development", "holdout"] = "development"


class CalibrationSuite(BaseModel):
    rubric_id: str
    rubric_version: str
    cases: list[CalibrationCase] = Field(min_length=1)


class ReviewerCriterionLabel(BaseModel):
    criterion_id: str
    criterion_name: str
    standard: str
    required_fields: dict[str, str]
    verdict: Verdict | None = None
    rationale: str | None = None


class ReviewerBandDefinition(BaseModel):
    id: str
    label: str
    description: str


class ReviewerCaseLabel(BaseModel):
    case_id: str
    source_ref: str | None = None
    band: str | None = None
    criteria: list[ReviewerCriterionLabel]
    rationale: str | None = None


class ReviewerLabelSheet(BaseModel):
    rubric_id: str
    rubric_version: str
    reviewer_id: str = Field(min_length=1)
    bands: list[ReviewerBandDefinition]
    cases: list[ReviewerCaseLabel] = Field(min_length=1)


class Agreement(BaseModel):
    matches: int
    compared: int
    rate: float | None


class ErrorRate(BaseModel):
    count: int
    compared: int
    rate: float | None


class CriterionCalibration(BaseModel):
    model_human: Agreement
    inter_reviewer: Agreement
    contested_cases: int


class CalibrationReport(BaseModel):
    rubric_id: str
    rubric_version: str
    case_count: int
    calibration_case_count: int
    label_count: int
    source_counts: dict[str, int]
    split_counts: dict[str, int]
    band_agreement: Agreement
    mean_band_distance: float | None
    band_confusion: dict[str, dict[str, int]]
    false_ready: ErrorRate
    false_not_ready: ErrorRate
    inter_reviewer_band_agreement: Agreement
    contested_band_cases: int
    criteria: dict[str, CriterionCalibration]
    warnings: list[str]


class ValidationThresholds(BaseModel):
    minimum_resolved_cases: int = Field(default=20, ge=1)
    maximum_false_ready_rate: float = Field(default=0.1, ge=0, le=1)
    minimum_band_agreement: float = Field(default=0.7, ge=0, le=1)
    maximum_mean_band_distance: float = Field(default=0.5, ge=0)
    minimum_inter_reviewer_agreement: float = Field(default=0.7, ge=0, le=1)


class ValidationDecision(BaseModel):
    passed: bool
    checks: dict[str, bool]
    blockers: list[str]


def make_label_template(
    assessment: Assessment,
    rubric: Rubric,
    *,
    case_id: str,
    reviewer_id: str,
    source_ref: str | None = None,
) -> ReviewerLabelSheet:
    """Create a blinded label sheet without predictions or document text."""
    if (assessment.rubric_id, assessment.rubric_version) != (
        rubric.id,
        rubric.version,
    ):
        raise ValueError("assessment does not match the label rubric version")
    return ReviewerLabelSheet(
        rubric_id=assessment.rubric_id,
        rubric_version=assessment.rubric_version,
        reviewer_id=reviewer_id,
        bands=[
            ReviewerBandDefinition(
                id=band.id,
                label=band.label,
                description=band.description.strip(),
            )
            for band in rubric.bands_descending()
        ],
        cases=[
            ReviewerCaseLabel(
                case_id=case_id,
                source_ref=source_ref,
                criteria=[
                    ReviewerCriterionLabel(
                        criterion_id=criterion.id,
                        criterion_name=criterion.name,
                        standard=criterion.rationale.strip(),
                        required_fields={
                            field.name: field.description.strip()
                            for field in criterion.required_fields
                        },
                    )
                    for criterion in rubric.criteria
                ],
            )
        ],
    )


def merge_reviewer_labels(
    predictions: CalibrationSuite,
    sheets: list[ReviewerLabelSheet],
) -> CalibrationSuite:
    """Attach completed blinded sheets to a prediction bundle by case id."""
    if not sheets:
        raise ValueError("at least one reviewer label sheet is required")
    expected_cases = {case.case_id for case in predictions.cases}
    reviewers = [sheet.reviewer_id for sheet in sheets]
    if len(reviewers) != len(set(reviewers)):
        raise ValueError("reviewer label sheets contain duplicate reviewer ids")

    labels_by_case: dict[str, list[HumanLabel]] = {
        case_id: [] for case_id in expected_cases
    }
    for sheet in sheets:
        if (sheet.rubric_id, sheet.rubric_version) != (
            predictions.rubric_id,
            predictions.rubric_version,
        ):
            raise ValueError("reviewer label sheet uses a different rubric version")
        sheet_cases = {case.case_id for case in sheet.cases}
        if sheet_cases != expected_cases:
            raise ValueError("reviewer label sheet cases do not match predictions")
        for case in sheet.cases:
            labels_by_case[case.case_id].append(
                HumanLabel(
                    reviewer_id=sheet.reviewer_id,
                    band=case.band,
                    criteria={
                        criterion.criterion_id: criterion.verdict
                        for criterion in case.criteria
                    },
                    rationale=case.rationale,
                )
            )

    merged = predictions.model_copy(deep=True)
    for case in merged.cases:
        case.labels = labels_by_case[case.case_id]
    return merged


def evaluate_calibration(
    rubric: Rubric, suite: CalibrationSuite
) -> CalibrationReport:
    """Compare deterministic predictions with reviewer consensus.

    Tied reviewer votes have no consensus and are reported as contested rather
    than being resolved in Forge's favour.
    """
    _validate_suite(rubric, suite)
    band_order = [
        band.id for band in sorted(rubric.bands, key=lambda band: band.min_score)
    ]
    ready_index = band_order.index("ready_with_gaps")

    band_matches = band_compared = 0
    band_distance = 0
    contested_bands = 0
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    false_ready = false_not_ready = 0
    human_ready_count = human_not_ready_count = 0
    band_pairs_match = band_pairs_compared = 0

    criterion_matches = Counter[str]()
    criterion_compared = Counter[str]()
    criterion_pair_matches = Counter[str]()
    criterion_pair_compared = Counter[str]()
    criterion_contested = Counter[str]()

    source_counts = Counter(case.source_kind for case in suite.cases)
    split_counts = Counter(case.study_split for case in suite.cases)
    calibration_cases = [
        case for case in suite.cases if case.source_kind == "internal"
    ]

    for case in calibration_cases:
        predicted = {
            result.criterion_id: result.verdict
            for result in case.prediction.criteria
        }
        human_band = _consensus(
            [label.band for label in case.labels if label.band is not None]
        )
        if human_band is None:
            if len({label.band for label in case.labels if label.band}) > 1:
                contested_bands += 1
        else:
            band_compared += 1
            band_matches += case.prediction.band == human_band
            band_distance += abs(
                band_order.index(case.prediction.band) - band_order.index(human_band)
            )
            confusion[human_band][case.prediction.band] += 1
            model_ready = band_order.index(case.prediction.band) >= ready_index
            human_ready = band_order.index(human_band) >= ready_index
            human_ready_count += human_ready
            human_not_ready_count += not human_ready
            false_ready += model_ready and not human_ready
            false_not_ready += not model_ready and human_ready

        for left, right in combinations(case.labels, 2):
            if left.band is not None and right.band is not None:
                band_pairs_compared += 1
                band_pairs_match += left.band == right.band

        for criterion in rubric.criteria:
            values = [
                label.criteria[criterion.id]
                for label in case.labels
                if label.criteria[criterion.id] is not None
            ]
            human_verdict = _consensus(values)
            if human_verdict is None:
                if len(set(values)) > 1:
                    criterion_contested[criterion.id] += 1
            else:
                criterion_compared[criterion.id] += 1
                criterion_matches[criterion.id] += (
                    predicted[criterion.id] == human_verdict
                )

            for left, right in combinations(case.labels, 2):
                left_verdict = left.criteria[criterion.id]
                right_verdict = right.criteria[criterion.id]
                if left_verdict is not None and right_verdict is not None:
                    criterion_pair_compared[criterion.id] += 1
                    criterion_pair_matches[criterion.id] += (
                        left_verdict == right_verdict
                    )

    warnings: list[str] = []
    if source_counts["internal"] == 0:
        warnings.append(
            "No internal PRDs are labelled; this suite cannot calibrate a company rubric."
        )
    if band_compared < 20:
        warnings.append(
            "Fewer than 20 cases have a resolved human band; rates are unstable."
        )
    if band_pairs_compared == 0:
        warnings.append(
            "No case has two completed band labels; inter-reviewer agreement is unavailable."
        )
    if split_counts["holdout"] == 0:
        warnings.append(
            "No holdout cases are declared; results may describe rubric tuning data."
        )
    excluded = len(suite.cases) - len(calibration_cases)
    if excluded:
        warnings.append(
            f"Excluded {excluded} public or synthetic case(s) from calibration "
            "metrics; use them only for robustness diagnostics."
        )

    return CalibrationReport(
        rubric_id=rubric.id,
        rubric_version=rubric.version,
        case_count=len(suite.cases),
        calibration_case_count=len(calibration_cases),
        label_count=sum(len(case.labels) for case in suite.cases),
        source_counts=dict(source_counts),
        split_counts=dict(split_counts),
        band_agreement=_agreement(band_matches, band_compared),
        mean_band_distance=(
            round(band_distance / band_compared, 4) if band_compared else None
        ),
        band_confusion={
            human: dict(predictions) for human, predictions in confusion.items()
        },
        false_ready=_error_rate(false_ready, human_not_ready_count),
        false_not_ready=_error_rate(false_not_ready, human_ready_count),
        inter_reviewer_band_agreement=_agreement(
            band_pairs_match, band_pairs_compared
        ),
        contested_band_cases=contested_bands,
        criteria={
            criterion.id: CriterionCalibration(
                model_human=_agreement(
                    criterion_matches[criterion.id],
                    criterion_compared[criterion.id],
                ),
                inter_reviewer=_agreement(
                    criterion_pair_matches[criterion.id],
                    criterion_pair_compared[criterion.id],
                ),
                contested_cases=criterion_contested[criterion.id],
            )
            for criterion in rubric.criteria
        },
        warnings=warnings,
    )


def evaluate_validation_thresholds(
    report: CalibrationReport,
    thresholds: ValidationThresholds,
) -> ValidationDecision:
    """Apply predeclared acceptance thresholds without tuning them to results."""
    checks = {
        "minimum_resolved_cases": (
            report.band_agreement.compared >= thresholds.minimum_resolved_cases
        ),
        "maximum_false_ready_rate": (
            report.false_ready.rate is not None
            and report.false_ready.rate <= thresholds.maximum_false_ready_rate
        ),
        "minimum_band_agreement": (
            report.band_agreement.rate is not None
            and report.band_agreement.rate >= thresholds.minimum_band_agreement
        ),
        "maximum_mean_band_distance": (
            report.mean_band_distance is not None
            and report.mean_band_distance <= thresholds.maximum_mean_band_distance
        ),
        "minimum_inter_reviewer_agreement": (
            report.inter_reviewer_band_agreement.rate is not None
            and report.inter_reviewer_band_agreement.rate
            >= thresholds.minimum_inter_reviewer_agreement
        ),
        "holdout_cases_present": report.split_counts.get("holdout", 0) > 0,
    }
    blockers = [name for name, passed in checks.items() if not passed]
    return ValidationDecision(passed=not blockers, checks=checks, blockers=blockers)


def holdout_only(suite: CalibrationSuite) -> CalibrationSuite:
    cases = [case for case in suite.cases if case.study_split == "holdout"]
    if not cases:
        raise ValueError("calibration suite has no holdout cases")
    return suite.model_copy(update={"cases": cases}, deep=True)


def _validate_suite(rubric: Rubric, suite: CalibrationSuite) -> None:
    if (suite.rubric_id, suite.rubric_version) != (rubric.id, rubric.version):
        raise ValueError("calibration suite does not match the active rubric version")
    expected_criteria = {criterion.id for criterion in rubric.criteria}
    known_bands = {band.id for band in rubric.bands}
    case_ids = [case.case_id for case in suite.cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("calibration suite contains duplicate case ids")

    for case in suite.cases:
        assessment = case.prediction
        if (assessment.rubric_id, assessment.rubric_version) != (
            rubric.id,
            rubric.version,
        ):
            raise ValueError(f"case {case.case_id!r} uses a different rubric version")
        predicted_criteria = {
            result.criterion_id for result in assessment.criteria
        }
        if predicted_criteria != expected_criteria:
            raise ValueError(f"case {case.case_id!r} prediction criteria do not match")
        reviewers = [label.reviewer_id for label in case.labels]
        if len(reviewers) != len(set(reviewers)):
            raise ValueError(f"case {case.case_id!r} has duplicate reviewer ids")
        for label in case.labels:
            if set(label.criteria) != expected_criteria:
                raise ValueError(
                    f"case {case.case_id!r} label criteria do not match the rubric"
                )
            if label.band is not None and label.band not in known_bands:
                raise ValueError(
                    f"case {case.case_id!r} has unknown band {label.band!r}"
                )


def _consensus(values):
    if not values:
        return None
    counts = Counter(values)
    top = max(counts.values())
    winners = [value for value, count in counts.items() if count == top]
    return winners[0] if len(winners) == 1 and top > len(values) / 2 else None


def _agreement(matches: int, compared: int) -> Agreement:
    return Agreement(
        matches=matches,
        compared=compared,
        rate=round(matches / compared, 4) if compared else None,
    )


def _error_rate(count: int, compared: int) -> ErrorRate:
    return ErrorRate(
        count=count,
        compared=compared,
        rate=round(count / compared, 4) if compared else None,
    )


def _load_assessment(path: Path) -> Assessment:
    payload = json.loads(path.read_text())
    return Assessment.model_validate(payload.get("assessment", payload))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create human-label templates and evaluate Forge calibration."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    template = subparsers.add_parser("template")
    template.add_argument("assessment", type=Path)
    template.add_argument("output", type=Path)
    template.add_argument("--case-id", required=True)
    template.add_argument("--reviewer", required=True)
    template.add_argument("--rubric", default="prd")
    template.add_argument("--source-ref")

    merge = subparsers.add_parser("merge")
    merge.add_argument("predictions", type=Path)
    merge.add_argument("output", type=Path)
    merge.add_argument("labels", type=Path, nargs="+")

    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("suite", type=Path)
    evaluate.add_argument("--rubric", default="prd")
    evaluate.add_argument("--holdout-only", action="store_true")
    evaluate.add_argument("--thresholds", type=Path)

    args = parser.parse_args()
    if args.command == "template":
        suite = make_label_template(
            _load_assessment(args.assessment),
            load_rubric(args.rubric),
            case_id=args.case_id,
            reviewer_id=args.reviewer,
            source_ref=args.source_ref,
        )
        args.output.write_text(suite.model_dump_json(indent=2) + "\n")
        return

    if args.command == "merge":
        predictions = CalibrationSuite.model_validate_json(
            args.predictions.read_text()
        )
        sheets = [
            ReviewerLabelSheet.model_validate_json(path.read_text())
            for path in args.labels
        ]
        merged = merge_reviewer_labels(predictions, sheets)
        args.output.write_text(merged.model_dump_json(indent=2) + "\n")
        return

    rubric = load_rubric(args.rubric)
    suite = CalibrationSuite.model_validate_json(args.suite.read_text())
    if args.holdout_only:
        suite = holdout_only(suite)
    report = evaluate_calibration(rubric, suite)
    if args.thresholds:
        thresholds = ValidationThresholds.model_validate_json(
            args.thresholds.read_text()
        )
        print(
            json.dumps(
                {
                    "report": report.model_dump(mode="json"),
                    "decision": evaluate_validation_thresholds(
                        report, thresholds
                    ).model_dump(mode="json"),
                },
                indent=2,
            )
        )
    else:
        print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
