"""Combine ignored internal PRD shadow runs and print diagnostic JSON."""

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
            (
                root
                / f"sampleDoc/.forge/evaluation-shadow-run{index}.json"
            ).read_text()
        )
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

    cases: list[EvaluationDiagnosticCase] = []
    for source_path, (case_id, metadata) in cases_by_source[0].items():
        runs = [
            CriterionEvaluationRun(
                run_index=payload["run_index"],
                fragments=[
                    CriterionEvaluationFragment(
                        batch_id=by_source[source_path][1]["batch_id"],
                        plan_fingerprint=by_source[source_path][1][
                            "plan_fingerprint"
                        ],
                        criteria=by_source[source_path][1]["criteria"],
                    )
                ],
            )
            for payload, by_source in zip(payloads, cases_by_source, strict=True)
        ]
        cases.append(
            EvaluationDiagnosticCase(
                case_id=case_id,
                source_kind="internal",
                source_path=metadata["source_path"],
                source_sha256=metadata["source_sha256"],
                rubric_version=metadata["rubric_version"],
                native=CriterionEvaluationBatch(runs=runs),
            )
        )
    report = evaluate_diagnostics(
        EvaluationDiagnosticSuite(cases=cases), workspace_root=root
    )
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
