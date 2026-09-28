"""Combine independent corpus shadow runs and print diagnostic JSON."""

from __future__ import annotations

import json
from pathlib import Path

from forge.evaluate.batch import (
    CriterionEvaluationBatch,
    CriterionEvaluationFragment,
    CriterionEvaluationRun,
)
from forge.evaluate.diagnostics import (
    EvaluationDiagnosticCase,
    EvaluationDiagnosticSuite,
    evaluate_diagnostics,
)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    payloads = [
        json.loads(
            (root / f"fixtures/evaluation/corpus.run{index}.json").read_text()
        )
        for index in (1, 2, 3)
    ]
    case_ids = set(payloads[0]["cases"])
    if any(set(payload["cases"]) != case_ids for payload in payloads[1:]):
        raise ValueError("corpus shadow runs contain different cases")

    cases: list[EvaluationDiagnosticCase] = []
    for case_id, metadata in payloads[0]["cases"].items():
        source = root / metadata["source_path"]
        runs = [
            CriterionEvaluationRun(
                run_index=payload["run_index"],
                fragments=[
                    CriterionEvaluationFragment(
                        batch_id=payload["cases"][case_id]["batch_id"],
                        plan_fingerprint=payload["cases"][case_id][
                            "plan_fingerprint"
                        ],
                        criteria=payload["cases"][case_id]["criteria"],
                    )
                ],
            )
            for payload in payloads
        ]
        cases.append(
            EvaluationDiagnosticCase(
                case_id=case_id,
                source_kind="authored_regression",
                source_path=metadata["source_path"],
                source_sha256=metadata["source_sha256"],
                rubric_version=metadata["rubric_version"],
                native=CriterionEvaluationBatch(runs=runs),
                legacy_extraction_json=source.with_suffix(
                    ".extraction.json"
                ).read_text(),
            )
        )
    report = evaluate_diagnostics(
        EvaluationDiagnosticSuite(cases=cases), workspace_root=root
    )
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
