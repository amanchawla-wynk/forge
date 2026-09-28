"""Prepare and verify fresh rubric-0.8 internal atomic-evaluation runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from forge.evaluate.batch import (
    CriterionEvaluationBatch,
    CriterionEvaluationFragment,
    CriterionEvaluationRun,
    prepare_evaluation_plan,
    verify_evaluation_batch,
)
from forge.service import prepare_assessment


ROOT = Path(__file__).resolve().parents[1]
FORGE_DIR = ROOT / "sampleDoc/.forge"
PROMPTS_PATH = FORGE_DIR / "evaluation-atomic-prompts.json"
SOURCES = {
    "micro_dramas": "sampleDoc/Micro Dramas.docx",
    "rush_playback_quality_selection_guide": (
        "sampleDoc/Rush_Playback_Quality_Selection_Guide.docx"
    ),
}


def run_path(index: int) -> Path:
    return FORGE_DIR / f"evaluation-atomic-run{index}.json"


def prepare() -> None:
    cases = []
    for case_id, source_path in SOURCES.items():
        prepared = prepare_assessment(str(ROOT / source_path))
        plan = prepare_evaluation_plan(prepared)
        cases.append(
            {
                "case_id": case_id,
                "source_path": source_path,
                "source_sha256": prepared.snapshot.source.sha256,
                "rubric_version": prepared.rubric.version,
                "batch_id": prepared.batches[0].id,
                "plan_fingerprint": prepared.plan_fingerprint,
                "items": [
                    {
                        "criterion_id": item.criterion_id,
                        "prompt": item.prompt,
                    }
                    for item in plan.items
                ],
            }
        )
    PROMPTS_PATH.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "artifact_type": "forge.atomic_evaluation_prompts.v1",
                "calibration_eligible": False,
                "score_effect": "none",
                "cases": cases,
            },
            indent=2,
        )
        + "\n"
    )
    for run_index in (1, 2, 3):
        run_path(run_index).write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "artifact_type": "forge.atomic_evaluation_run.v1",
                    "calibration_eligible": False,
                    "score_effect": "none",
                    "run_index": run_index,
                    "instructions": [
                        "Complete every criterion independently from its bounded prompt.",
                        "Replace only submission null values with schema-valid JSON objects.",
                        "Use only declared atomic assertion ids and provide a neutral missing_decision for every gap.",
                        "Do not read another run, question artifact, review sheet, or report.",
                    ],
                    "cases": {
                        case["case_id"]: {
                            key: value
                            for key, value in case.items()
                            if key not in {"case_id", "items"}
                        }
                        | {
                            "items": [
                                {
                                    "criterion_id": item["criterion_id"],
                                    "submission": None,
                                }
                                for item in case["items"]
                            ]
                        }
                        for case in cases
                    },
                },
                indent=2,
            )
            + "\n"
        )
    print(
        json.dumps(
            {
                "rubric_version": cases[0]["rubric_version"],
                "case_count": len(cases),
                "criterion_prompts": sum(len(case["items"]) for case in cases),
                "prompts_path": str(PROMPTS_PATH.relative_to(ROOT)),
                "run_paths": [
                    str(run_path(index).relative_to(ROOT))
                    for index in (1, 2, 3)
                ],
            },
            indent=2,
        )
    )


def load_verified():
    payloads = [json.loads(run_path(index).read_text()) for index in (1, 2, 3)]
    result = []
    for case_id, source_path in SOURCES.items():
        prepared = prepare_assessment(str(ROOT / source_path))
        runs = []
        for payload in payloads:
            case = payload["cases"][case_id]
            submissions = [item["submission"] for item in case["items"]]
            if any(item is None for item in submissions):
                raise ValueError(
                    f"atomic run {payload['run_index']} case {case_id} is incomplete"
                )
            runs.append(
                CriterionEvaluationRun(
                    run_index=payload["run_index"],
                    fragments=[
                        CriterionEvaluationFragment(
                            batch_id=case["batch_id"],
                            plan_fingerprint=case["plan_fingerprint"],
                            criteria=submissions,
                        )
                    ],
                )
            )
        result.append(
            (
                case_id,
                source_path,
                prepared,
                verify_evaluation_batch(
                    prepared, CriterionEvaluationBatch(runs=runs)
                ),
            )
        )
    return result


def validate() -> None:
    print(
        json.dumps(
            {
                case_id: {
                    "rubric_version": prepared.rubric.version,
                    "artifacts": len(verified.artifacts),
                    "consolidated": len(verified.consolidated),
                    "atomic_assertions": sum(
                        len(item.assertion_outcomes)
                        for item in verified.consolidated
                    ),
                    "gaps_with_missing_decisions": sum(
                        bool(gap.missing_decisions)
                        for item in verified.consolidated
                        for gap in item.gaps
                    ),
                }
                for case_id, _, prepared, verified in load_verified()
            },
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "validate"))
    args = parser.parse_args()
    prepare() if args.action == "prepare" else validate()


if __name__ == "__main__":
    main()
