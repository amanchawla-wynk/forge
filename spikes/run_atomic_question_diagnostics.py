"""Run deterministic rubric-0.8 question diagnostics and proxy review."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from forge.questions.diagnostics import evaluate_question_diagnostics
from forge.questions.labels import (
    QuestionReviewerSheet,
    evaluate_question_reviewer_sheets,
    make_question_reviewer_sheet,
)
from forge.questions.prepare import prepare_question_generations
from prepare_internal_atomic_evaluation import load_verified


ROOT = Path(__file__).resolve().parents[1]
FORGE_DIR = ROOT / "sampleDoc/.forge"
DIAGNOSTIC_PATH = FORGE_DIR / "atomic-question-diagnostic-report.json"
REVIEW_REPORT_PATH = FORGE_DIR / "atomic-question-review-report.json"
THRESHOLDS = {
    "consensus_coverage_min": 1.0,
    "relevant_yes_rate_min": 0.9,
    "answerable_yes_rate_min": 0.9,
    "smallest_scope_yes_rate_min": 0.8,
    "unsupported_assumption_no_rate_min": 0.95,
    "unsupported_text_max": 0,
    "duplicate_questions_max": 0,
    "deterministic_stability_required": True,
}
FRAMINGS = {"micro_dramas": "opportunity_bet"}


def review_path(index: int) -> Path:
    return FORGE_DIR / f"atomic-question-review-proxy-{index}.json"


def prepare() -> None:
    cases = load_verified()
    preparations_by_case = {
        case_id: prepare_question_generations(
            prepared.rubric,
            verified.consolidated,
            framing=FRAMINGS.get(case_id),
        )
        for case_id, _, prepared, verified in cases
    }
    preparations = [
        item for items in preparations_by_case.values() for item in items
    ]
    repeated_cases = load_verified()
    repeated = [
        item
        for case_id, _source_path, prepared, verified in repeated_cases
        for item in prepare_question_generations(
            prepared.rubric,
            verified.consolidated,
            framing=FRAMINGS.get(case_id),
        )
    ]
    group_by_plan = {
        item.target.plan_id: case_id
        for case_id, items in preparations_by_case.items()
        for item in items
    }
    report = evaluate_question_diagnostics(
        preparations,
        [],
        repeated_preparations=repeated,
        group_by_plan=group_by_plan,
        deterministic_primary=True,
    )
    mechanical_pass = (
        report.deterministic.rate == 1.0
        and report.unsupported_text_count <= THRESHOLDS["unsupported_text_max"]
        and report.duplicates.matched <= THRESHOLDS["duplicate_questions_max"]
        and report.stable is THRESHOLDS["deterministic_stability_required"]
    )
    payload = {
        "artifact_type": "forge.atomic_question_diagnostics.v1",
        "calibration_eligible": False,
        "score_effect": "none",
        "thresholds_predeclared": THRESHOLDS,
        "mechanical_gate_passed": mechanical_pass,
        "report": report.model_dump(mode="json"),
    }
    DIAGNOSTIC_PATH.write_text(json.dumps(payload, indent=2) + "\n")

    questions_by_case = {case_id: [] for case_id in preparations_by_case}
    for question in report.questions:
        questions_by_case[group_by_plan[question.plan_id]].append(
            (question.question_id, question.question)
        )
    reviewer_cases = [
        (
            case_id,
            next(source for item, source, _, _ in cases if item == case_id),
            sorted(questions),
        )
        for case_id, questions in questions_by_case.items()
        if questions
    ]
    for index in (1, 2, 3):
        sheet = make_question_reviewer_sheet(
            reviewer_id=f"atomic-question-proxy-{index}",
            cases=reviewer_cases,
        )
        review_path(index).write_text(sheet.model_dump_json(indent=2) + "\n")
    print(
        json.dumps(
            {
                "eligible_questions": report.eligible_questions,
                "mechanical_gate_passed": mechanical_pass,
                "diagnostic_path": str(DIAGNOSTIC_PATH.relative_to(ROOT)),
                "review_paths": [
                    str(review_path(index).relative_to(ROOT))
                    for index in (1, 2, 3)
                ],
                "thresholds_predeclared": THRESHOLDS,
            },
            indent=2,
        )
    )


def review() -> None:
    sheets = [
        QuestionReviewerSheet.model_validate_json(review_path(index).read_text())
        for index in (1, 2, 3)
    ]
    report = evaluate_question_reviewer_sheets(sheets)
    total = report.compared_questions
    dimensions = (
        "relevant",
        "answerable",
        "smallest_scope",
        "unsupported_assumption",
    )
    counts = {
        dimension: Counter(
            getattr(item, dimension).value
            for item in report.consensus.values()
            if getattr(item, dimension) is not None
        )
        for dimension in dimensions
    }
    consensus_values = sum(sum(values.values()) for values in counts.values())
    rates = {
        "consensus_coverage": (
            consensus_values / (total * len(dimensions)) if total else 0.0
        ),
        "relevant_yes_rate": counts["relevant"]["yes"] / total if total else 0.0,
        "answerable_yes_rate": counts["answerable"]["yes"] / total if total else 0.0,
        "smallest_scope_yes_rate": (
            counts["smallest_scope"]["yes"] / total if total else 0.0
        ),
        "unsupported_assumption_no_rate": (
            counts["unsupported_assumption"]["no"] / total if total else 0.0
        ),
    }
    checks = {
        "consensus_coverage": rates["consensus_coverage"]
        >= THRESHOLDS["consensus_coverage_min"],
        "relevant": rates["relevant_yes_rate"]
        >= THRESHOLDS["relevant_yes_rate_min"],
        "answerable": rates["answerable_yes_rate"]
        >= THRESHOLDS["answerable_yes_rate_min"],
        "smallest_scope": rates["smallest_scope_yes_rate"]
        >= THRESHOLDS["smallest_scope_yes_rate_min"],
        "unsupported_assumption": rates["unsupported_assumption_no_rate"]
        >= THRESHOLDS["unsupported_assumption_no_rate_min"],
    }
    diagnostic = json.loads(DIAGNOSTIC_PATH.read_text())
    payload = {
        "artifact_type": "forge.atomic_question_review_gate.v1",
        "label_authority": "synthetic_ai_proxy",
        "calibration_eligible": False,
        "score_effect": "none",
        "thresholds_predeclared": THRESHOLDS,
        "mechanical_gate_passed": diagnostic["mechanical_gate_passed"],
        "proxy_checks": checks,
        "rates": {key: round(value, 4) for key, value in rates.items()},
        "gate_passed": diagnostic["mechanical_gate_passed"] and all(checks.values()),
        "consensus_counts": {
            key: dict(sorted(value.items())) for key, value in counts.items()
        },
        "review": report.model_dump(mode="json"),
    }
    REVIEW_REPORT_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "review"))
    args = parser.parse_args()
    prepare() if args.action == "prepare" else review()


if __name__ == "__main__":
    main()
