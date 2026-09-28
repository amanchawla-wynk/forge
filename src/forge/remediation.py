from __future__ import annotations

import hashlib
import json
import uuid

from pydantic import BaseModel, Field

from forge.deep_review import (
    ClaimOccurrence,
    DeepReviewReport,
    build_deep_review,
    claim_occurrences,
    mechanical_claim_occurrences,
)
from forge.evaluate.models import CriterionEvaluation
from forge.extract.batch import (
    ExtractionBatch,
    verify_extraction_batch_with_claims,
)
from forge.extract.delta import (
    DeltaExtractionPlan,
    PendingDeltaAnswer,
    build_delta_extraction_plan,
    merge_criterion_patches,
    parse_delta_extraction,
    verify_delta_extraction,
)
from forge.extract.models import CriterionExtraction
from forge.ingest.adapters import LocalFileSourceAdapter, SourceRef
from forge.ingest.models import ProductContextTerm, SupplementalAnswer
from forge.ingest.snapshot import DocumentSnapshot
from forge.rubric.loader import load_rubric
from forge.revise import RevisionPlan
from forge.score.edge_coverage import (
    CoverageStatus,
    EdgeCaseCoverageLedger,
    apply_coverage_answers,
    edge_case_type,
    render_coverage_question,
    verify_coverage_ledger,
)
from forge.score.engine import Assessment, score
from forge.score.planner import Question, document_display_name, plan_question_queue
from forge.score.report import NarrativeReport, build_narrative_report
from forge.service import (
    AssessmentResponse,
    PreparedAssessmentInput,
    build_legacy_criterion_evaluations,
    prepare_assessment,
    prepare_assessment_input,
)


class CheckpointPolicy(BaseModel):
    max_pending_answers: int = Field(default=5, ge=1, le=20)


class FinalVerification(BaseModel):
    artifact_path: str
    artifact_sha256: str
    operation_id: str
    rubric_id: str
    rubric_version: str
    supplemental_answer_count: int = 0
    assessment: AssessmentResponse


class RemediationState(BaseModel):
    state_schema_version: int = 3
    source_path: str
    source_sha256: str
    snapshot_id: str | None = None
    parser_fingerprint: str | None = None
    normalized_hash: str | None = None
    plan_fingerprint: str | None = None
    source_snapshot: DocumentSnapshot | None = Field(default=None, exclude=True)
    criterion_evaluations: list[CriterionEvaluation] = Field(
        default_factory=list, exclude=True
    )
    rubric_name: str = "prd"
    rubric_id: str
    rubric_version: str
    baseline_fingerprint: str
    runs: list[list[CriterionExtraction]]
    assessment: Assessment
    report: NarrativeReport
    deep_review: DeepReviewReport | None = None
    question_queue: list[Question]
    verified_answers: list[SupplementalAnswer] = Field(default_factory=list)
    pending_answers: list[PendingDeltaAnswer] = Field(default_factory=list)
    uncredited_answers: list[SupplementalAnswer] = Field(default_factory=list)
    product_context: list[ProductContextTerm] = Field(default_factory=list)
    framing: str | None = None
    display_name: str
    edge_case_coverage: EdgeCaseCoverageLedger | None = None
    run_count: int
    expected_run_count: int
    client_models: list[str] = Field(default_factory=list)
    revision: int = 0
    evaluation_revision: int = 0
    delta_extraction_count: int = 0
    delta_input_characters: int = 0
    checkpoint_policy: CheckpointPolicy = Field(default_factory=CheckpointPolicy)
    revision_plan: RevisionPlan | None = None
    revision_output_path: str | None = None
    revision_output_sha256: str | None = None
    final_verification: FinalVerification | None = None


class RemediationTurn(BaseModel):
    state: RemediationState
    next_question: Question | None
    checkpoint_due: bool
    checkpoint_reason: str | None
    pending_answer_count: int
    verified_answer_count: int
    score_is_current: bool


class RemediationCheckpointResult(BaseModel):
    state: RemediationState
    next_question: Question | None
    credited_answer_ids: list[str]
    uncredited_answer_ids: list[str]
    previous_band: str
    current_band: str


