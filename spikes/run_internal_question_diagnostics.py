"""Prepare, evaluate, and proxy-review internal Phase 3 shadow questions."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from forge.evaluate.batch import (
    CriterionEvaluationBatch,
    CriterionEvaluationFragment,
    CriterionEvaluationRun,
    verify_evaluation_batch,
)
from forge.questions.apply import apply_question_generation
from forge.questions.diagnostics import (
    QuestionCompletion,
    evaluate_question_diagnostics,
)
from forge.questions.labels import (
    QuestionReviewerSheet,
    evaluate_question_reviewer_sheets,
    make_question_reviewer_sheet,
)
from forge.questions.models import PreparedQuestionGeneration, ShadowQuestion
from forge.questions.prepare import prepare_question_generations
from forge.service import prepare_assessment


ROOT = Path(__file__).resolve().parents[1]
FORGE_DIR = ROOT / "sampleDoc/.forge"
PROMPTS_PATH = FORGE_DIR / "question-generation-prompts.json"


def _native_cases() -> list[tuple[str, str, list[PreparedQuestionGeneration]]]:
    payloads = [
        json.loads((FORGE_DIR / f"evaluation-shadow-v2-run{index}.json").read_text())
        for index in (1, 2, 3)
    ]
    cases_by_source = [
        {
            metadata["source_path"]: (case_id, metadata)
            for case_id, metadata in payload["cases"].items()
        }
        for payload in payloads
    ]
    source_paths = set(cases_by_source[0])
    if any(set(items) != source_paths for items in cases_by_source[1:]):
        raise ValueError("internal shadow runs contain different sources")

    result = []
    for source_path, (case_id, metadata) in sorted(cases_by_source[0].items()):
        prepared = prepare_assessment(str(ROOT / source_path))
        runs = [
            CriterionEvaluationRun(
                run_index=payload["run_index"],
                fragments=[
                    CriterionEvaluationFragment(
                        batch_id=by_source[source_path][1]["batch_id"],
                        plan_fingerprint=by_source[source_path][1]["plan_fingerprint"],
                        criteria=[
                            item["submission"]
                            for item in by_source[source_path][1]["items"]
                        ],
                    )
                ],
            )
            for payload, by_source in zip(payloads, cases_by_source, strict=True)
        ]
        verified = verify_evaluation_batch(
            prepared, CriterionEvaluationBatch(runs=runs)
        )
        questions = prepare_question_generations(
            prepared.rubric, verified.consolidated
        )
        result.append((case_id, source_path, questions))
    return result


def _completion_path(run_index: int) -> Path:
    return FORGE_DIR / f"question-generation-run{run_index}.json"


def _review_path(reviewer_index: int) -> Path:
    return FORGE_DIR / f"question-review-ai-proxy-{reviewer_index}.json"


def prepare_artifacts() -> None:
    cases = _native_cases()
    prompt_payload = {
        "schema_version": "1.0",
        "artifact_type": "forge.question_generation_prompts.v1",
        "calibration_eligible": False,
        "score_effect": "none",
        "cases": [
            {
                "case_id": case_id,
                "source_path": source_path,
                "plans": [item.model_dump(mode="json") for item in questions],
            }
            for case_id, source_path, questions in cases
        ],
    }
    PROMPTS_PATH.write_text(json.dumps(prompt_payload, indent=2) + "\n")
    for run_index in (1, 2, 3):
        payload = {
            "schema_version": "1.0",
            "artifact_type": "forge.question_generation_completions.v1",
            "calibration_eligible": False,
            "score_effect": "none",
            "run_index": run_index,
            "instructions": [
                "Complete each bounded prompt independently.",
                "Write only the model JSON object into completion; do not alter any other field.",
                "Do not read another completion run, reviewer sheet, Forge report, or live question output.",
            ],
            "completions": [
                {
                    "case_id": case_id,
                    "plan_id": item.target.plan_id,
                    "completion": None,
                }
                for case_id, _, questions in cases
                for item in questions
            ],
        }
        _completion_path(run_index).write_text(json.dumps(payload, indent=2) + "\n")
    print(
        json.dumps(
            {
                "case_count": len(cases),
                "eligible_questions": sum(len(items) for _, _, items in cases),
                "prompts_path": str(PROMPTS_PATH.relative_to(ROOT)),
                "completion_paths": [
                    str(_completion_path(index).relative_to(ROOT))
                    for index in (1, 2, 3)
                ],
            },
            indent=2,
        )
    )


def _load_completion_run(
    run_index: int,
) -> tuple[list[QuestionCompletion], dict[str, str]]:
    payload = json.loads(_completion_path(run_index).read_text())
    if payload.get("run_index") != run_index:
        raise ValueError(f"completion run {run_index} has wrong run_index")
    completions = []
    cases = {}
    for item in payload["completions"]:
        if not isinstance(item.get("completion"), str):
            raise ValueError(
                f"completion run {run_index} is incomplete for {item['plan_id']}"
            )
        completions.append(
            QuestionCompletion(
                plan_id=item["plan_id"], completion=item["completion"]
            )
        )
        cases[item["plan_id"]] = item["case_id"]
    return completions, cases


def _normalize(question: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", question.casefold()))


def evaluate_artifacts() -> None:
    cases = _native_cases()
    preparations = [item for _, _, items in cases for item in items]
    repeated = [item for _, _, items in _native_cases() for item in items]
    group_by_plan = {
        item.target.plan_id: case_id
        for case_id, _, items in cases
        for item in items
    }
    run_reports = []
    rendered_by_plan: dict[str, list[ShadowQuestion]] = {}
    case_by_plan: dict[str, str] = {}
    source_by_case = {case_id: source for case_id, source, _ in cases}
    for run_index in (1, 2, 3):
        completions, run_cases = _load_completion_run(run_index)
        case_by_plan.update(run_cases)
        report = evaluate_question_diagnostics(
            preparations,
            completions,
            repeated_preparations=repeated,
            group_by_plan=group_by_plan,
        )
        run_reports.append(report)
        for question in report.questions:
            rendered_by_plan.setdefault(question.plan_id, []).append(question)

    stable = sum(
        len({_normalize(item.question) for item in questions}) == 1
        for questions in rendered_by_plan.values()
    )
    unique_questions: dict[str, tuple[str, str]] = {}
    for questions in rendered_by_plan.values():
        for question in questions:
            unique_questions.setdefault(
                question.question_id,
                (case_by_plan[question.plan_id], question.question),
            )
    reviewer_cases = []
    for case_id in sorted(source_by_case):
        questions = sorted(
            (
                (question_id, question)
                for question_id, (question_case, question) in unique_questions.items()
                if question_case == case_id
            ),
            key=lambda item: item[0],
        )
        if questions:
            reviewer_cases.append((case_id, source_by_case[case_id], questions))
    for reviewer_index in (1, 2, 3):
        sheet = make_question_reviewer_sheet(
            reviewer_id=f"question-ai-proxy-{reviewer_index}",
            cases=reviewer_cases,
        )
        _review_path(reviewer_index).write_text(sheet.model_dump_json(indent=2) + "\n")

    print(
        json.dumps(
            {
                "artifact_type": "forge.internal_question_diagnostics.v1",
                "calibration_eligible": False,
                "score_effect": "none",
                "eligible_questions": len(preparations),
                "run_reports": [item.model_dump(mode="json") for item in run_reports],
                "generation_stability": {
                    "matched": stable,
                    "total": len(rendered_by_plan),
                    "rate": round(stable / len(rendered_by_plan), 4)
                    if rendered_by_plan
                    else None,
                },
                "unique_rendered_questions": len(unique_questions),
                "reviewer_paths": [
                    str(_review_path(index).relative_to(ROOT))
                    for index in (1, 2, 3)
                ],
            },
            indent=2,
        )
    )


def review_artifacts() -> None:
    sheets = [
        QuestionReviewerSheet.model_validate_json(_review_path(index).read_text())
        for index in (1, 2, 3)
    ]
    report = evaluate_question_reviewer_sheets(sheets)
    dimensions = (
        "relevant",
        "answerable",
        "smallest_scope",
        "unsupported_assumption",
    )
    counts = {
        dimension: dict(
            Counter(
                getattr(item, dimension).value
                for item in report.consensus.values()
                if getattr(item, dimension) is not None
            )
        )
        for dimension in dimensions
    }
    payload = report.model_dump(mode="json")
    payload["consensus_counts"] = counts
    print(json.dumps(payload, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "evaluate", "review"))
    args = parser.parse_args()
    if args.action == "prepare":
        prepare_artifacts()
    elif args.action == "evaluate":
        evaluate_artifacts()
    else:
        review_artifacts()


if __name__ == "__main__":
    main()
