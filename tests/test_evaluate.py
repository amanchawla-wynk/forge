from __future__ import annotations

import pytest
from pydantic import ValidationError

from forge.evaluate.consolidate import (
    consolidate_evaluation_fragments,
    consolidate_evaluation_runs,
    evaluations_from_legacy_extraction_run,
    legacy_extraction_run_from_evaluations,
)
from forge.evaluate.batch import (
    CriterionEvaluationBatch,
    CriterionEvaluationFragment,
    CriterionEvaluationRun,
    prepare_evaluation_plan,
    verify_evaluation_batch,
)
from forge.evaluate.models import (
    Applicability,
    AssertionOutcome,
    CriterionEvaluation,
    CriterionEvaluationSubmission,
    EvaluationContradiction,
    EvidenceReference,
    SubmittedClaim,
    SubmittedAmbiguity,
    SubmittedContradiction,
    SubmittedEvidenceSet,
    SubmittedGap,
    SemanticStatus,
    SupportRelation,
)
from forge.evaluate.prompt import (
    build_criterion_evaluation_prompt,
    parse_criterion_evaluation,
)
from forge.evaluate.verify import verify_criterion_evaluation
from forge.extract.batch import ExtractionBatch, ExtractionRun
from forge.extract.models import CriterionExtraction, Evidence, FieldExtraction
from forge.ingest.models import NormalizedDocument, SourceBlock
from forge.remediation import begin_remediation
from forge.rubric.loader import load_rubric
from forge.rubric.models import CriterionEvaluationSpec
from forge.score.engine import score
from forge.service import assess_extractions
from forge.sessions import ReviewSessionRepository


def _document() -> NormalizedDocument:
    return NormalizedDocument(
        source_path="/tmp/prd.md",
        source_type="md",
        snapshot_id="a" * 64,
        source_sha256="b" * 64,
        parser_fingerprint="test-parser/1.0",
        normalized_hash="c" * 64,
        normalized_schema_version="1.0",
        blocks=[
            SourceBlock(
                id="block-1",
                text="Launch conversion is 10%. The target is 20%.",
                section="Metrics",
            ),
            SourceBlock(
                id="block-2",
                text="The target is 20%, but finance requires 15%.",
                section="Constraints",
            ),
        ],
    )


def _submission() -> CriterionEvaluationSubmission:
    return CriterionEvaluationSubmission(
        criterion_id="success_metrics",
        applicability=Applicability.APPLICABLE,
        evidence=[
            EvidenceReference(
                ref_id="baseline-evidence",
                source_block_id="block-1",
                quote="Launch conversion is 10%.",
            ),
            EvidenceReference(
                ref_id="target-evidence",
                source_block_id="block-1",
                quote="The target is 20%.",
            ),
        ],
        claims=[
            SubmittedClaim(
                claim_ref="baseline-claim",
                assertion_id="baseline",
                value="10%",
                evidence_refs=["baseline-evidence"],
            ),
            SubmittedClaim(
                claim_ref="target-claim",
                assertion_id="target",
                value="20%",
                evidence_refs=["target-evidence"],
            ),
        ],
        evidence_sets=[
            SubmittedEvidenceSet(
                evidence_set_ref="metric-set",
                assertion_ids=["baseline", "target"],
                claim_refs=["baseline-claim", "target-claim"],
                evidence_refs=["baseline-evidence", "target-evidence"],
                relation=SupportRelation.SUPPORTS,
            )
        ],
        gaps=[
            SubmittedGap(
                gap_ref="window-gap",
                assertion_ids=["measurement_window"],
                kind="missing_decision",
            )
        ],
    )


def test_submission_rejects_model_authored_verified_ids():
    payload = _submission().model_dump()
    payload["evidence"][0]["evidence_id"] = "model-controlled"

    with pytest.raises(ValidationError):
        CriterionEvaluationSubmission.model_validate(payload)


def test_verifier_mints_block_bound_evidence_and_gap_ids():
    rubric = load_rubric("prd")

    evaluation = verify_criterion_evaluation(
        _document(),
        rubric,
        _submission(),
        plan_fingerprint="plan-1",
        run_id="run-1",
        batch_ids=["batch-1"],
        coverage_complete=True,
    )

    assert evaluation.snapshot_id == "a" * 64
    assert len(evaluation.evidence) == 2
    assert all(len(item.evidence_id) == 64 for item in evaluation.evidence)
    assert evaluation.evidence_sets[0].relation is SupportRelation.SUPPORTS
    assert set(evaluation.evidence_sets[0].assertion_ids) == {"baseline", "target"}
    assert evaluation.gaps[0].assertion_ids == ["measurement_window"]
    assert evaluation.gaps[0].question == rubric.criterion(
        "success_metrics"
    ).field("measurement_window").remediation_question


def test_verifier_rejects_claim_without_evidence_set_relation():
    submission = _submission()
    submission.evidence_sets = []

    with pytest.raises(ValueError, match="claim refs missing evidence set relation"):
        verify_criterion_evaluation(
            _document(),
            load_rubric("prd"),
            submission,
            plan_fingerprint="plan-1",
            run_id="run-1",
            batch_ids=["batch-1"],
            coverage_complete=True,
        )


