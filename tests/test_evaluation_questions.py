from __future__ import annotations

import json

import pytest

from forge.evaluate.models import (
    Applicability,
    AssertionOutcome,
    CriterionEvaluation,
    EvaluationConfidence,
    EvaluationContradiction,
    EvaluationGap,
    EvidenceSpan,
    SemanticStatus,
)
from forge.questions.apply import (
    apply_question_generation,
    render_deterministic_question,
)
from forge.questions.diagnostics import (
    QuestionCompletion,
    evaluate_question_diagnostics,
)
from forge.questions.labels import (
    QuestionReviewChoice,
    evaluate_question_reviewer_sheets,
    make_question_reviewer_sheet,
)
from forge.questions.prepare import (
    prepare_question_generation,
    prepare_question_generations,
)
from forge.rubric.loader import load_rubric


def _contradictory_evaluation(*, run_count: int = 3) -> CriterionEvaluation:
    left_id = "1" * 64
    right_id = "2" * 64
    issue_id = "3" * 64
    return CriterionEvaluation(
        evaluation_id="4" * 64,
        criterion_id="functional_requirements",
        snapshot_id="5" * 64,
        rubric_id="prd",
        rubric_version="0.9.1-applicability-contracts-shadow",
        plan_fingerprint="plan-1",
        run_ids=[f"run-{index}" for index in range(run_count)],
        batch_ids=["batch-1"],
        coverage_complete=True,
        applicability=Applicability.APPLICABLE,
        status=SemanticStatus.CONTRADICTORY,
        evidence=[
            EvidenceSpan(
                evidence_id=left_id,
                snapshot_id="5" * 64,
                source_block_id="block-1",
                start_char=0,
                end_char=37,
                exact_quote="When the global flag is off, use ABR.",
                provenance="document",
                section="Rules",
            ),
            EvidenceSpan(
                evidence_id=right_id,
                snapshot_id="5" * 64,
                source_block_id="block-2",
                start_char=0,
                end_char=45,
                exact_quote="When the global flag is off, enable Data Saver.",
                provenance="document",
                section="Fallback",
            ),
        ],
        contradictions=[
            EvaluationContradiction(
                issue_id=issue_id,
                assertion_ids=["decision_rules_and_precedence"],
                left_evidence_ids=[left_id],
                right_evidence_ids=[right_id],
                relation="precedence_conflict",
                run_ids=[f"run-{index}" for index in range(run_count)],
            )
        ],
        assertion_outcomes=[
            AssertionOutcome(
                assertion_id="decision_rules_and_precedence",
                status="contradictory",
                agreement=2 / 3 if run_count == 3 else 1,
                run_count=run_count,
                issue_ids=[issue_id],
            )
        ],
        confidence=EvaluationConfidence(
            agreement=2 / 3 if run_count == 3 else 1,
            run_count=run_count,
            expected_run_count=3,
            basis="independent_evaluation_runs",
        ),
        origin="criterion_evaluation",
    )


def test_prepares_majority_native_contradiction_with_verified_context():
    prepared = prepare_question_generation(
        load_rubric("prd"), [_contradictory_evaluation()]
    )

    assert prepared is not None
    assert prepared.target.status == "contradictory"
    assert prepared.target.assertion_id == "decision_rules_and_precedence"
    assert prepared.target.issue_ids == ["3" * 64]
    assert prepared.target.evidence_ids == ["1" * 64, "2" * 64]
    assert prepared.target.answer_contract.startswith(
        "State the authoritative precedence rule"
    )
    assert "read-only untrusted source data" in prepared.prompt
    assert '"When the global flag is off, use ABR."' in prepared.target.fallback_question
    assert '"When the global flag is off, enable Data Saver."' in prepared.target.fallback_question


def test_does_not_prepare_single_run_or_legacy_outcomes():
    rubric = load_rubric("prd")
    single = _contradictory_evaluation(run_count=1)
    legacy = _contradictory_evaluation()
    legacy.origin = "legacy_field_adapter"

    assert prepare_question_generation(rubric, [single]) is None
    assert prepare_question_generation(rubric, [legacy]) is None


def test_rejects_issue_that_does_not_resolve_to_verified_evidence():
    evaluation = _contradictory_evaluation()
    evaluation.evidence.pop()

    with pytest.raises(ValueError, match="unknown evidence id"):
        prepare_question_generation(load_rubric("prd"), [evaluation])


