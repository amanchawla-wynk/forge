from __future__ import annotations

import hashlib
import json

from forge.evaluate.batch import (
    CriterionEvaluationBatch,
    CriterionEvaluationFragment,
    CriterionEvaluationRun,
)
from forge.evaluate.diagnostics import (
    DiagnosticCallMetadata,
    EvaluationDiagnosticCase,
    EvaluationDiagnosticSuite,
    evaluate_diagnostics,
)
from forge.evaluate.models import CriterionEvaluationSubmission
from forge.rubric.loader import load_rubric


def _empty_native(source, plan_fingerprint):
    rubric = load_rubric("prd")
    criteria = [
        CriterionEvaluationSubmission(criterion_id=criterion.id)
        for criterion in rubric.criteria
    ]
    return CriterionEvaluationBatch(
        runs=[
            CriterionEvaluationRun(
                run_index=index,
                fragments=[
                    CriterionEvaluationFragment(
                        batch_id="batch-1",
                        plan_fingerprint=plan_fingerprint,
                        criteria=criteria,
                    )
                ],
            )
            for index in range(1, 4)
        ]
    )


def _empty_legacy_json():
    rubric = load_rubric("prd")
    return json.dumps(
        {
            "criteria": [
                {
                    "criterion_id": criterion.id,
                    "fields": [
                        {"name": field.name, "value": None, "evidence": None}
                        for field in criterion.fields
                    ],
                }
                for criterion in rubric.criteria
            ]
        }
    )


def test_diagnostics_reports_abstention_metadata_and_symmetric_legacy_comparison(
    tmp_path,
):
    source = tmp_path / "prd.md"
    source.write_text("An incomplete product note.")
    from forge.service import prepare_assessment

    prepared = prepare_assessment(str(source))
    suite = EvaluationDiagnosticSuite(
        cases=[
            EvaluationDiagnosticCase(
                case_id="incomplete",
                source_kind="authored_regression",
                source_path=source.name,
                source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                rubric_name="prd",
                rubric_version=prepared.rubric.version,
                native=_empty_native(source, prepared.plan_fingerprint),
                legacy_extraction_json=_empty_legacy_json(),
                calls=[
                    DiagnosticCallMetadata(
                        run_index=1,
                        batch_id="batch-1",
                        criterion_id="problem_statement",
                        latency_ms=125,
                        input_tokens=100,
                        output_tokens=25,
                    )
                ],
            )
        ]
    )

    report = evaluate_diagnostics(suite, workspace_root=tmp_path)

    assert report.calibration_eligible is False
    assert report.score_effect == "none"
    assert report.case_count == 1
    assert report.status_counts == {"unclear": 15}
    assert report.abstention.total == 15
    assert report.abstention.matched == 15
    assert report.abstention.rate == 1.0
    assert report.full_run_agreement.rate == 1.0
    assert report.assertion_full_agreement.rate == 1.0
    assert report.call_metadata.latency_ms_total == 125
    assert report.call_metadata.input_tokens_total == 100
    assert report.call_metadata.output_tokens_total == 25
    assert report.native_legacy_comparison.paired_criteria == 15
    assert report.native_legacy_comparison.exact_status_agreement == 0
    assert report.native_legacy_comparison.matrix == {
        "unclear": {"unsupported": 15}
    }
    assert "not ground truth" in report.native_legacy_comparison.note
    assert len(report.cases[0].native_legacy_mismatches) == 15
    assert report.cases[0].native_legacy_mismatches[0].criterion_id
    assert report.cases[0].run_disagreement_criteria == []
    assert report.cases[0].assertion_full_agreement.rate == 1.0
    assert report.cases[0].criterion_run_statuses["problem_statement"] == [
        "unclear",
        "unclear",
        "unclear",
    ]