def test_verifier_rejects_evidence_set_that_omits_claim_assertion():
    submission = _submission()
    submission.evidence_sets[0].assertion_ids = ["baseline"]

    with pytest.raises(ValueError, match="does not include claim assertion 'target'"):
        verify_criterion_evaluation(
            _document(),
            load_rubric("prd"),
            submission,
            plan_fingerprint="plan-1",
            run_id="run-1",
            batch_ids=["batch-1"],
            coverage_complete=True,
        )


def test_evaluation_prompt_requires_relations_for_every_claim():
    prompt = build_criterion_evaluation_prompt(
        _document(),
        load_rubric("prd").criterion("success_metrics"),
        batch_id="batch-1",
        plan_fingerprint="plan-1",
        run_index=1,
    )

    assert "Every claim must be linked by at least one evidence set" in prompt
    assert "Do not report a gap for an assertion satisfied by an exact source" in prompt


def test_same_quote_in_different_blocks_has_distinct_evidence_identity():
    document = _document().model_copy(deep=True)
    document.blocks[1].text = "The target is 20%."
    submission = _submission()
    submission.evidence.append(
        EvidenceReference(
            ref_id="second-target",
            source_block_id="block-2",
            quote="The target is 20%.",
        )
    )
    submission.contradictions.append(
        SubmittedContradiction(
            issue_ref="target-conflict",
            assertion_ids=["target"],
            left_evidence_refs=["target-evidence"],
            right_evidence_refs=["second-target"],
            relation="scoped_contradiction",
        )
    )

    evaluation = verify_criterion_evaluation(
        document,
        load_rubric("prd"),
        submission,
        plan_fingerprint="plan-1",
        run_id="run-1",
        batch_ids=["batch-1"],
        coverage_complete=True,
    )

    target_ids = {
        span.evidence_id
        for span in evaluation.evidence
        if span.exact_quote == "The target is 20%."
    }
    assert len(target_ids) == 2
    assert evaluation.contradictions[0].left_evidence_ids != (
        evaluation.contradictions[0].right_evidence_ids
    )


def test_legacy_adapter_round_trip_preserves_score_and_evidence():
    rubric = load_rubric("prd")
    criterion = rubric.criterion("success_metrics")
    extraction = CriterionExtraction(
        criterion_id=criterion.id,
        fields=[
            FieldExtraction(
                name=field.name,
                value=("10%" if field.name == "baseline" else None),
                evidence=(
                    Evidence(
                        quote="Launch conversion is 10%.",
                        source_block_id="block-1",
                        quote_start_char=0,
                        quote_end_char=25,
                    )
                    if field.name == "baseline"
                    else None
                ),
            )
            for field in criterion.fields
        ],
    )
    original = score(rubric, [[extraction]])

    evaluations = evaluations_from_legacy_extraction_run(
        rubric,
        [extraction],
        snapshot_id="a" * 64,
        plan_fingerprint="plan-1",
        run_index=1,
    )
    restored = legacy_extraction_run_from_evaluations(rubric, evaluations)
    round_trip = score(rubric, [restored])

    assert round_trip.model_dump() == original.model_dump()
    baseline = next(
        item for item in evaluations[0].claims if item.assertion_id == "baseline"
    )
    assert len(baseline.evidence_ids) == 1


def test_run_consolidation_keeps_conflicts_and_resolves_ties_to_unclear():
    rubric = load_rubric("prd")
    supported = verify_criterion_evaluation(
        _document(),
        rubric,
        _submission(),
        plan_fingerprint="plan-1",
        run_id="run-1",
        batch_ids=["batch-1"],
        coverage_complete=True,
    )
    unclear_submission = _submission().model_copy(
        update={"claims": [], "evidence_sets": [], "gaps": []}, deep=True
    )
    unclear = verify_criterion_evaluation(
        _document(),
        rubric,
        unclear_submission,
        plan_fingerprint="plan-1",
        run_id="run-2",
        batch_ids=["batch-1"],
        coverage_complete=True,
    )

    consolidated = consolidate_evaluation_runs(
        [supported, unclear], expected_run_count=3
    )

    assert consolidated.status.value == "unclear"
    assert consolidated.confidence.agreement == 0.5
    assert consolidated.confidence.run_count == 2
    assert len(consolidated.evidence) == 2