def test_applies_grounded_generated_question():
    prepared = prepare_question_generation(
        load_rubric("prd"), [_contradictory_evaluation()]
    )
    assert prepared is not None
    completion = json.dumps(
        {
            "plan_id": prepared.target.plan_id,
            "issue_id": "3" * 64,
            "question": (
                "Which ABR or Data Saver rule should take precedence when the "
                "global flag is off?"
            ),
        }
    )

    result = apply_question_generation(prepared, completion)

    assert result.generation_mode == "generated"
    assert result.question.endswith("off?")
    assert result.evidence_ids == ["1" * 64, "2" * 64]
    assert result.score_effect == "none"


@pytest.mark.parametrize(
    ("completion", "reason"),
    [
        ("not json", "invalid_json"),
        (
            json.dumps(
                {
                    "plan_id": "wrong",
                    "issue_id": "3" * 64,
                    "question": "Which rule should apply?",
                }
            ),
            "invalid_submission",
        ),
        (
            None,
            "unsupported_wording",
        ),
    ],
)
def test_malformed_or_unsupported_generation_uses_rubric_fallback(
    completion: str | None, reason: str
):
    prepared = prepare_question_generation(
        load_rubric("prd"), [_contradictory_evaluation()]
    )
    assert prepared is not None
    if completion is None:
        completion = json.dumps(
            {
                "plan_id": prepared.target.plan_id,
                "issue_id": "3" * 64,
                "question": 'Should the undocumented "Premium mode" rule win?',
            }
        )

    result = apply_question_generation(prepared, completion)

    assert result.generation_mode == "rubric_fallback"
    assert result.question == prepared.target.fallback_question
    assert result.rejection_reason == reason


def test_question_diagnostics_measure_generation_fallback_duplicates_and_stability():
    prepared = prepare_question_generations(
        load_rubric("prd"), [_contradictory_evaluation()]
    )
    assert len(prepared) == 1
    completion = QuestionCompletion(
        plan_id=prepared[0].target.plan_id,
        completion=json.dumps(
            {
                "plan_id": prepared[0].target.plan_id,
                "issue_id": "3" * 64,
                "question": (
                    "Which ABR or Data Saver rule should take precedence when "
                    "the global flag is off?"
                ),
            }
        ),
    )

    report = evaluate_question_diagnostics(
        prepared,
        [completion],
        repeated_preparations=prepare_question_generations(
            load_rubric("prd"), [_contradictory_evaluation()]
        ),
    )

    assert report.calibration_eligible is False
    assert report.score_effect == "none"
    assert report.eligible_questions == 1
    assert report.generated.rate == 1.0
    assert report.deterministic.rate == 0.0
    assert report.fallback.rate == 0.0
    assert report.unsupported_text_count == 0
    assert report.duplicates.matched == 0
    assert report.stable is True

    duplicate = prepared[0].model_copy(deep=True)
    duplicate.target.plan_id = "9" * 64
    fallback_report = evaluate_question_diagnostics(
        [prepared[0], duplicate], []
    )
    assert fallback_report.fallback.rate == 1.0
    assert fallback_report.duplicates.matched == 1
    assert fallback_report.missing_completions == 2
    grouped_report = evaluate_question_diagnostics(
        [prepared[0], duplicate],
        [],
        group_by_plan={
            prepared[0].target.plan_id: "case-a",
            duplicate.target.plan_id: "case-b",
        },
    )
    assert grouped_report.duplicates.matched == 0

    deterministic = evaluate_question_diagnostics(
        prepared,
        [],
        repeated_preparations=prepare_question_generations(
            load_rubric("prd"), [_contradictory_evaluation()]
        ),
        deterministic_primary=True,
    )
    assert deterministic.deterministic.rate == 1.0
    assert deterministic.generated.rate == 0.0
    assert deterministic.fallback.rate == 0.0
    assert deterministic.questions[0] == render_deterministic_question(prepared[0])
    assert deterministic.questions[0].generation_mode == "deterministic_template"
    assert deterministic.questions[0].rejection_reason is None