def _baseline_fingerprint(
    source_sha256: str,
    snapshot_id: str,
    parser_fingerprint: str,
    normalized_hash: str,
    rubric_id: str,
    rubric_version: str,
    product_context: list[ProductContextTerm],
) -> str:
    digest = hashlib.sha256()
    digest.update(b"forge-remediation-baseline/v2")
    digest.update(b"\x00")
    digest.update(source_sha256.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(snapshot_id.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(parser_fingerprint.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(normalized_hash.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(rubric_id.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(rubric_version.encode("utf-8"))
    for term in product_context:
        digest.update(b"\x00context\x00")
        digest.update(term.model_dump_json().encode("utf-8"))
    return digest.hexdigest()[:32]


def assert_current_source(
    state: RemediationState, source_path: str | None = None
) -> None:
    path = source_path or state.source_path
    artifact = LocalFileSourceAdapter().acquire(SourceRef.local_file(path))
    if artifact.sha256 != state.source_sha256:
        raise ValueError(
            "the source PRD changed after remediation began; start a new assessment"
        )
    snapshot = state.source_snapshot
    identity = (state.snapshot_id, state.parser_fingerprint, state.normalized_hash)
    if any(value is not None for value in identity):
        if snapshot is None:
            raise ValueError("review session is missing its exact source snapshot")
        if (
            snapshot.snapshot_id != state.snapshot_id
            or snapshot.parser_fingerprint != state.parser_fingerprint
            or snapshot.normalized_hash != state.normalized_hash
            or snapshot.source.sha256 != state.source_sha256
            or snapshot.source.source_type != artifact.source_type
        ):
            raise ValueError("review session source snapshot identity does not match")
    rubric = load_rubric(state.rubric_name)
    if rubric.id != state.rubric_id or rubric.version != state.rubric_version:
        raise ValueError(
            "the rubric changed after remediation began; start a new assessment"
        )


def _decorate_edge_questions(
    queue: list[Question],
    assessment: Assessment,
    display_name: str,
    coverage: EdgeCaseCoverageLedger | None,
) -> None:
    if coverage is None:
        return
    uncovered = [
        item
        for status in (CoverageStatus.MISSING, CoverageStatus.UNCLEAR)
        for item in coverage.items
        if item.status is status
    ]
    if not uncovered:
        return
    result = next(
        item
        for item in assessment.criteria
        if item.criterion_id == "edge_cases_and_states"
    )
    existing_indexes = [
        index
        for index, question in enumerate(queue)
        if question.criterion_id == result.criterion_id
    ]
    insertion_index = existing_indexes[0] if existing_indexes else len(queue)
    queue[:] = [
        question
        for question in queue
        if question.criterion_id != result.criterion_id
    ]
    coverage_questions: list[Question] = []
    for item in uncovered:
        edge = edge_case_type(item.edge_case_id)
        coverage_questions.append(
            Question(
                criterion_id=result.criterion_id,
                criterion_name=result.name,
                target_field="edge_case_coverage",
                question=render_coverage_question(display_name, item),
                base_question=edge.question,
                missing_fields=result.missing,
                answer_requirements=[
                    "State the expected behavior for this requirement and edge case, "
                    "including the user-visible result and recovery path."
                ],
                is_gate=result.gate_triggered,
                band_if_answered=assessment.band,
                unblocks_consumers=[consumer.value for consumer in result.consumers],
                requirement_quote=item.requirement_quote,
                edge_case_id=item.edge_case_id,
                taxonomy_version=coverage.taxonomy_version,
                evaluation_revision=assessment.evaluation_revision,
            )
        )
    queue[insertion_index:insertion_index] = coverage_questions
    priority = {
        result.criterion_id: index
        for index, result in enumerate(
            sorted(
                (
                    item
                    for item in assessment.criteria
                    if item.verdict.value in {"absent", "partial"}
                ),
                key=lambda item: (
                    not item.gate_triggered,
                    -item.weight,
                    -len(item.consumers),
                    item.criterion_id,
                ),
            )
        )
    }
    queue.sort(key=lambda question: priority.get(question.criterion_id, len(priority)))


def _current_claims(
    state: RemediationState,
    patches: list[CriterionExtraction],
    document,
) -> list[ClaimOccurrence]:
    claims = list(state.deep_review.claims if state.deep_review else [])
    delta_claims = claim_occurrences(
        patches,
        run_index=0,
        batch_id=f"remediation-delta-{state.evaluation_revision + 1}",
    )
    for claim in delta_claims:
        claim.run_indexes = []
    claims.extend(delta_claims)
    claims.extend(mechanical_claim_occurrences(document, claims))
    return claims


def _snapshot(
    state: RemediationState,
    runs: list[list[CriterionExtraction]],
    verified_answers: list[SupplementalAnswer],
    coverage: EdgeCaseCoverageLedger | None,
    remediated_criteria: list[str],
    remediation_delta_count: int,
    delta_patches: list[CriterionExtraction],
) -> tuple[
    Assessment,
    NarrativeReport,
    DeepReviewReport,
    list[Question],
    EdgeCaseCoverageLedger | None,
]:
    rubric = load_rubric(state.rubric_name)
    document, _ = prepare_assessment_input(
        state.source_path,
        state.rubric_name,
        verified_answers,
        state.product_context,
        snapshot=state.source_snapshot,
    )
    verified_coverage = (
        verify_coverage_ledger(
            document,
            apply_coverage_answers(coverage, verified_answers),
        )
        if coverage is not None
        else None
    )
    assessment = score(rubric, runs, edge_case_coverage=verified_coverage)
    evaluation_revision = state.evaluation_revision + 1
    assessment.evaluation_revision = evaluation_revision
    previous_agreement = {
        result.criterion_id: result.agreement
        for result in state.assessment.criteria
    }
    for result in assessment.criteria:
        if result.criterion_id in remediated_criteria:
            result.agreement = previous_agreement.get(result.criterion_id, result.agreement)
            result.agreement_basis = "source_before_remediation"
    assessment.confidence = round(
        sum(result.agreement for result in assessment.criteria)
        / len(assessment.criteria),
        4,
    )
    assessment.confidence_basis = "source_runs_plus_single_verified_deltas"
    assessment.remediated_criteria = remediated_criteria
    assessment.remediation_delta_count = remediation_delta_count
    queue = plan_question_queue(
        rubric,
        assessment,
        display_name=state.display_name,
        framing=state.framing,
    )
    for question in queue:
        question.evaluation_revision = evaluation_revision
    _decorate_edge_questions(queue, assessment, state.display_name, verified_coverage)
    report = build_narrative_report(
        assessment,
        queue[:1],
        run_count=len(runs),
        expected_run_count=rubric.extraction_runs,
    )
    report.evaluation_revision = evaluation_revision
    deep_review = build_deep_review(
        rubric,
        _current_claims(
            state,
            delta_patches,
            document,
        ),
    )
    deep_review.evaluation_revision = evaluation_revision
    return assessment, report, deep_review, queue, verified_coverage


def begin_remediation(
    source_path: str,
    extraction_json: str,
    *,
    rubric_name: str = "prd",
    product_context: list[ProductContextTerm] | None = None,
    framing: str | None = None,
    edge_case_coverage: EdgeCaseCoverageLedger | None = None,
    client_models: list[str] | None = None,
    display_name: str | None = None,
    checkpoint_policy: CheckpointPolicy | None = None,
) -> RemediationTurn:
    prepared = prepare_assessment(
        source_path,
        rubric_name,
        [],
        product_context,
    )
    return begin_remediation_prepared(
        prepared,
        extraction_json,
        framing=framing,
        edge_case_coverage=edge_case_coverage,
        client_models=client_models,
        display_name=display_name,
        checkpoint_policy=checkpoint_policy,
    )


def begin_remediation_prepared(
    prepared: PreparedAssessmentInput,
    extraction_json: str,
    *,
    framing: str | None = None,
    edge_case_coverage: EdgeCaseCoverageLedger | None = None,
    client_models: list[str] | None = None,
    display_name: str | None = None,
    checkpoint_policy: CheckpointPolicy | None = None,
) -> RemediationTurn:
    document = prepared.document
    rubric = prepared.rubric
    terms = list(prepared.product_context)
    payload = json.loads(extraction_json)
    if "runs" not in payload:
        payload = {"runs": [payload]}
    runs, claims = verify_extraction_batch_with_claims(
        list(prepared.batches), ExtractionBatch.model_validate(payload), rubric
    )
    evaluation_artifacts, _ = build_legacy_criterion_evaluations(prepared, runs)
    source_sha = prepared.snapshot.source.sha256
    resolved_display_name = display_name or document_display_name(document.source_path)
    verified_coverage = (
        verify_coverage_ledger(document, edge_case_coverage)
        if edge_case_coverage is not None
        else None
    )
    assessment = score(rubric, runs, edge_case_coverage=verified_coverage)
    assessment.evaluation_revision = 0
    claims.extend(mechanical_claim_occurrences(document, claims))
    queue = plan_question_queue(
        rubric,
        assessment,
        display_name=resolved_display_name,
        framing=framing,
    )
    _decorate_edge_questions(queue, assessment, resolved_display_name, verified_coverage)
    report = build_narrative_report(
        assessment,
        queue[:1],
        run_count=len(runs),
        expected_run_count=rubric.extraction_runs,
    )
    report.evaluation_revision = 0
    deep_review = build_deep_review(rubric, claims)
    deep_review.evaluation_revision = 0
    state = RemediationState(
        source_path=document.source_path,
        source_sha256=source_sha,
        snapshot_id=prepared.snapshot.snapshot_id,
        parser_fingerprint=prepared.snapshot.parser_fingerprint,
        normalized_hash=prepared.snapshot.normalized_hash,
        plan_fingerprint=prepared.plan_fingerprint,
        source_snapshot=prepared.snapshot,
        criterion_evaluations=evaluation_artifacts,
        rubric_name=prepared.rubric_name,
        rubric_id=rubric.id,
        rubric_version=rubric.version,
        baseline_fingerprint=_baseline_fingerprint(
            source_sha,
            prepared.snapshot.snapshot_id,
            prepared.snapshot.parser_fingerprint,
            prepared.snapshot.normalized_hash,
            rubric.id,
            rubric.version,
            terms,
        ),
        runs=runs,
        assessment=assessment,
        deep_review=deep_review,
        report=report,
        question_queue=queue,
        verified_answers=list(prepared.supplemental_answers),
        product_context=terms,
        framing=queue[0].framing if queue else rubric.default_framing,
        display_name=resolved_display_name,
        edge_case_coverage=verified_coverage,
        run_count=len(runs),
        expected_run_count=rubric.extraction_runs,
        client_models=client_models or [],
        checkpoint_policy=checkpoint_policy or CheckpointPolicy(),
    )
    return _turn(state)


def _checkpoint_reason(state: RemediationState) -> str | None:
    if state.pending_answers and not state.question_queue:
        return "queue_exhausted"
    if len(state.pending_answers) >= state.checkpoint_policy.max_pending_answers:
        return "pending_limit"
    pending_by_criterion: dict[str, set[str]] = {}
    for pending in state.pending_answers:
        if pending.target_field is not None:
            pending_by_criterion.setdefault(
                pending.answer.criterion_id, set()
            ).add(pending.target_field)
    for result in state.assessment.criteria:
        if not result.gate_triggered:
            continue
        if set(result.missing).issubset(
            pending_by_criterion.get(result.criterion_id, set())
        ):
            return "failed_gate_fields_collected"
    return None


def _turn(
    state: RemediationState,
    *,
    forced_reason: str | None = None,
) -> RemediationTurn:
    reason = forced_reason or _checkpoint_reason(state)
    return RemediationTurn(
        state=state,
        next_question=None if reason else (state.question_queue[0] if state.question_queue else None),
        checkpoint_due=reason is not None,
        checkpoint_reason=reason,
        pending_answer_count=len(state.pending_answers),
        verified_answer_count=len(state.verified_answers),
        score_is_current=not state.pending_answers,
    )


def current_turn(state: RemediationState) -> RemediationTurn:
    """Re-derive the current turn from durable state, with no model work.

    Used when a session is loaded from storage: workflow state and the next
    question are recomputed from the persisted state rather than stored
    separately, so they can never drift from the verified assessment.
    """
    return _turn(state)


def record_answer(
    state: RemediationState,
    answer: str,
    *,
    force_checkpoint: bool = False,
) -> RemediationTurn:
    assert_current_source(state)
    if not state.question_queue:
        raise ValueError("no remediation question remains")
    question = state.question_queue[0]
    answer_id = uuid.uuid4().hex
    supplemental = SupplementalAnswer(
        answer_id=answer_id,
        criterion_id=question.criterion_id,
        answer=answer,
        requirement_quote=question.requirement_quote,
        edge_case_id=question.edge_case_id,
        taxonomy_version=question.taxonomy_version,
    )
    pending = PendingDeltaAnswer(
        answer_id=answer_id,
        target_field=question.target_field,
        answer=supplemental,
    )
    updated = state.model_copy(deep=True)
    updated.pending_answers.append(pending)
    updated.question_queue.pop(0)
    return _turn(updated, forced_reason="explicit" if force_checkpoint else None)


def prepare_checkpoint(state: RemediationState) -> DeltaExtractionPlan:
    assert_current_source(state)
    rubric = load_rubric(state.rubric_name)
    return build_delta_extraction_plan(
        state.baseline_fingerprint,
        rubric,
        state.pending_answers,
        state.runs[0],
    )


def apply_checkpoint(
    state: RemediationState,
    delta_json: str,
) -> RemediationCheckpointResult:
    assert_current_source(state)
    plan = prepare_checkpoint(state)
    rubric = load_rubric(state.rubric_name)
    delta = parse_delta_extraction(delta_json)
    patches = verify_delta_extraction(plan, delta, rubric, state.pending_answers)
    affected_criteria = list(dict.fromkeys(patch.criterion_id for patch in patches))
    runs = merge_criterion_patches(state.runs, patches)
    credited_block_ids = {
        field.evidence.source_block_id
        for patch in patches
        for field in patch.fields
        if field.evidence is not None and field.evidence.source_block_id is not None
    }
    credited = [
        pending
        for pending in state.pending_answers
        if (
            f"supplemental-answer-{pending.answer_id}" in credited_block_ids
            or (
                pending.answer.requirement_quote is not None
                and pending.answer.edge_case_id is not None
                and pending.answer.taxonomy_version is not None
            )
        )
    ]
    uncredited = [
        pending
        for pending in state.pending_answers
        if pending not in credited
    ]
    verified_answers = [
        *state.verified_answers,
        *(pending.answer for pending in credited),
    ]
    assessment, report, deep_review, queue, coverage = _snapshot(
        state,
        runs,
        verified_answers,
        state.edge_case_coverage,
        list(dict.fromkeys([*state.assessment.remediated_criteria, *affected_criteria])),
        state.delta_extraction_count + 1,
        patches,
    )
    updated = state.model_copy(
        update={
            "runs": runs,
            "assessment": assessment,
            "report": report,
            "deep_review": deep_review,
            "question_queue": queue,
            "verified_answers": verified_answers,
            "pending_answers": [],
            "uncredited_answers": [
                *state.uncredited_answers,
                *(pending.answer for pending in uncredited),
            ],
            "edge_case_coverage": coverage,
            "revision": state.revision + 1,
            "evaluation_revision": state.evaluation_revision + 1,
            "delta_extraction_count": state.delta_extraction_count + 1,
            "delta_input_characters": (
                state.delta_input_characters + plan.input_character_count
            ),
        },
        deep=True,
    )
    return RemediationCheckpointResult(
        state=updated,
        next_question=queue[0] if queue else None,
        credited_answer_ids=[pending.answer_id for pending in credited],
        uncredited_answer_ids=[pending.answer_id for pending in uncredited],
        previous_band=state.assessment.band,
        current_band=assessment.band,
    )