def test_bundled_rubric_exposes_versioned_evaluation_contracts():
    rubric = load_rubric("prd")

    for criterion in rubric.criteria:
        contract = criterion.evaluation
        assert contract is not None
        assert contract.version in {"1.0", "1.1"}
        assert all(item.answer_contract for item in contract.assertions if item.required)
        assert all(item.resolution_contract for item in contract.assertions if item.required)
        assert "placeholder" in " ".join(contract.hard_negatives).lower()

    problem = rubric.criterion("problem_statement").evaluation
    assert problem is not None
    assert problem.version == "1.1"
    assert problem.assertions[0].id == "problem"
    assert "opportunity" in problem.assertions[0].description

    functional = rubric.criterion("functional_requirements").evaluation
    assert functional is not None
    assert functional.version == "1.1"
    assert {
        item.id
        for item in functional.assertions
        if item.legacy_field == "prioritisation"
    } == {"must_have_requirement", "deferred_requirement"}

    dependencies = rubric.criterion("dependencies").evaluation
    assert dependencies is not None
    assert dependencies.version == "1.1"
    readiness_atoms = [
        item
        for item in dependencies.assertions
        if item.legacy_field == "dependency_readiness"
    ]
    assert {item.id for item in readiness_atoms} == {
        "dependency_owner",
        "readiness_proof",
        "freshness_or_availability",
        "unavailable_fallback",
    }
    assert all(
        item.prerequisite_assertion_ids == ["dependencies"]
        for item in readiness_atoms
    )

    operations = rubric.criterion("operational_readiness").evaluation
    assert operations is not None
    assert operations.version == "1.1"
    service_atoms = [
        item
        for item in operations.assertions
        if item.legacy_field == "service_expectations"
    ]
    assert {item.id for item in service_atoms} == {
        "availability_expectation",
        "latency_expectation",
        "capacity_expectation",
        "data_integrity_expectation",
        "recovery_expectation",
    }
    assert all(
        not item.prerequisite_assertion_ids for item in service_atoms
    )
    assert {item.id for item in operations.assertions if item.required} >= {
        "availability_expectation",
        "latency_expectation",
        "capacity_expectation",
        "data_integrity_expectation",
        "recovery_expectation",
        "monitoring_owner",
        "support_owner",
        "incident_response_owner",
        "diagnostic_method",
        "recovery_procedure",
    }
    assert operations.assertions[-1].id == "degraded_mode_or_restore"
    assert operations.assertions[-1].prerequisite_assertion_ids == [
        "diagnostic_method"
    ]

    rollout = rubric.criterion("rollout").evaluation
    assert rollout is not None
    assert rollout.version == "1.1"
    threshold_atoms = [
        item
        for item in rollout.assertions
        if item.legacy_field == "launch_and_stop_criteria"
    ]
    assert {item.id for item in threshold_atoms} == {
        "entry_criteria",
        "observation_window",
        "promotion_criteria",
        "pause_criteria",
        "stop_criteria",
    }
    promotion = next(item for item in rollout.assertions if item.id == "promotion_criteria")
    rollback = next(item for item in rollout.assertions if item.id == "rollback_procedure")
    assert promotion.prerequisite_assertion_ids == [
        "entry_criteria",
        "observation_window",
    ]
    assert rollback.prerequisite_assertion_ids == [
        "rollback_trigger"
    ]
    communication_atoms = [
        item
        for item in rollout.assertions
        if item.legacy_field == "support_and_communications"
    ]
    assert communication_atoms[0].id == "communication_impact_scope"
    assert all(
        item.prerequisite_assertion_ids == ["communication_impact_scope"]
        for item in communication_atoms[1:]
    )

    instrumentation = rubric.criterion("instrumentation").evaluation
    assert instrumentation is not None
    assert instrumentation.version == "1.1"
    event_atoms = [
        item
        for item in instrumentation.assertions
        if item.legacy_field == "events"
    ]
    assert {item.id for item in event_atoms} == {
        "event_declarations",
        "event_properties",
    }
    assert event_atoms[0].prerequisite_assertion_ids == [
        "metric_definition_reference"
    ]
    assert event_atoms[1].prerequisite_assertion_ids == ["event_declarations"]
    formula = next(
        item for item in instrumentation.assertions if item.id == "metric_formula"
    )
    assert formula.prerequisite_assertion_ids == [
        "event_declarations",
        "metric_definition_reference",
    ]
    diagnostic = next(
        item
        for item in instrumentation.assertions
        if item.id == "diagnostic_signal_use"
    )
    assert diagnostic.prerequisite_assertion_ids == ["failure_detection_signal"]

    acceptance = rubric.criterion("acceptance_criteria").evaluation
    assert acceptance is not None
    assert acceptance.version == "1.1"
    acceptance_subject = next(
        item for item in acceptance.assertions if item.id == "acceptance_subject"
    )
    assert acceptance_subject.legacy_field == "criteria"
    assert all(
        next(item for item in acceptance.assertions if item.id == assertion_id)
        .prerequisite_assertion_ids
        == ["acceptance_subject"]
        for assertion_id in ("completion_outcome", "pass_condition", "fail_condition")
    )
    criteria_atoms = [
        item
        for item in acceptance.assertions
        if item.legacy_field == "criteria"
    ]
    assert {item.id for item in criteria_atoms} == {
        "acceptance_subject",
        "completion_outcome",
        "pass_condition",
        "fail_condition",
    }
    mapping = next(
        item
        for item in acceptance.assertions
        if item.id == "requirement_case_mapping"
    )
    assert mapping.prerequisite_assertion_ids == [
        "launch_critical_requirement_set",
        "pass_condition",
        "fail_condition",
    ]
    boundary_mapping = next(
        item
        for item in acceptance.assertions
        if item.id == "boundary_case_mapping"
    )
    assert boundary_mapping.required is False
    assert boundary_mapping.prerequisite_assertion_ids == [
        "decision_rule_boundary_set",
        "failure_boundary_scope",
    ]
    completeness = next(
        item
        for item in acceptance.assertions
        if item.id == "coverage_completeness"
    )
    assert completeness.prerequisite_assertion_ids == [
        "requirement_case_mapping"
    ]

    edge_states = rubric.criterion("edge_cases_and_states").evaluation
    assert edge_states is not None
    assert edge_states.version == "1.1"
    assert {
        item.id
        for item in edge_states.assertions
        if item.legacy_field == "transitional_or_degraded_states"
    } == {
        "loading_applicability",
        "loading_behavior",
        "offline_applicability",
        "offline_behavior",
        "interruption_applicability",
        "interruption_behavior",
        "partial_completion_applicability",
        "partial_completion_behavior",
        "recovery_transition_applicability",
        "recovery_transition_behavior",
    }
    assert all(
        item.prerequisite_assertion_ids == [item.id.replace("_behavior", "_applicability")]
        for item in edge_states.assertions
        if item.id.endswith("_behavior")
        and item.legacy_field == "transitional_or_degraded_states"
    )
    accessibility = [
        item
        for item in edge_states.assertions
        if item.legacy_field == "accessibility_approach"
    ]
    assert [item.id for item in accessibility] == [
        "accessibility_standard",
        "accessibility_verification",
    ]
    assert accessibility[1].prerequisite_assertion_ids == [
        "accessibility_standard"
    ]

    open_questions = rubric.criterion("open_questions_owned").evaluation
    assert open_questions is not None
    assert open_questions.version == "1.1"
    assert [item.id for item in open_questions.assertions] == [
        "unresolved_decision_scope",
        "open_question",
        "open_question_owner",
        "open_question_deadline",
    ]
    assert open_questions.assertions[1].prerequisite_assertion_ids == [
        "unresolved_decision_scope"
    ]
    assert all(
        item.prerequisite_assertion_ids == ["open_question"]
        for item in open_questions.assertions[2:]
    )

    alternatives = rubric.criterion("alternatives_considered").evaluation
    assert alternatives is not None
    assert alternatives.version == "1.1"
    assert [item.id for item in alternatives.assertions] == [
        "alternative_scope",
        "considered_alternative",
        "alternative_disposition",
        "rejection_reason",
    ]
    assert alternatives.assertions[-1].prerequisite_assertion_ids == [
        "alternative_disposition"
    ]

    assumptions = rubric.criterion("assumptions_validation").evaluation
    assert assumptions is not None
    assert assumptions.version == "1.1"
    assert [item.id for item in assumptions.assertions] == [
        "material_assumption",
        "validation_path",
        "existing_validation_evidence",
        "validation_method",
        "validation_owner",
        "validation_timing",
    ]
    assert all(
        item.prerequisite_assertion_ids
        for item in assumptions.assertions
        if item.id != "material_assumption"
    )

    risk = rubric.criterion("risk_compliance").evaluation
    assert risk is not None
    assert risk.version == "1.1"
    assert risk.assertions[0].id == "sensitive_data_scope"
    assert all(
        not item.required for item in risk.assertions[1:]
        if item.legacy_field in {
            "data_handled",
            "purpose_and_minimisation",
            "access_and_third_parties",
        }
    )