def test_question_proxy_reviews_use_strict_majority_and_are_not_calibration():
    questions = [
        (
            "q1",
            "Which ABR or Data Saver rule should take precedence when the flag is off?",
        )
    ]
    sheets = [
        make_question_reviewer_sheet(
            reviewer_id=f"proxy-{index}",
            cases=[("rush", "sampleDoc/Rush Guide.docx", questions)],
        )
        for index in range(1, 4)
    ]
    choices = [
        QuestionReviewChoice.YES,
        QuestionReviewChoice.YES,
        QuestionReviewChoice.NO,
    ]
    for sheet, choice in zip(sheets, choices, strict=True):
        review = sheet.cases[0].questions[0]
        review.relevant = choice
        review.answerable = QuestionReviewChoice.YES
        review.smallest_scope = choice
        review.unsupported_assumption = QuestionReviewChoice.NO

    report = evaluate_question_reviewer_sheets(sheets)

    assert report.label_authority == "synthetic_ai_proxy"
    assert report.calibration_eligible is False
    assert report.compared_questions == 1
    assert report.unanimous_questions == 0
    assert report.consensus["rush:q1"].relevant is QuestionReviewChoice.YES
    assert report.consensus["rush:q1"].unsupported_assumption is QuestionReviewChoice.NO


def test_question_plans_deduplicate_shared_issues_and_defer_later_gaps():
    rubric = load_rubric("prd")
    shared = _contradictory_evaluation()
    shared.assertion_outcomes.insert(
        0,
        AssertionOutcome(
            assertion_id="requirements",
            status="contradictory",
            agreement=2 / 3,
            run_count=3,
            issue_ids=["3" * 64],
        ),
    )
    shared.contradictions[0].assertion_ids.append("requirements")
    second_issue = shared.contradictions[0].model_copy(
        update={"issue_id": "8" * 64}
    )
    shared.contradictions.append(second_issue)
    shared.assertion_outcomes[0].issue_ids.append("8" * 64)

    plans = prepare_question_generations(rubric, [shared])

    assert len(plans) == 1
    assert plans[0].target.issue_ids == ["3" * 64, "8" * 64]

    gaps = _contradictory_evaluation()
    gaps.criterion_id = "success_metrics"
    gaps.status = SemanticStatus.UNSUPPORTED
    gaps.evidence = []
    gaps.contradictions = []
    gaps.gaps = [
        EvaluationGap(
            gap_id="6" * 64,
            assertion_ids=["primary_metric"],
            kind="missing_decision",
            question="Which single metric will tell us whether this worked?",
            missing_decisions=["Name the primary outcome metric."],
        ),
        EvaluationGap(
            gap_id="7" * 64,
            assertion_ids=["baseline"],
            kind="missing_decision",
            question="What is that metric's current numeric value?",
            missing_decisions=["State the current value of the selected metric."],
        ),
    ]
    gaps.assertion_outcomes = [
        AssertionOutcome(
            assertion_id="primary_metric",
            status="gap",
            agreement=1,
            run_count=3,
            issue_ids=["6" * 64],
        ),
        AssertionOutcome(
            assertion_id="baseline",
            status="gap",
            agreement=1,
            run_count=3,
            issue_ids=["7" * 64],
        ),
    ]

    plans = prepare_question_generations(rubric, [gaps])

    assert [item.target.assertion_id for item in plans] == ["primary_metric"]
    assert plans[0].target.issues[0].missing_decisions == [
        "Name the primary outcome metric."
    ]


def test_question_plans_require_supported_atomic_prerequisites():
    rubric = load_rubric("prd")
    evaluation = _contradictory_evaluation()
    evaluation.criterion_id = "dependencies"
    evaluation.status = SemanticStatus.UNSUPPORTED
    evaluation.evidence = []
    evaluation.contradictions = []
    evaluation.gaps = [
        EvaluationGap(
            gap_id="6" * 64,
            assertion_ids=["dependencies"],
            kind="missing_decision",
            question="Name the material dependency.",
            missing_decisions=["Name the material dependency."],
        ),
        EvaluationGap(
            gap_id="7" * 64,
            assertion_ids=["dependency_owner"],
            kind="missing_decision",
            question="Name the accountable owner.",
            missing_decisions=["Name the accountable owner."],
        ),
    ]
    evaluation.assertion_outcomes = [
        AssertionOutcome(
            assertion_id="dependencies",
            status="gap",
            agreement=1,
            run_count=3,
            issue_ids=["6" * 64],
        ),
        AssertionOutcome(
            assertion_id="dependency_owner",
            status="gap",
            agreement=1,
            run_count=3,
            issue_ids=["7" * 64],
        ),
    ]

    plans = prepare_question_generations(rubric, [evaluation])

    assert [item.target.assertion_id for item in plans] == ["dependencies"]
    assert plans[0].target.prerequisite_assertion_ids == []

    evaluation.assertion_outcomes[0] = AssertionOutcome(
        assertion_id="dependencies",
        status="supported",
        agreement=1,
        run_count=3,
    )
    plans = prepare_question_generations(rubric, [evaluation])

    assert [item.target.assertion_id for item in plans] == ["dependency_owner"]
    assert plans[0].target.prerequisite_assertion_ids == ["dependencies"]
    assert plans[0].target.answer_contract == (
        "Name the accountable owner for the material dependency."
    )


