"""Prediction-free synthetic proxy labels for shadow questions."""

from __future__ import annotations

from collections import Counter
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuestionReviewChoice(str, Enum):
    YES = "yes"
    NO = "no"
    UNCLEAR = "unclear"


class ReviewerQuestion(StrictModel):
    question_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    relevant: QuestionReviewChoice | None = None
    answerable: QuestionReviewChoice | None = None
    smallest_scope: QuestionReviewChoice | None = None
    unsupported_assumption: QuestionReviewChoice | None = None
    rationale: str | None = None


class QuestionReviewerCase(StrictModel):
    case_id: str
    source_ref: str
    questions: list[ReviewerQuestion] = Field(min_length=1)


class QuestionReviewerSheet(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    label_authority: Literal["synthetic_ai_proxy"] = "synthetic_ai_proxy"
    calibration_eligible: Literal[False] = False
    reviewer_id: str = Field(min_length=1)
    instructions: list[str]
    cases: list[QuestionReviewerCase] = Field(min_length=1)


class QuestionReviewConsensus(StrictModel):
    relevant: QuestionReviewChoice | None = None
    answerable: QuestionReviewChoice | None = None
    smallest_scope: QuestionReviewChoice | None = None
    unsupported_assumption: QuestionReviewChoice | None = None


class QuestionReviewerReport(StrictModel):
    label_authority: Literal["synthetic_ai_proxy"] = "synthetic_ai_proxy"
    calibration_eligible: Literal[False] = False
    score_effect: Literal["none"] = "none"
    reviewer_count: int
    compared_questions: int
    unanimous_questions: int
    consensus: dict[str, QuestionReviewConsensus]
    contested: list[str]
    warnings: list[str]


def make_question_reviewer_sheet(
    *,
    reviewer_id: str,
    cases: list[tuple[str, str, list[tuple[str, str]]]],
) -> QuestionReviewerSheet:
    if not cases:
        raise ValueError("question reviewer sheet requires at least one case")
    return QuestionReviewerSheet(
        reviewer_id=reviewer_id,
        instructions=[
            "This is a synthetic AI proxy review and cannot establish calibration or human agreement.",
            "Read the complete source without viewing Forge targets, evidence selections, generation mode, or other reviewer sheets.",
            "Judge whether each question addresses a real unresolved source issue and can be answered by the PRD owner.",
            "Mark smallest_scope yes only when one decision can resolve the question without combining unrelated gaps.",
            "Mark unsupported_assumption yes when the question states or presupposes a fact the source does not support.",
            "Use unclear rather than guessing, and provide a concise rationale.",
        ],
        cases=[
            QuestionReviewerCase(
                case_id=case_id,
                source_ref=source_ref,
                questions=[
                    ReviewerQuestion(question_id=question_id, question=question)
                    for question_id, question in questions
                ],
            )
            for case_id, source_ref, questions in cases
        ],
    )


def _shape(sheet: QuestionReviewerSheet) -> dict[str, list[str]]:
    return {
        case.case_id: [item.question_id for item in case.questions]
        for case in sheet.cases
    }


def _majority(values: list[QuestionReviewChoice]) -> QuestionReviewChoice | None:
    selected, votes = Counter(values).most_common(1)[0]
    return selected if votes > len(values) / 2 else None


def evaluate_question_reviewer_sheets(
    sheets: list[QuestionReviewerSheet],
) -> QuestionReviewerReport:
    if len(sheets) < 2:
        raise ValueError("at least two question reviewer sheets are required")
    if len({sheet.reviewer_id for sheet in sheets}) != len(sheets):
        raise ValueError("question reviewer ids must be unique")
    expected = _shape(sheets[0])
    if any(_shape(sheet) != expected for sheet in sheets[1:]):
        raise ValueError("question reviewer sheets contain different cases or questions")

    by_key: dict[str, list[ReviewerQuestion]] = {}
    for sheet in sheets:
        for case in sheet.cases:
            for question in case.questions:
                by_key.setdefault(f"{case.case_id}:{question.question_id}", []).append(
                    question
                )

    consensus: dict[str, QuestionReviewConsensus] = {}
    contested: list[str] = []
    compared = unanimous = 0
    fields = ("relevant", "answerable", "smallest_scope", "unsupported_assumption")
    for key, reviews in sorted(by_key.items()):
        if len(reviews) < 2 or any(
            getattr(review, field) is None for review in reviews for field in fields
        ):
            continue
        compared += 1
        choices = {
            field: [getattr(review, field) for review in reviews]
            for field in fields
        }
        if all(len(set(values)) == 1 for values in choices.values()):
            unanimous += 1
        else:
            contested.append(key)
        consensus[key] = QuestionReviewConsensus(
            **{field: _majority(values) for field, values in choices.items()}
        )
    warnings = []
    if compared == 0:
        warnings.append("No question has complete labels from at least two reviewers.")
    return QuestionReviewerReport(
        reviewer_count=len(sheets),
        compared_questions=compared,
        unanimous_questions=unanimous,
        consensus=consensus,
        contested=contested,
        warnings=warnings,
    )