def test_evaluation_contract_rejects_unknown_and_cyclic_prerequisites():
    contract = load_rubric("prd").criterion("dependencies").evaluation
    assert contract is not None
    unknown = contract.model_dump(mode="json")
    unknown["assertions"][1]["prerequisite_assertion_ids"] = ["missing"]
    with pytest.raises(ValidationError, match="unknown prerequisite"):
        CriterionEvaluationSpec.model_validate(unknown)

    cyclic = contract.model_dump(mode="json")
    cyclic["assertions"][0]["prerequisite_assertion_ids"] = [
        cyclic["assertions"][1]["id"]
    ]
    cyclic["assertions"][1]["prerequisite_assertion_ids"] = [
        cyclic["assertions"][0]["id"]
    ]
    with pytest.raises(ValidationError, match="prerequisite cycle"):
        CriterionEvaluationSpec.model_validate(cyclic)


def test_native_evaluation_derives_outcomes_for_atomic_assertions():
    rubric = load_rubric("prd")
    criterion = rubric.criterion("dependencies")
    submission = CriterionEvaluationSubmission(
        criterion_id=criterion.id,
        gaps=[
            SubmittedGap(
                gap_ref=f"gap-{assertion.id}",
                assertion_ids=[assertion.id],
                kind="missing_decision",
                missing_decision=assertion.resolution_contract,
            )
            for assertion in criterion.evaluation.assertions
        ],
    )

    evaluation = verify_criterion_evaluation(
        _document(), rubric, submission,
        plan_fingerprint="plan-1", run_id="run-1",
        batch_ids=["batch-1"], coverage_complete=True,
    )

    assert {item.assertion_id for item in evaluation.assertion_outcomes} == {
        item.id for item in criterion.evaluation.assertions
    }
    assert "dependency_readiness" not in {
        item.assertion_id for item in evaluation.assertion_outcomes
    }


def test_legacy_adapter_fans_composite_field_into_atomic_shadow_assertions():
    rubric = load_rubric("prd")
    criterion = rubric.criterion("dependencies")
    extraction = CriterionExtraction(
        criterion_id=criterion.id,
        fields=[
            FieldExtraction(
                name=field.name,
                value=("Ready" if field.name == "dependency_readiness" else None),
                evidence=(
                    Evidence(
                        quote="Launch conversion is 10%.",
                        source_block_id="block-1",
                    )
                    if field.name == "dependency_readiness"
                    else None
                ),
            )
            for field in criterion.fields
        ],
    )
    original = score(rubric, [[extraction]])

    evaluations = evaluations_from_legacy_extraction_run(
        rubric,
        [extraction],
        snapshot_id="a" * 64,
        plan_fingerprint="plan-1",
        run_index=1,
    )
    restored = legacy_extraction_run_from_evaluations(rubric, evaluations)

    assert score(rubric, [restored]).model_dump() == original.model_dump()
    assert {
        claim.assertion_id for claim in evaluations[0].claims
    } == {
        "dependency_owner",
        "readiness_proof",
        "freshness_or_availability",
        "unavailable_fallback",
    }