def test_gap_question_uses_verified_prerequisite_evidence_as_subject_context():
    rubric = load_rubric("prd")
    evaluation = _contradictory_evaluation()
    evaluation.criterion_id = "dependencies"
    evaluation.status = SemanticStatus.PARTIAL
    evaluation.contradictions = []
    evidence_id = "6" * 64
    gap_id = "7" * 64
    evaluation.evidence = [
        EvidenceSpan(
            evidence_id=evidence_id,
            snapshot_id="5" * 64,
            source_block_id="block-1",
            start_char=0,
            end_char=45,
            exact_quote="Three content partners must approve the POC.",
            provenance="document",
            section="Dependencies",
        )
    ]
    evaluation.gaps = [
        EvaluationGap(
            gap_id=gap_id,
            assertion_ids=["dependency_owner"],
            kind="missing_decision",
            question="Name the accountable owner.",
        )
    ]
    evaluation.assertion_outcomes = [
        AssertionOutcome(
            assertion_id="dependencies",
            status="supported",
            agreement=1,
            run_count=3,
            evidence_ids=[evidence_id],
        ),
        AssertionOutcome(
            assertion_id="dependency_owner",
            status="gap",
            agreement=1,
            run_count=3,
            issue_ids=[gap_id],
        ),
    ]

    prepared = prepare_question_generation(rubric, [evaluation])

    assert prepared is not None
    assert prepared.target.subject is not None
    assert prepared.target.subject.assertion_id == "dependencies"
    assert prepared.target.subject.evidence.evidence_id == evidence_id
    assert "Three content partners must approve the POC." in (
        prepared.target.fallback_question
    )
    rendered = render_deterministic_question(prepared)
    assert rendered.evidence_ids == [evidence_id]


def test_gap_question_does_not_use_unrelated_same_field_sibling_as_subject():
    rubric = load_rubric("prd")
    evaluation = _contradictory_evaluation()
    evaluation.criterion_id = "acceptance_criteria"
    evaluation.status = SemanticStatus.PARTIAL
    evaluation.contradictions = []
    evidence_id = "6" * 64
    gap_id = "7" * 64
    evaluation.evidence = [
        EvidenceSpan(
            evidence_id=evidence_id,
            snapshot_id="5" * 64,
            source_block_id="block-1",
            start_char=0,
            end_char=30,
            exact_quote="A table row passes at 720p.",
            provenance="document",
        )
    ]
    evaluation.gaps = [
        EvaluationGap(
            gap_id=gap_id,
            assertion_ids=["completion_outcome"],
            kind="missing_decision",
            question="State completion.",
        )
    ]
    evaluation.assertion_outcomes = [
        AssertionOutcome(
            assertion_id="acceptance_subject",
            status="supported",
            agreement=1,
            run_count=3,
        ),
        AssertionOutcome(
            assertion_id="pass_condition",
            status="supported",
            agreement=1,
            run_count=3,
            evidence_ids=[evidence_id],
        ),
        AssertionOutcome(
            assertion_id="completion_outcome",
            status="gap",
            agreement=1,
            run_count=3,
            issue_ids=[gap_id],
        ),
    ]

    prepared = prepare_question_generation(rubric, [evaluation])

    assert prepared is not None
    assert prepared.target.subject is None
    assert "720p" not in prepared.target.fallback_question


