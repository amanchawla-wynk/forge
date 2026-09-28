"""Compare native shadow assertions with synthetic AI proxy consensus."""

from __future__ import annotations

import json
from pathlib import Path

from forge.evaluate.batch import (
    CriterionEvaluationBatch,
    CriterionEvaluationFragment,
    CriterionEvaluationRun,
    verify_evaluation_batch,
)
from forge.evaluate.labels import (
    EvaluationReviewerSheet,
    compare_proxy_consensus,
    evaluate_reviewer_sheets,
)
from forge.service import prepare_assessment


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    sheets = [
        EvaluationReviewerSheet.model_validate_json(
            (
                root / f"sampleDoc/.forge/evaluation-ai-proxy-{index}.json"
            ).read_text()
        )
        for index in (1, 2, 3)
    ]
    proxy = evaluate_reviewer_sheets(sheets)
    case_ids = {
        case.source_ref: case.case_id for case in sheets[0].cases
    }
    payloads = [
        json.loads(
            (
                root
                / f"sampleDoc/.forge/evaluation-shadow-run{index}.json"
            ).read_text()
        )
        for index in (1, 2, 3)
    ]
    by_source = [
        {
            metadata["source_path"]: metadata
            for metadata in payload["cases"].values()
        }
        for payload in payloads
    ]

    native_statuses: dict[str, str] = {}
    for source_ref, case_id in case_ids.items():
        prepared = prepare_assessment(str(root / source_ref))
        runs = [
            CriterionEvaluationRun(
                run_index=payload["run_index"],
                fragments=[
                    CriterionEvaluationFragment(
                        batch_id=metadata[source_ref]["batch_id"],
                        plan_fingerprint=metadata[source_ref]["plan_fingerprint"],
                        criteria=metadata[source_ref]["criteria"],
                    )
                ],
            )
            for payload, metadata in zip(payloads, by_source, strict=True)
        ]
        verified = verify_evaluation_batch(
            prepared, CriterionEvaluationBatch(runs=runs)
        )
        for evaluation in verified.consolidated:
            for outcome in evaluation.assertion_outcomes:
                key = f"{case_id}:{evaluation.criterion_id}:{outcome.assertion_id}"
                native_statuses[key] = outcome.status

    comparison = compare_proxy_consensus(native_statuses, proxy)
    print(comparison.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