def test_operational_atomic_adapter_preserves_legacy_score_parity():
    rubric = load_rubric("prd")
    criterion = rubric.criterion("operational_readiness")
    extraction = CriterionExtraction(
        criterion_id=criterion.id,
        fields=[
            FieldExtraction(
                name=field.name,
                value=f"Defined {field.name}",
                evidence=Evidence(
                    quote="Launch conversion is 10%.",
                    source_block_id="block-1",
                ),
            )
            for field in criterion.fields
        ],
    )
    original = score(rubric, [[extraction]])

    evaluations = evaluations_from_legacy_extraction_run(
        rubric,
        [extraction],
        snapshot_id="a" * 64,
        plan_fingerprint="plan-1",
        run_index=1,
    )
    restored = legacy_extraction_run_from_evaluations(rubric, evaluations)

    assert score(rubric, [restored]).model_dump() == original.model_dump()
    assert {claim.assertion_id for claim in evaluations[0].claims} == {
        item.id for item in criterion.evaluation.assertions
    }


def test_rollout_atomic_adapter_preserves_legacy_score_parity():
    rubric = load_rubric("prd")
    criterion = rubric.criterion("rollout")
    extraction = CriterionExtraction(
        criterion_id=criterion.id,
        fields=[
            FieldExtraction(
                name=field.name,
                value=f"Defined {field.name}",
                evidence=Evidence(
                    quote="Launch conversion is 10%.",
                    source_block_id="block-1",
                ),
            )
            for field in criterion.fields
        ],
    )
    original = score(rubric, [[extraction]])

    evaluations = evaluations_from_legacy_extraction_run(
        rubric,
        [extraction],
        snapshot_id="a" * 64,
        plan_fingerprint="plan-1",
        run_index=1,
    )
    restored = legacy_extraction_run_from_evaluations(rubric, evaluations)

    assert score(rubric, [restored]).model_dump() == original.model_dump()
    assert {claim.assertion_id for claim in evaluations[0].claims} == {
        item.id for item in criterion.evaluation.assertions
    }


def test_instrumentation_atomic_adapter_preserves_legacy_score_parity():
    rubric = load_rubric("prd")
    criterion = rubric.criterion("instrumentation")
    extraction = CriterionExtraction(
        criterion_id=criterion.id,
        fields=[
            FieldExtraction(
                name=field.name,
                value=(
                    [f"Defined {field.name}"]
                    if field.type == "string[]"
                    else "Named playback_failure alert"
                    if field.name == "operational_signals"
                    else f"Defined {field.name}"
                ),
                evidence=Evidence(
                    quote=(
                        "Named playback_failure alert"
                        if field.name == "operational_signals"
                        else "Launch conversion is 10%."
                    ),
                    source_block_id="block-1",
                ),
            )
            for field in criterion.fields
        ],
    )
    original = score(rubric, [[extraction]])

    evaluations = evaluations_from_legacy_extraction_run(
        rubric,
        [extraction],
        snapshot_id="a" * 64,
        plan_fingerprint="plan-1",
        run_index=1,
    )
    restored = legacy_extraction_run_from_evaluations(rubric, evaluations)

    assert score(rubric, [restored]).model_dump() == original.model_dump()
    assert {claim.assertion_id for claim in evaluations[0].claims} == {
        item.id for item in criterion.evaluation.assertions
    }


def test_acceptance_atomic_adapter_preserves_gate_and_score_parity():
    rubric = load_rubric("prd")
    criterion = rubric.criterion("acceptance_criteria")
    extraction = CriterionExtraction(
        criterion_id=criterion.id,
        fields=[
            FieldExtraction(
                name=field.name,
                value=(
                    [
                        "The user sees a confirmation after completion."
                        if field.name == "criteria"
                        else "Invalid input shows an actionable error."
                    ]
                    if field.name in {"criteria", "failure_and_boundary_criteria"}
                    else None
                ),
                evidence=(
                    Evidence(
                        quote=(
                            "The user sees a confirmation after completion."
                            if field.name == "criteria"
                            else "Invalid input shows an actionable error."
                        ),
                        source_block_id="block-1",
                    )
                    if field.name in {"criteria", "failure_and_boundary_criteria"}
                    else None
                ),
            )
            for field in criterion.fields
        ],
    )
    original = score(rubric, [[extraction]])

    evaluations = evaluations_from_legacy_extraction_run(
        rubric,
        [extraction],
        snapshot_id="a" * 64,
        plan_fingerprint="plan-1",
        run_index=1,
    )
    restored = legacy_extraction_run_from_evaluations(rubric, evaluations)
    round_trip = score(rubric, [restored])

    assert round_trip.model_dump() == original.model_dump()
    result = next(
        item
        for item in original.criteria
        if item.criterion_id == "acceptance_criteria"
    )
    assert result.gate_triggered
    assert result.verdict.value == "partial"
    assert {
        gap.assertion_ids[0] for gap in evaluations[0].gaps
    } >= {
        "launch_critical_requirement_set",
        "requirement_case_mapping",
        "coverage_completeness",
    }