def test_gap_question_uses_explicit_rubric_framing_variant_only():
    rubric = load_rubric("prd")
    evaluation = _contradictory_evaluation()
    evaluation.criterion_id = "problem_statement"
    evaluation.status = SemanticStatus.UNSUPPORTED
    evaluation.evidence = []
    evaluation.contradictions = []
    evaluation.gaps = [
        EvaluationGap(
            gap_id="6" * 64,
            assertion_ids=["problem"],
            kind="missing_decision",
            question="State the problem.",
        )
    ]
    evaluation.assertion_outcomes = [
        AssertionOutcome(
            assertion_id="problem",
            status="gap",
            agreement=1,
            run_count=3,
            issue_ids=["6" * 64],
        )
    ]

    opportunity = prepare_question_generation(
        rubric, [evaluation], framing="opportunity_bet"
    )
    unknown = prepare_question_generation(rubric, [evaluation], framing="unknown")

    assert opportunity is not None
    assert opportunity.target.fallback_question == (
        "What specific opportunity is this pursuing?"
    )
    assert unknown is not None
    assert unknown.target.fallback_question == (
        "State the problem or framing-appropriate driver for this work."
    )


def test_recovery_procedure_waits_for_diagnostic_method():
    rubric = load_rubric("prd")
    evaluation = _contradictory_evaluation()
    evaluation.criterion_id = "operational_readiness"
    evaluation.status = SemanticStatus.UNSUPPORTED
    evaluation.evidence = []
    evaluation.contradictions = []
    evaluation.gaps = [
        EvaluationGap(
            gap_id="6" * 64,
            assertion_ids=["diagnostic_method"],
            kind="missing_decision",
            question="State the diagnostic method.",
        ),
        EvaluationGap(
            gap_id="7" * 64,
            assertion_ids=["recovery_procedure"],
            kind="missing_decision",
            question="State the recovery procedure.",
        ),
    ]
    evaluation.assertion_outcomes = [
        AssertionOutcome(
            assertion_id="diagnostic_method",
            status="gap",
            agreement=1,
            run_count=3,
            issue_ids=["6" * 64],
        ),
        AssertionOutcome(
            assertion_id="recovery_procedure",
            status="gap",
            agreement=1,
            run_count=3,
            issue_ids=["7" * 64],
        ),
    ]

    plans = prepare_question_generations(rubric, [evaluation])
    assert [item.target.assertion_id for item in plans] == ["diagnostic_method"]

    evaluation.assertion_outcomes[0] = AssertionOutcome(
        assertion_id="diagnostic_method",
        status="supported",
        agreement=1,
        run_count=3,
    )
    plans = prepare_question_generations(rubric, [evaluation])
    assert [item.target.assertion_id for item in plans] == ["recovery_procedure"]
    assert plans[0].target.prerequisite_assertion_ids == ["diagnostic_method"]


def test_rollout_promotion_waits_for_entry_and_observation():
    rubric = load_rubric("prd")
    evaluation = _contradictory_evaluation()
    evaluation.criterion_id = "rollout"
    evaluation.status = SemanticStatus.UNSUPPORTED
    evaluation.evidence = []
    evaluation.contradictions = []
    ids = {
        "entry_criteria": "6" * 64,
        "observation_window": "7" * 64,
        "promotion_criteria": "8" * 64,
    }
    evaluation.gaps = [
        EvaluationGap(
            gap_id=gap_id,
            assertion_ids=[assertion_id],
            kind="missing_decision",
            question=f"Resolve {assertion_id}.",
        )
        for assertion_id, gap_id in ids.items()
    ]
    evaluation.assertion_outcomes = [
        AssertionOutcome(
            assertion_id="rollout_mechanism",
            status="supported",
            agreement=1,
            run_count=3,
        ),
        *[
            AssertionOutcome(
                assertion_id=assertion_id,
                status="gap",
                agreement=1,
                run_count=3,
                issue_ids=[gap_id],
            )
            for assertion_id, gap_id in ids.items()
        ],
    ]

    plans = prepare_question_generations(rubric, [evaluation])
    assert [item.target.assertion_id for item in plans] == ["entry_criteria"]

    evaluation.assertion_outcomes[1] = AssertionOutcome(
        assertion_id="entry_criteria",
        status="supported",
        agreement=1,
        run_count=3,
    )
    plans = prepare_question_generations(rubric, [evaluation])
    assert [item.target.assertion_id for item in plans] == ["observation_window"]

    evaluation.assertion_outcomes[2] = AssertionOutcome(
        assertion_id="observation_window",
        status="supported",
        agreement=1,
        run_count=3,
    )
    plans = prepare_question_generations(rubric, [evaluation])
    assert [item.target.assertion_id for item in plans] == ["promotion_criteria"]
    assert plans[0].target.prerequisite_assertion_ids == [
        "entry_criteria",
        "observation_window",
    ]


