"""Prepare and validate independent internal evaluation runs for question v2."""

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
PROMPTS_PATH = FORGE_DIR / "evaluation-shadow-v2-prompts.json"


def _run_path(index: int) -> Path:
    return FORGE_DIR / f"evaluation-shadow-v2-run{index}.json"


def prepare() -> None:
    baseline = json.loads((FORGE_DIR / "evaluation-shadow-run1.json").read_text())
    cases = []
    for case_id, old in sorted(baseline["cases"].items()):
        prepared = prepare_assessment(str(ROOT / old["source_path"]))
        plan = prepare_evaluation_plan(prepared)
        cases.append(
            {
                "case_id": case_id,
                "source_path": old["source_path"],
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
                "artifact_type": "forge.internal_evaluation_shadow_v2_prompts",
                "calibration_eligible": False,
                "score_effect": "none",
                "cases": cases,
            },
            indent=2,
        )
        + "\n"
    )
    for run_index in (1, 2, 3):
        _run_path(run_index).write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "artifact_type": "forge.internal_evaluation_shadow_v2_run",
                    "calibration_eligible": False,
                    "score_effect": "none",
                    "run_index": run_index,
                    "instructions": [
                        "Complete each criterion independently from its bounded prompt.",
                        "Replace only submission null values with one JSON object matching the prompt schema.",
                        "For each gap, provide one neutral missing_decision without asserting unstated behavior.",
                        "Do not read another run, question artifacts, reviewer sheets, or reports.",
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
                "case_count": len(cases),
                "criterion_prompts": sum(len(case["items"]) for case in cases),
                "prompts_path": str(PROMPTS_PATH.relative_to(ROOT)),
                "run_paths": [
                    str(_run_path(index).relative_to(ROOT))
                    for index in (1, 2, 3)
                ],
            },
            indent=2,
        )
    )


def validate() -> None:
    payloads = [json.loads(_run_path(index).read_text()) for index in (1, 2, 3)]
    case_ids = set(payloads[0]["cases"])
    if any(set(payload["cases"]) != case_ids for payload in payloads[1:]):
        raise ValueError("v2 evaluation runs contain different cases")
    summary = {}
    for case_id in sorted(case_ids):
        metadata = payloads[0]["cases"][case_id]
        prepared = prepare_assessment(str(ROOT / metadata["source_path"]))
        runs = []
        for payload in payloads:
            run_case = payload["cases"][case_id]
            submissions = [item["submission"] for item in run_case["items"]]
            if any(item is None for item in submissions):
                raise ValueError(
                    f"run {payload['run_index']} case {case_id} is incomplete"
                )
            runs.append(
                CriterionEvaluationRun(
                    run_index=payload["run_index"],
                    fragments=[
                        CriterionEvaluationFragment(
                            batch_id=run_case["batch_id"],
                            plan_fingerprint=run_case["plan_fingerprint"],
                            criteria=submissions,
                        )
                    ],
                )
            )
        verified = verify_evaluation_batch(
            prepared, CriterionEvaluationBatch(runs=runs)
        )
        summary[case_id] = {
            "artifacts": len(verified.artifacts),
            "consolidated": len(verified.consolidated),
            "gaps_with_missing_decisions": sum(
                bool(gap.missing_decisions)
                for evaluation in verified.consolidated
                for gap in evaluation.gaps
            ),
            "question_generation_available": verified.question_generation is not None,
        }
    print(json.dumps(summary, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "validate"))
    args = parser.parse_args()
    prepare() if args.action == "prepare" else validate()


if __name__ == "__main__":
    main()