def test_evaluation_prompt_exposes_contract_without_scoring_authority():
    rubric = load_rubric("prd")
    criterion = rubric.criterion("success_metrics")

    prompt = build_criterion_evaluation_prompt(
        _document(),
        criterion,
        batch_id="batch-1",
        plan_fingerprint="plan-1",
        run_index=1,
    )

    assert "baseline" in prompt
    assert "measurement_window" in prompt
    assert "UNTRUSTED" in prompt
    assert "source_block_id" in prompt
    assert "global absence" in prompt
    assert "weight" not in prompt.lower()
    assert "caps_at" not in prompt
    assert "ready_to_build" not in prompt


def test_evaluation_parser_accepts_one_fence_and_rejects_extra_fields():
    payload = _submission().model_dump_json()

    parsed = parse_criterion_evaluation(f"```json\n{payload}\n```")

    assert parsed == _submission()
    invalid = _submission().model_dump()
    invalid["score"] = 1.0
    with pytest.raises(ValidationError):
        parse_criterion_evaluation(__import__("json").dumps(invalid))


def _empty_run():
    rubric = load_rubric("prd")
    return ExtractionRun(
        criteria=[
            CriterionExtraction(
                criterion_id=criterion.id,
                fields=[FieldExtraction(name=field.name) for field in criterion.fields],
            )
            for criterion in rubric.criteria
        ]
    )


def test_service_returns_shadow_evaluations_without_changing_score(tmp_path):
    source = tmp_path / "prd.md"
    source.write_text("An incomplete product note.")
    rubric = load_rubric("prd")
    run = _empty_run()

    response = assess_extractions(
        str(source), ExtractionBatch(runs=[run, run, run])
    )
    legacy = score(rubric, [run.criteria, run.criteria, run.criteria])

    assert response.assessment.model_dump() == legacy.model_dump()
    assert len(response.criterion_evaluations) == len(rubric.criteria)
    assert {item.status.value for item in response.criterion_evaluations} == {
        "unsupported"
    }
    assert all(item.confidence.run_count == 3 for item in response.criterion_evaluations)


def test_review_persists_immutable_evaluation_artifacts_across_restart(tmp_path):
    source = tmp_path / "prd.md"
    source.write_text("An incomplete product note.")
    extraction_json = _empty_run().model_dump_json()
    turn = begin_remediation(str(source), extraction_json)
    repository = ReviewSessionRepository(tmp_path / "reviews.sqlite3")

    created = repository.create(turn.state)
    reopened = ReviewSessionRepository(tmp_path / "reviews.sqlite3")
    artifacts = reopened.list_evaluation_artifacts(created.review_session_id)

    assert len(artifacts) == len(load_rubric("prd").criteria)
    assert all(item.snapshot_id == turn.state.snapshot_id for item in artifacts)
    assert all(item.plan_fingerprint == turn.state.plan_fingerprint for item in artifacts)
    assert all(item.origin == "legacy_field_adapter" for item in artifacts)


def test_fragment_consolidation_requires_full_coverage_and_keeps_every_span():
    rubric = load_rubric("prd")
    first = verify_criterion_evaluation(
        _document(),
        rubric,
        _submission(),
        plan_fingerprint="plan-1",
        run_id="run-1",
        batch_ids=["batch-1"],
        coverage_complete=False,
    )
    second_submission = _submission().model_copy(deep=True)
    second_submission.evidence = [
        EvidenceReference(
            ref_id="constraint",
            source_block_id="block-2",
            quote="finance requires 15%.",
        )
    ]
    second_submission.claims = [
        SubmittedClaim(
            claim_ref="constraint-claim",
            assertion_id="target",
            value="15%",
            evidence_refs=["constraint"],
        )
    ]
    second_submission.evidence_sets = [
        SubmittedEvidenceSet(
            evidence_set_ref="constraint-set",
            assertion_ids=["target"],
            claim_refs=["constraint-claim"],
            evidence_refs=["constraint"],
            relation=SupportRelation.CONTRADICTS,
        )
    ]
    second_submission.gaps = []
    second = verify_criterion_evaluation(
        _document(),
        rubric,
        second_submission,
        plan_fingerprint="plan-1",
        run_id="run-1",
        batch_ids=["batch-2"],
        coverage_complete=False,
    )

    with pytest.raises(ValueError, match="missing batch fragments"):
        consolidate_evaluation_fragments(
            [first], expected_batch_ids=["batch-1", "batch-2"]
        )

    consolidated = consolidate_evaluation_fragments(
        [first, second], expected_batch_ids=["batch-1", "batch-2"]
    )

    assert consolidated.coverage_complete
    assert len(consolidated.evidence) == 3
    assert {item.relation for item in consolidated.evidence_sets} == {
        SupportRelation.SUPPORTS,
        SupportRelation.CONTRADICTS,
    }


