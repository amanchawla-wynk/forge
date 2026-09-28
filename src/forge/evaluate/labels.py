"""Prediction-free reviewer sheets for criterion-evaluation assertions."""

from __future__ import annotations

from collections import Counter
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from forge.rubric.models import Rubric


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssertionReviewStatus(str, Enum):
    SUPPORTED = "supported"
    GAP = "gap"
    CONTRADICTORY = "contradictory"
    AMBIGUOUS = "ambiguous"
    UNCLEAR = "unclear"


class ReviewerAssertion(StrictModel):
    assertion_id: str
    description: str
    required: bool
    status: AssertionReviewStatus | None = None
    evidence_quotes: list[str] = Field(default_factory=list)
    rationale: str | None = None


class ReviewerCriterion(StrictModel):
    criterion_id: str
    name: str
    standard: str
    assertions: list[ReviewerAssertion]


class ReviewerCase(StrictModel):
    case_id: str
    source_ref: str
    criteria: list[ReviewerCriterion]


class EvaluationReviewerSheet(StrictModel):
    schema_version: str = "1.0"
    label_authority: Literal["synthetic_ai_proxy"] = "synthetic_ai_proxy"
    calibration_eligible: Literal[False] = False
    rubric_id: str
    rubric_version: str
    reviewer_id: str = Field(min_length=1)
    instructions: list[str]
    cases: list[ReviewerCase] = Field(min_length=1)


class EvaluationReviewerReport(StrictModel):
    label_authority: Literal["synthetic_ai_proxy"] = "synthetic_ai_proxy"
    calibration_eligible: Literal[False] = False
    reviewer_count: int
    compared: int
    matches: int
    agreement_rate: float | None
    contested: list[str]
    consensus: dict[str, AssertionReviewStatus]
    warnings: list[str]


class ProxyAssertionDisagreement(StrictModel):
    assertion_key: str
    native_status: str
    proxy_status: AssertionReviewStatus


class ProxyConsensusComparison(StrictModel):
    label_authority: Literal["synthetic_ai_proxy"] = "synthetic_ai_proxy"
    calibration_eligible: Literal[False] = False
    score_effect: Literal["none"] = "none"
    paired_assertions: int
    exact_matches: int
    agreement_rate: float | None
    matrix: dict[str, dict[str, int]]
    disagreements: list[ProxyAssertionDisagreement]
    note: str = (
        "Synthetic proxy alignment only; proxy consensus is not human ground truth."
    )


def make_reviewer_sheet(
    rubric: Rubric,
    *,
    reviewer_id: str,
    cases: list[tuple[str, str]],
) -> EvaluationReviewerSheet:
    if not cases:
        raise ValueError("reviewer sheet requires at least one case")
    if len({case_id for case_id, _ in cases}) != len(cases):
        raise ValueError("reviewer sheet contains duplicate case ids")
    return EvaluationReviewerSheet(
        rubric_id=rubric.id,
        rubric_version=rubric.version,
        reviewer_id=reviewer_id,
        instructions=[
            "This is a synthetic AI proxy review and cannot establish calibration or human agreement.",
            "Read the source document without viewing any Forge prediction or prior reviewer sheet.",
            "For each assertion, select supported, gap, contradictory, ambiguous, or unclear.",
            "Paste exact source quotes for supported, contradictory, or ambiguous labels.",
            "Use gap only when the document lacks the required decision after reviewing the whole source.",
            "Do not infer implementation behavior that the document does not state.",
        ],
        cases=[
            ReviewerCase(
                case_id=case_id,
                source_ref=source_ref,
                criteria=[
                    ReviewerCriterion(
                        criterion_id=criterion.id,
                        name=criterion.name,
                        standard=criterion.rationale.strip(),
                        assertions=[
                            ReviewerAssertion(
                                assertion_id=assertion.id,
                                description=assertion.description.strip(),
                                required=assertion.required,
                            )
                            for assertion in criterion.evaluation.assertions
                        ],
                    )
                    for criterion in rubric.criteria
                    if criterion.evaluation is not None
                ],
            )
            for case_id, source_ref in cases
        ],
    )


def evaluate_reviewer_sheets(
    sheets: list[EvaluationReviewerSheet],
) -> EvaluationReviewerReport:
    if len(sheets) < 2:
        raise ValueError("at least two reviewer sheets are required")
    reviewer_ids = [sheet.reviewer_id for sheet in sheets]
    if len(reviewer_ids) != len(set(reviewer_ids)):
        raise ValueError("reviewer ids must be unique")
    first = sheets[0]
    expected_shape = _shape(first)
    for sheet in sheets[1:]:
        if (sheet.rubric_id, sheet.rubric_version) != (
            first.rubric_id,
            first.rubric_version,
        ):
            raise ValueError("reviewer sheets use different rubric versions")
        if _shape(sheet) != expected_shape:
            raise ValueError("reviewer sheets contain different cases or assertions")

    labels: dict[str, list[AssertionReviewStatus]] = {}
    for sheet in sheets:
        for case in sheet.cases:
            for criterion in case.criteria:
                for assertion in criterion.assertions:
                    if assertion.status is None:
                        continue
                    key = f"{case.case_id}:{criterion.criterion_id}:{assertion.assertion_id}"
                    labels.setdefault(key, []).append(assertion.status)

    compared = matches = 0
    contested: list[str] = []
    consensus: dict[str, AssertionReviewStatus] = {}
    for key, observed in sorted(labels.items()):
        if len(observed) < 2:
            continue
        compared += 1
        counts = Counter(observed)
        if len(counts) == 1:
            matches += 1
        else:
            contested.append(key)
        selected, votes = counts.most_common(1)[0]
        if votes > len(observed) / 2:
            consensus[key] = selected

    warnings: list[str] = []
    if compared == 0:
        warnings.append("No assertion has labels from at least two reviewers.")
    return EvaluationReviewerReport(
        reviewer_count=len(sheets),
        compared=compared,
        matches=matches,
        agreement_rate=round(matches / compared, 4) if compared else None,
        contested=contested,
        consensus=consensus,
        warnings=warnings,
    )


def compare_proxy_consensus(
    native_statuses: dict[str, str],
    proxy: EvaluationReviewerReport,
) -> ProxyConsensusComparison:
    matrix: dict[str, Counter[str]] = {}
    disagreements: list[ProxyAssertionDisagreement] = []
    paired = matches = 0
    for key, proxy_status in sorted(proxy.consensus.items()):
        native_status = native_statuses.get(key)
        if native_status is None:
            continue
        paired += 1
        matches += native_status == proxy_status.value
        matrix.setdefault(native_status, Counter())[proxy_status.value] += 1
        if native_status != proxy_status.value:
            disagreements.append(
                ProxyAssertionDisagreement(
                    assertion_key=key,
                    native_status=native_status,
                    proxy_status=proxy_status,
                )
            )
    return ProxyConsensusComparison(
        paired_assertions=paired,
        exact_matches=matches,
        agreement_rate=round(matches / paired, 4) if paired else None,
        matrix={
            native: dict(sorted(values.items()))
            for native, values in sorted(matrix.items())
        },
        disagreements=disagreements,
    )


def _shape(sheet: EvaluationReviewerSheet) -> dict[str, dict[str, list[str]]]:
    return {
        case.case_id: {
            criterion.criterion_id: [
                assertion.assertion_id for assertion in criterion.assertions
            ]
            for criterion in case.criteria
        }
        for case in sheet.cases
    }
