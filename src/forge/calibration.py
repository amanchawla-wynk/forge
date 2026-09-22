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
    labels: list[HumanLabel] = Field(min_length=1)


class CalibrationSuite(BaseModel):
    rubric_id: str
    rubric_version: str
    cases: list[CalibrationCase] = Field(min_length=1)


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
    label_count: int
    source_counts: dict[str, int]
    band_agreement: Agreement
    mean_band_distance: float | None
    band_confusion: dict[str, dict[str, int]]
    false_ready: ErrorRate
    false_not_ready: ErrorRate
    inter_reviewer_band_agreement: Agreement
    contested_band_cases: int
    criteria: dict[str, CriterionCalibration]
    warnings: list[str]


def make_label_template(
    assessment: Assessment,
    *,
    case_id: str,
    reviewer_id: str,
    source_kind: Literal["internal", "public", "synthetic"] = "internal",
    source_ref: str | None = None,
) -> CalibrationSuite:
    """Create an exhaustive blank label without retaining source document text."""
    return CalibrationSuite(
        rubric_id=assessment.rubric_id,
        rubric_version=assessment.rubric_version,
        cases=[
            CalibrationCase(
                case_id=case_id,
                source_kind=source_kind,
                source_ref=source_ref,
                prediction=assessment,
                labels=[
                    HumanLabel(
                        reviewer_id=reviewer_id,
                        criteria={
                            result.criterion_id: None
                            for result in assessment.criteria
                        },
                    )
                ],
            )
        ],
    )


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
    band_pairs_match = band_pairs_compared = 0

    criterion_matches = Counter[str]()
    criterion_compared = Counter[str]()
    criterion_pair_matches = Counter[str]()
    criterion_pair_compared = Counter[str]()
    criterion_contested = Counter[str]()

    for case in suite.cases:
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

    source_counts = Counter(case.source_kind for case in suite.cases)
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

    return CalibrationReport(
        rubric_id=rubric.id,
        rubric_version=rubric.version,
        case_count=len(suite.cases),
        label_count=sum(len(case.labels) for case in suite.cases),
        source_counts=dict(source_counts),
        band_agreement=_agreement(band_matches, band_compared),
        mean_band_distance=(
            round(band_distance / band_compared, 4) if band_compared else None
        ),
        band_confusion={
            human: dict(predictions) for human, predictions in confusion.items()
        },
        false_ready=_error_rate(false_ready, band_compared),
        false_not_ready=_error_rate(false_not_ready, band_compared),
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
    return winners[0] if len(winners) == 1 else None


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
    template.add_argument(
        "--source-kind",
        choices=("internal", "public", "synthetic"),
        default="internal",
    )
    template.add_argument("--source-ref")

    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("suite", type=Path)
    evaluate.add_argument("--rubric", default="prd")

    args = parser.parse_args()
    if args.command == "template":
        suite = make_label_template(
            _load_assessment(args.assessment),
            case_id=args.case_id,
            reviewer_id=args.reviewer,
            source_kind=args.source_kind,
            source_ref=args.source_ref,
        )
        args.output.write_text(suite.model_dump_json(indent=2) + "\n")
        return

    rubric = load_rubric(args.rubric)
    suite = CalibrationSuite.model_validate_json(args.suite.read_text())
    print(evaluate_calibration(rubric, suite).model_dump_json(indent=2))


if __name__ == "__main__":
    main()
