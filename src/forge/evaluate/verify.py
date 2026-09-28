from __future__ import annotations

import hashlib
import json

from forge.evaluate.models import (
    Applicability,
    AssertionOutcome,
    CriterionEvaluation,
    CriterionEvaluationSubmission,
    EvaluationAmbiguity,
    EvaluationClaim,
    EvaluationConfidence,
    EvaluationContradiction,
    EvaluationGap,
    EvidenceSet,
    EvidenceSpan,
    SemanticStatus,
    SupportRelation,
)
from forge.ingest.models import NormalizedDocument, SourceBlock
from forge.rubric.models import Criterion, Rubric


def _hash(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {label}")


def _assertions(criterion: Criterion, values: list[str]) -> None:
    assert criterion.evaluation is not None
    unknown = sorted(
        set(values) - {assertion.id for assertion in criterion.evaluation.assertions}
    )
    if unknown:
        raise ValueError("unknown assertion ids: " + ", ".join(unknown))


def _locate(block: SourceBlock, quote: str, start: int | None, end: int | None) -> tuple[int, int]:
    if (start is None) != (end is None):
        raise ValueError("quote offsets must be supplied together")
    if start is not None and end is not None:
        if end <= start or block.text[start:end] != quote:
            raise ValueError("quote offsets do not match the named source block")
        return start, end
    matches: list[int] = []
    offset = 0
    while True:
        found = block.text.find(quote, offset)
        if found < 0:
            break
        matches.append(found)
        offset = found + 1
    if not matches:
        raise ValueError("quote does not occur in the named source block")
    if len(matches) > 1:
        raise ValueError("repeated quote requires exact quote offsets")
    return matches[0], matches[0] + len(quote)


def _status(
    criterion: Criterion,
    applicability: Applicability,
    evidence_sets: list[EvidenceSet],
    gaps: list[EvaluationGap],
    ambiguities: list[EvaluationAmbiguity],
    contradictions: list[EvaluationContradiction],
    coverage_complete: bool,
) -> SemanticStatus:
    if applicability is Applicability.NOT_APPLICABLE:
        return (
            SemanticStatus.NOT_APPLICABLE
            if criterion.allow_not_applicable
            else SemanticStatus.UNSUPPORTED
        )
    if contradictions:
        return SemanticStatus.CONTRADICTORY
    if ambiguities or applicability is Applicability.UNCLEAR:
        return SemanticStatus.UNCLEAR
    supported = {
        assertion
        for item in evidence_sets
        if item.relation is SupportRelation.SUPPORTS
        for assertion in item.assertion_ids
    }
    assert criterion.evaluation is not None
    required = {
        assertion.id
        for assertion in criterion.evaluation.assertions
        if assertion.required
    }
    if required and required.issubset(supported) and not gaps:
        return SemanticStatus.SUPPORTED
    if supported:
        return SemanticStatus.PARTIAL
    if coverage_complete and gaps:
        return SemanticStatus.UNSUPPORTED
    return SemanticStatus.UNCLEAR


def derive_assertion_outcomes(
    criterion: Criterion,
    evidence_sets: list[EvidenceSet],
    gaps: list[EvaluationGap],
    ambiguities: list[EvaluationAmbiguity],
    contradictions: list[EvaluationContradiction],
    *,
    coverage_complete: bool,
) -> list[AssertionOutcome]:
    outcomes: list[AssertionOutcome] = []
    assert criterion.evaluation is not None
    for assertion in criterion.evaluation.assertions:
        contradiction_ids = [
            issue.issue_id
            for issue in contradictions
            if assertion.id in issue.assertion_ids
        ]
        ambiguity_ids = [
            issue.issue_id
            for issue in ambiguities
            if assertion.id in issue.assertion_ids
        ]
        supporting = [
            evidence_set
            for evidence_set in evidence_sets
            if assertion.id in evidence_set.assertion_ids
            and evidence_set.relation is SupportRelation.SUPPORTS
        ]
        gap_ids = [
            gap.gap_id for gap in gaps if assertion.id in gap.assertion_ids
        ]
        if contradiction_ids:
            status = "contradictory"
            selected_issue_ids = contradiction_ids
        elif ambiguity_ids:
            status = "ambiguous"
            selected_issue_ids = ambiguity_ids
        elif supporting:
            status = "supported"
            selected_issue_ids = []
        elif gap_ids and coverage_complete:
            status = "gap"
            selected_issue_ids = gap_ids
        else:
            status = "unclear"
            selected_issue_ids = []
        outcomes.append(
            AssertionOutcome(
                assertion_id=assertion.id,
                status=status,
                agreement=1.0,
                run_count=1,
                evidence_ids=sorted(
                    {
                        evidence_id
                        for evidence_set in supporting
                        for evidence_id in evidence_set.evidence_ids
                    }
                ),
                issue_ids=sorted(selected_issue_ids),
            )
        )
    return outcomes


def verify_criterion_evaluation(
    document: NormalizedDocument,
    rubric: Rubric,
    submission: CriterionEvaluationSubmission,
    *,
    plan_fingerprint: str,
    run_id: str,
    batch_ids: list[str],
    coverage_complete: bool,
) -> CriterionEvaluation:
    if document.snapshot_id is None:
        raise ValueError("criterion evaluation requires snapshot identity")
    criterion = rubric.criterion(submission.criterion_id)
    _unique([item.ref_id for item in submission.evidence], "evidence refs")
    _unique([item.claim_ref for item in submission.claims], "claim refs")
    _unique(
        [item.evidence_set_ref for item in submission.evidence_sets],
        "evidence set refs",
    )
    blocks = {block.id: block for block in document.blocks}
    spans_by_ref: dict[str, EvidenceSpan] = {}
    for reference in submission.evidence:
        block = blocks.get(reference.source_block_id)
        if block is None:
            raise ValueError(f"unknown source block {reference.source_block_id!r}")
        if (
            block.provenance == "supplemental_answer"
            and block.criterion_id != criterion.id
        ):
            raise ValueError("supplemental evidence belongs to another criterion")
        local_start, local_end = _locate(
            block,
            reference.quote,
            reference.quote_start_char,
            reference.quote_end_char,
        )
        absolute_start = (block.start_char or 0) + local_start
        absolute_end = (block.start_char or 0) + local_end
        source_identity = block.parent_id or block.id
        evidence_id = _hash(
            {
                "snapshot_id": document.snapshot_id,
                "source_identity": source_identity,
                "start_char": absolute_start,
                "end_char": absolute_end,
                "provenance": block.provenance,
                "quote": reference.quote,
            }
        )
        spans_by_ref[reference.ref_id] = EvidenceSpan(
            evidence_id=evidence_id,
            snapshot_id=document.snapshot_id,
            source_block_id=block.id,
            source_parent_block_id=block.parent_id,
            start_char=absolute_start,
            end_char=absolute_end,
            exact_quote=reference.quote,
            provenance=block.provenance,
            page=block.page,
            section=block.section,
        )

    def evidence_ids(refs: list[str]) -> list[str]:
        unknown = sorted(set(refs) - set(spans_by_ref))
        if unknown:
            raise ValueError("unknown evidence refs: " + ", ".join(unknown))
        return [spans_by_ref[ref].evidence_id for ref in refs]

    claims_by_ref: dict[str, EvaluationClaim] = {}
    for claim in submission.claims:
        _assertions(criterion, [claim.assertion_id])
        ids = evidence_ids(claim.evidence_refs)
        claim_id = _hash(
            {
                "criterion_id": criterion.id,
                "assertion_id": claim.assertion_id,
                "value": claim.value,
                "evidence_ids": ids,
            }
        )
        claims_by_ref[claim.claim_ref] = EvaluationClaim(
            claim_id=claim_id,
            assertion_id=claim.assertion_id,
            value=claim.value,
            evidence_ids=ids,
            run_ids=[run_id],
        )

    evidence_sets: list[EvidenceSet] = []
    related_claim_refs: set[str] = set()
    for submitted in submission.evidence_sets:
        _assertions(criterion, submitted.assertion_ids)
        unknown_claims = sorted(set(submitted.claim_refs) - set(claims_by_ref))
        if unknown_claims:
            raise ValueError("unknown claim refs: " + ", ".join(unknown_claims))
        for claim_ref in submitted.claim_refs:
            claim_assertion = claims_by_ref[claim_ref].assertion_id
            if claim_assertion not in submitted.assertion_ids:
                raise ValueError(
                    f"evidence set {submitted.evidence_set_ref!r} does not include "
                    f"claim assertion {claim_assertion!r}"
                )
        related_claim_refs.update(submitted.claim_refs)
        claim_ids = [claims_by_ref[ref].claim_id for ref in submitted.claim_refs]
        ids = evidence_ids(submitted.evidence_refs)
        evidence_sets.append(
            EvidenceSet(
                evidence_set_id=_hash(
                    {
                        "criterion_id": criterion.id,
                        "assertion_ids": submitted.assertion_ids,
                        "evidence_ids": ids,
                        "relation": submitted.relation.value,
                        "role": submitted.role,
                    }
                ),
                role=submitted.role,
                assertion_ids=submitted.assertion_ids,
                claim_ids=claim_ids,
                evidence_ids=ids,
                relation=submitted.relation,
                run_ids=[run_id],
                batch_ids=list(batch_ids),
            )
        )
    unrelated_claims = sorted(set(claims_by_ref) - related_claim_refs)
    if unrelated_claims:
        raise ValueError(
            "claim refs missing evidence set relation: "
            + ", ".join(unrelated_claims)
        )

    gaps: list[EvaluationGap] = []
    for submitted in submission.gaps:
        _assertions(criterion, submitted.assertion_ids)
        question = next(
            (
                criterion.assertion(assertion).resolution_contract
                for assertion in submitted.assertion_ids
                if criterion.assertion(assertion).resolution_contract
            ),
            criterion.remediation_prompt,
        )
        gaps.append(
            EvaluationGap(
                gap_id=_hash(
                    {
                        "criterion_id": criterion.id,
                        "assertion_ids": submitted.assertion_ids,
                        "kind": submitted.kind,
                    }
                ),
                assertion_ids=submitted.assertion_ids,
                kind=submitted.kind,
                question=question,
                missing_decisions=(
                    [submitted.missing_decision.strip()]
                    if submitted.missing_decision
                    else []
                ),
            )
        )

    ambiguities: list[EvaluationAmbiguity] = []
    for submitted in submission.ambiguities:
        _assertions(criterion, submitted.assertion_ids)
        ids = evidence_ids(submitted.evidence_refs)
        ambiguities.append(
            EvaluationAmbiguity(
                issue_id=_hash(
                    {
                        "criterion_id": criterion.id,
                        "assertion_ids": submitted.assertion_ids,
                        "evidence_ids": ids,
                        "kind": "ambiguity",
                    }
                ),
                assertion_ids=submitted.assertion_ids,
                evidence_ids=ids,
                alternatives=submitted.alternatives,
                run_ids=[run_id],
            )
        )

    contradictions: list[EvaluationContradiction] = []
    for submitted in submission.contradictions:
        _assertions(criterion, submitted.assertion_ids)
        left = evidence_ids(submitted.left_evidence_refs)
        right = evidence_ids(submitted.right_evidence_refs)
        contradictions.append(
            EvaluationContradiction(
                issue_id=_hash(
                    {
                        "criterion_id": criterion.id,
                        "assertion_ids": submitted.assertion_ids,
                        "left": left,
                        "right": right,
                        "relation": submitted.relation,
                    }
                ),
                assertion_ids=submitted.assertion_ids,
                left_evidence_ids=left,
                right_evidence_ids=right,
                relation=submitted.relation,
                run_ids=[run_id],
            )
        )
    if submission.applicability is Applicability.NOT_APPLICABLE:
        if not submission.not_applicable_evidence_refs:
            raise ValueError("not_applicable requires verified evidence")
        evidence_ids(submission.not_applicable_evidence_refs)

    status = _status(
        criterion,
        submission.applicability,
        evidence_sets,
        gaps,
        ambiguities,
        contradictions,
        coverage_complete,
    )
    assertion_outcomes = derive_assertion_outcomes(
        criterion,
        evidence_sets,
        gaps,
        ambiguities,
        contradictions,
        coverage_complete=coverage_complete,
    )
    payload = {
        "criterion_id": criterion.id,
        "snapshot_id": document.snapshot_id,
        "rubric_id": rubric.id,
        "rubric_version": rubric.version,
        "plan_fingerprint": plan_fingerprint,
        "run_ids": [run_id],
        "batch_ids": batch_ids,
        "status": status.value,
        "evidence": sorted(span.evidence_id for span in spans_by_ref.values()),
    }
    return CriterionEvaluation(
        evaluation_id=_hash(payload),
        criterion_id=criterion.id,
        snapshot_id=document.snapshot_id,
        rubric_id=rubric.id,
        rubric_version=rubric.version,
        plan_fingerprint=plan_fingerprint,
        run_ids=[run_id],
        batch_ids=list(batch_ids),
        coverage_complete=coverage_complete,
        applicability=submission.applicability,
        status=status,
        evidence=list(spans_by_ref.values()),
        claims=list(claims_by_ref.values()),
        evidence_sets=evidence_sets,
        gaps=gaps,
        ambiguities=ambiguities,
        contradictions=contradictions,
        assertion_outcomes=assertion_outcomes,
        confidence=EvaluationConfidence(
            agreement=1.0,
            run_count=1,
            expected_run_count=1,
            basis="single_evaluation_run",
        ),
        origin="criterion_evaluation",
    )