def test_prepared_evaluation_plan_and_batch_cover_every_criterion(tmp_path):
    source = tmp_path / "prd.md"
    source.write_text("An incomplete product note.")
    from forge.service import prepare_assessment

    prepared = prepare_assessment(str(source))
    plan = prepare_evaluation_plan(prepared)

    assert len(plan.items) == len(prepared.rubric.criteria) * len(prepared.batches)
    assert all(item.plan_fingerprint == prepared.plan_fingerprint for item in plan.items)
    submissions = [
        CriterionEvaluationSubmission(
            criterion_id=criterion.id,
            gaps=(
                [
                    SubmittedGap(
                        gap_ref="metric-gap",
                        assertion_ids=["primary_metric"],
                        kind="missing_decision",
                    )
                ]
                if criterion.id == "success_metrics"
                else []
            ),
        )
        for criterion in prepared.rubric.criteria
    ]
    payload = CriterionEvaluationBatch(
        runs=[
            CriterionEvaluationRun(
                run_index=index,
                fragments=[
                    CriterionEvaluationFragment(
                        batch_id=batch.id,
                        plan_fingerprint=prepared.plan_fingerprint,
                        criteria=submissions,
                    )
                    for batch in prepared.batches
                ],
            )
            for index in range(1, 4)
        ]
    )

    verified = verify_evaluation_batch(prepared, payload)

    assert len(verified.artifacts) == 3 * len(prepared.rubric.criteria)
    assert len(verified.consolidated) == len(prepared.rubric.criteria)
    assert {item.status for item in verified.consolidated} == {SemanticStatus.UNCLEAR}
    assert all(item.confidence.run_count == 3 for item in verified.consolidated)
    assert verified.question_generation is not None
    assert verified.question_generation.target.assertion_id == "primary_metric"


def test_exhaustive_all_gap_fragments_become_unsupported():
    rubric = load_rubric("prd")
    submission = CriterionEvaluationSubmission(
        criterion_id="success_metrics",
        gaps=[
            SubmittedGap(
                gap_ref="missing-metric",
                assertion_ids=["primary_metric"],
                kind="missing_decision",
            )
        ],
    )
    fragment = verify_criterion_evaluation(
        _document(),
        rubric,
        submission,
        plan_fingerprint="plan-1",
        run_id="run-1",
        batch_ids=["batch-1"],
        coverage_complete=False,
    )
    assert fragment.status is SemanticStatus.UNCLEAR

    consolidated = consolidate_evaluation_fragments(
        [fragment], expected_batch_ids=["batch-1"]
    )

    assert consolidated.coverage_complete
    assert consolidated.status is SemanticStatus.UNSUPPORTED


def test_run_consolidation_reconciles_assertions_before_criterion_status():
    rubric = load_rubric("prd")
    support_one = verify_criterion_evaluation(
        _document(),
        rubric,
        _submission(),
        plan_fingerprint="plan-1",
        run_id="run-1",
        batch_ids=["batch-1"],
        coverage_complete=True,
    )
    support_two = support_one.model_copy(
        update={
            "evaluation_id": "d" * 64,
            "run_ids": ["run-2"],
            "confidence": support_one.confidence.model_copy(),
        },
        deep=True,
    )
    for claim in support_two.claims:
        claim.run_ids = ["run-2"]
    for evidence_set in support_two.evidence_sets:
        evidence_set.run_ids = ["run-2"]
    conflict_submission = _submission().model_copy(deep=True)
    conflict_submission.evidence.append(
        EvidenceReference(
            ref_id="constraint",
            source_block_id="block-2",
            quote="finance requires 15%.",
        )
    )
    conflict_submission.contradictions.append(
        SubmittedContradiction(
            issue_ref="target-conflict",
            assertion_ids=["target"],
            left_evidence_refs=["target-evidence"],
            right_evidence_refs=["constraint"],
            relation="scoped_contradiction",
        )
    )
    conflict = verify_criterion_evaluation(
        _document(),
        rubric,
        conflict_submission,
        plan_fingerprint="plan-1",
        run_id="run-3",
        batch_ids=["batch-1"],
        coverage_complete=True,
    )

    consolidated = consolidate_evaluation_runs(
        [support_one, support_two, conflict],
        expected_run_count=3,
        criterion=rubric.criterion("success_metrics"),
    )

    target = next(
        item for item in consolidated.assertion_outcomes if item.assertion_id == "target"
    )
    assert target.status == "supported"
    assert target.agreement == pytest.approx(2 / 3)
    assert consolidated.status is SemanticStatus.UNCLEAR
    assert consolidated.status is not SemanticStatus.CONTRADICTORY
    assert consolidated.contradictions  # minority evidence remains auditable


def test_consolidated_contradiction_requires_majority_on_same_evidence_pair():
    base = verify_criterion_evaluation(
        _document(),
        load_rubric("prd"),
        _submission(),
        plan_fingerprint="plan-1",
        run_id="run-1",
        batch_ids=["batch-1"],
        coverage_complete=True,
    )

    def contradictory_run(
        run_index: int, issue_id: str, left_id: str, right_id: str
    ) -> CriterionEvaluation:
        return base.model_copy(
            update={
                "evaluation_id": str(run_index) * 64,
                "run_ids": [f"run-{run_index}"],
                "status": SemanticStatus.CONTRADICTORY,
                "contradictions": [
                    EvaluationContradiction(
                        issue_id=issue_id,
                        assertion_ids=["target"],
                        left_evidence_ids=[left_id],
                        right_evidence_ids=[right_id],
                        relation="precedence_conflict",
                        run_ids=[f"run-{run_index}"],
                    )
                ],
                "assertion_outcomes": [
                    AssertionOutcome(
                        assertion_id="target",
                        status="contradictory",
                        agreement=1,
                        run_count=1,
                        issue_ids=[issue_id],
                    )
                ],
            },
            deep=True,
        )

    singleton = contradictory_run(1, "6" * 64, "a" * 64, "b" * 64)
    majority_one = contradictory_run(2, "7" * 64, "c" * 64, "d" * 64)
    majority_two = contradictory_run(3, "8" * 64, "d" * 64, "c" * 64)

    consolidated = consolidate_evaluation_runs(
        [singleton, majority_one, majority_two],
        expected_run_count=3,
        criterion=load_rubric("prd").criterion("success_metrics"),
    )

    target = next(
        item for item in consolidated.assertion_outcomes if item.assertion_id == "target"
    )
    assert target.status == "contradictory"
    assert target.agreement == 1
    assert target.issue_ids == ["7" * 64]
    assert {item.issue_id for item in consolidated.contradictions} == {
        "6" * 64,
        "7" * 64,
        "8" * 64,
    }