def test_events_wait_for_metric_reference_before_metric_formula():
    rubric = load_rubric("prd")
    evaluation = _contradictory_evaluation()
    evaluation.criterion_id = "instrumentation"
    evaluation.status = SemanticStatus.UNSUPPORTED
    evaluation.evidence = []
    evaluation.contradictions = []
    ids = {
        "instrumentation_applicability": "5" * 64,
        "event_declarations": "6" * 64,
        "metric_definition_reference": "7" * 64,
        "metric_formula": "8" * 64,
    }
    evaluation.gaps = [
        EvaluationGap(
            gap_id=gap_id,
            assertion_ids=[assertion_id],
            kind="missing_decision",
            question=f"Resolve {assertion_id}.",
        )
        for assertion_id, gap_id in ids.items()
    ]
    evaluation.assertion_outcomes = [
        AssertionOutcome(
            assertion_id=assertion_id,
            status="gap",
            agreement=1,
            run_count=3,
            issue_ids=[gap_id],
        )
        for assertion_id, gap_id in ids.items()
    ]

    plans = prepare_question_generations(rubric, [evaluation])
    assert [item.target.assertion_id for item in plans] == [
        "instrumentation_applicability"
    ]

    evaluation.assertion_outcomes[0] = AssertionOutcome(
        assertion_id="instrumentation_applicability",
        status="supported",
        agreement=1,
        run_count=3,
    )
    plans = prepare_question_generations(rubric, [evaluation])
    assert [item.target.assertion_id for item in plans] == [
        "metric_definition_reference"
    ]
    assert plans[0].target.fallback_question == (
        "Name the success metric this instrumentation must measure."
    )

    evaluation.assertion_outcomes[2] = AssertionOutcome(
        assertion_id="metric_definition_reference",
        status="supported",
        agreement=1,
        run_count=3,
    )
    plans = prepare_question_generations(rubric, [evaluation])
    assert [item.target.assertion_id for item in plans] == ["event_declarations"]

    evaluation.assertion_outcomes[1] = AssertionOutcome(
        assertion_id="event_declarations",
        status="supported",
        agreement=1,
        run_count=3,
    )
    plans = prepare_question_generations(rubric, [evaluation])
    assert [item.target.assertion_id for item in plans] == ["metric_formula"]
    assert plans[0].target.prerequisite_assertion_ids == [
        "event_declarations",
        "metric_definition_reference",
    ]


def test_requirement_mapping_waits_for_requirement_set_and_pass_fail_cases():
    rubric = load_rubric("prd")
    evaluation = _contradictory_evaluation()
    evaluation.criterion_id = "acceptance_criteria"
    evaluation.status = SemanticStatus.UNSUPPORTED
    evaluation.evidence = []
    evaluation.contradictions = []
    ids = {
        "launch_critical_requirement_set": "6" * 64,
        "pass_condition": "7" * 64,
        "fail_condition": "8" * 64,
        "requirement_case_mapping": "9" * 64,
    }
    evaluation.gaps = [
        EvaluationGap(
            gap_id=gap_id,
            assertion_ids=[assertion_id],
            kind="missing_decision",
            question=f"Resolve {assertion_id}.",
        )
        for assertion_id, gap_id in ids.items()
    ]
    evaluation.assertion_outcomes = [
        AssertionOutcome(
            assertion_id="acceptance_subject",
            status="supported",
            agreement=1,
            run_count=3,
        ),
        *[
            AssertionOutcome(
                assertion_id=assertion_id,
                status="gap",
                agreement=1,
                run_count=3,
                issue_ids=[gap_id],
            )
            for assertion_id, gap_id in ids.items()
        ],
    ]

    plans = prepare_question_generations(rubric, [evaluation])
    assert [item.target.assertion_id for item in plans] == ["pass_condition"]

    for index, assertion_id in enumerate(
        ("launch_critical_requirement_set", "pass_condition", "fail_condition")
    ):
        outcome_index = list(ids).index(assertion_id) + 1
        evaluation.assertion_outcomes[outcome_index] = AssertionOutcome(
            assertion_id=assertion_id,
            status="supported",
            agreement=1,
            run_count=3,
        )
        if index < 2:
            plans = prepare_question_generations(rubric, [evaluation])
            assert all(
                item.target.assertion_id != "requirement_case_mapping"
                for item in plans
            )

    plans = prepare_question_generations(rubric, [evaluation])
    assert [item.target.assertion_id for item in plans] == [
        "requirement_case_mapping"
    ]