def test_semantic_record_identity_ignores_model_claim_wording():
    rubric = load_rubric("prd")
    first_submission = _submission()
    second_submission = _submission().model_copy(deep=True)
    second_submission.claims[0].value = "Current launch conversion: ten percent"
    second_submission.claims[1].value = "Twenty percent target"

    first = verify_criterion_evaluation(
        _document(),
        rubric,
        first_submission,
        plan_fingerprint="plan-1",
        run_id="run-1",
        batch_ids=["batch-1"],
        coverage_complete=True,
    )
    second = verify_criterion_evaluation(
        _document(),
        rubric,
        second_submission,
        plan_fingerprint="plan-1",
        run_id="run-2",
        batch_ids=["batch-1"],
        coverage_complete=True,
    )

    assert first.claims[0].claim_id != second.claims[0].claim_id
    assert first.evidence_sets[0].evidence_set_id == second.evidence_sets[0].evidence_set_id


def test_ambiguity_identity_ignores_alternative_wording():
    rubric = load_rubric("prd")
    first_submission = _submission()
    first_submission.ambiguities.append(
        SubmittedAmbiguity(
            issue_ref="a1",
            assertion_ids=["target"],
            evidence_refs=["target-evidence"],
            alternatives=["Target is mandatory", "Target is aspirational"],
        )
    )
    second_submission = first_submission.model_copy(deep=True)
    second_submission.ambiguities[0].alternatives = [
        "A committed target",
        "Only a desired target",
    ]

    first = verify_criterion_evaluation(
        _document(), rubric, first_submission,
        plan_fingerprint="plan-1", run_id="run-1",
        batch_ids=["batch-1"], coverage_complete=True,
    )
    second = verify_criterion_evaluation(
        _document(), rubric, second_submission,
        plan_fingerprint="plan-1", run_id="run-2",
        batch_ids=["batch-1"], coverage_complete=True,
    )

    assert first.ambiguities[0].issue_id == second.ambiguities[0].issue_id


def test_assertion_outcome_references_only_issues_for_its_selected_status():
    submission = _submission()
    submission.gaps.append(
        SubmittedGap(
            gap_ref="target-gap",
            assertion_ids=["target"],
            kind="missing_decision",
        )
    )
    submission.ambiguities.append(
        SubmittedAmbiguity(
            issue_ref="target-ambiguity",
            assertion_ids=["target"],
            evidence_refs=["target-evidence"],
            alternatives=["Committed target", "Aspirational target"],
        )
    )

    evaluation = verify_criterion_evaluation(
        _document(),
        load_rubric("prd"),
        submission,
        plan_fingerprint="plan-1",
        run_id="run-1",
        batch_ids=["batch-1"],
        coverage_complete=True,
    )

    target = next(
        item for item in evaluation.assertion_outcomes if item.assertion_id == "target"
    )
    assert target.status == "ambiguous"
    assert target.issue_ids == [evaluation.ambiguities[0].issue_id]
    assert evaluation.gaps[1].gap_id not in target.issue_ids


def test_gap_retains_bounded_missing_decision_without_changing_semantic_identity():
    first_submission = CriterionEvaluationSubmission(
        criterion_id="success_metrics",
        gaps=[
            SubmittedGap(
                gap_ref="metric-gap",
                assertion_ids=["primary_metric"],
                kind="missing_decision",
                missing_decision="Name the single outcome metric to optimize.",
            )
        ],
    )
    second_submission = first_submission.model_copy(deep=True)
    second_submission.gaps[0].missing_decision = (
        "Decide which one metric determines whether the launch worked."
    )

    first = verify_criterion_evaluation(
        _document(), load_rubric("prd"), first_submission,
        plan_fingerprint="plan-1", run_id="run-1",
        batch_ids=["batch-1"], coverage_complete=True,
    )
    second = verify_criterion_evaluation(
        _document(), load_rubric("prd"), second_submission,
        plan_fingerprint="plan-1", run_id="run-2",
        batch_ids=["batch-1"], coverage_complete=True,
    )

    assert first.gaps[0].gap_id == second.gaps[0].gap_id
    assert first.gaps[0].missing_decisions == [
        "Name the single outcome metric to optimize."
    ]
    consolidated = consolidate_evaluation_runs(
        [first, second],
        expected_run_count=2,
        criterion=load_rubric("prd").criterion("success_metrics"),
    )
    assert consolidated.gaps[0].missing_decisions == [
        "Decide which one metric determines whether the launch worked.",
        "Name the single outcome metric to optimize.",
    ]
