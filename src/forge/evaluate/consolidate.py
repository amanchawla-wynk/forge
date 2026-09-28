from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import TypeVar

from pydantic import BaseModel

from forge.evaluate.models import (
    Applicability,
    AssertionOutcome,
    CriterionEvaluation,
    EvaluationClaim,
    EvaluationConfidence,
    EvaluationContradiction,
    EvaluationGap,
    EvidenceSet,
    EvidenceSpan,
    SemanticStatus,
    SupportRelation,
)
from forge.evaluate.verify import derive_assertion_outcomes
from forge.extract.models import (
    CriterionExtraction,
    Evidence,
    FieldExtraction,
    derive_verdict,
    missing_fields,
)
from forge.rubric.models import Criterion, Rubric, Verdict


T = TypeVar("T", bound=BaseModel)


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _merge_by_id(items: list[T], field: str) -> list[T]:
    merged: dict[str, T] = {}
    for item in items:
        key = str(getattr(item, field))
        previous = merged.get(key)
        if previous is None:
            merged[key] = item.model_copy(deep=True)
            continue
        updates: dict[str, object] = {}
        for list_field in ("run_ids", "batch_ids", "missing_decisions"):
            if hasattr(item, list_field):
                updates[list_field] = sorted(
                    set(getattr(previous, list_field)) | set(getattr(item, list_field))
                )
        if updates:
            merged[key] = previous.model_copy(update=updates)
    return [merged[key] for key in sorted(merged)]


def _legacy_evidence_span(
    snapshot_id: str, evidence: Evidence, fallback_identity: str
) -> EvidenceSpan:
    block_id = evidence.source_block_id or fallback_identity
    source_identity = evidence.source_parent_block_id or block_id
    local_start = evidence.quote_start_char or 0
    start = (evidence.source_start_char or 0) + local_start
    end = start + len(evidence.quote)
    evidence_id = _hash(
        {
            "snapshot_id": snapshot_id,
            "source_identity": source_identity,
            "start_char": start,
            "end_char": end,
            "provenance": evidence.provenance,
            "quote": evidence.quote,
        }
    )
    return EvidenceSpan(
        evidence_id=evidence_id,
        snapshot_id=snapshot_id,
        source_block_id=block_id,
        source_parent_block_id=evidence.source_parent_block_id,
        start_char=start,
        end_char=end,
        exact_quote=evidence.quote,
        provenance=evidence.provenance,
        page=evidence.page,
        section=evidence.section,
    )


def evaluations_from_legacy_extraction_run(
    rubric: Rubric,
    run: list[CriterionExtraction],
    *,
    snapshot_id: str,
    plan_fingerprint: str,
    run_index: int,
) -> list[CriterionEvaluation]:
    run_id = _hash(
        {
            "snapshot_id": snapshot_id,
            "plan_fingerprint": plan_fingerprint,
            "run_index": run_index,
            "run": [item.model_dump(mode="json") for item in run],
        }
    )
    evaluations: list[CriterionEvaluation] = []
    for extraction in run:
        criterion = rubric.criterion(extraction.criterion_id)
        assert criterion.evaluation is not None
        spans: list[EvidenceSpan] = []
        claims: list[EvaluationClaim] = []
        sets: list[EvidenceSet] = []
        for field in extraction.fields:
            spec = criterion.field(field.name)
            if field.evidence is None or not field.is_satisfied(spec):
                continue
            evidence_values = field.item_evidence or [field.evidence]
            field_spans = [
                _legacy_evidence_span(
                    snapshot_id,
                    evidence,
                    f"legacy:{criterion.id}:{field.name}:{index}",
                )
                for index, evidence in enumerate(evidence_values, start=1)
            ]
            spans.extend(field_spans)
            values = field.value if isinstance(field.value, list) else [field.value]
            mapped_assertions = [
                assertion
                for assertion in criterion.evaluation.assertions
                if assertion.legacy_field == field.name
            ]
            for assertion in mapped_assertions:
                for index, value in enumerate(values, start=1):
                    evidence = field_spans[min(index - 1, len(field_spans) - 1)]
                    claim_id = _hash(
                        {
                            "criterion_id": criterion.id,
                            "assertion_id": assertion.id,
                            "value": value,
                            "evidence_ids": [evidence.evidence_id],
                        }
                    )
                    claim = EvaluationClaim(
                        claim_id=claim_id,
                        assertion_id=assertion.id,
                        value=value,
                        evidence_ids=[evidence.evidence_id],
                        run_ids=[run_id],
                    )
                    claims.append(claim)
                    sets.append(
                        EvidenceSet(
                            evidence_set_id=_hash(
                                {
                                    "criterion_id": criterion.id,
                                    "assertion_id": assertion.id,
                                    "evidence_id": evidence.evidence_id,
                                    "relation": "supports",
                                    "role": "legacy_field_witness",
                                }
                            ),
                            role="legacy_field_witness",
                            assertion_ids=[assertion.id],
                            claim_ids=[claim_id],
                            evidence_ids=[evidence.evidence_id],
                            relation=SupportRelation.SUPPORTS,
                            run_ids=[run_id],
                            batch_ids=["legacy-consolidated"],
                        )
                    )
        missing = set(missing_fields(criterion, extraction))
        gaps = [
            EvaluationGap(
                gap_id=_hash(
                    {
                        "criterion_id": criterion.id,
                        "assertion_ids": [assertion.id],
                        "kind": "missing_decision",
                    }
                ),
                assertion_ids=[assertion.id],
                kind="missing_decision",
                question=assertion.resolution_contract or assertion.answer_contract,
            )
            for assertion in criterion.evaluation.assertions
            if assertion.required and assertion.legacy_field in missing
        ]
        verdict = derive_verdict(criterion, extraction)
        statuses = {
            Verdict.PRESENT: SemanticStatus.SUPPORTED,
            Verdict.PARTIAL: SemanticStatus.PARTIAL,
            Verdict.ABSENT: SemanticStatus.UNSUPPORTED,
            Verdict.NOT_APPLICABLE: SemanticStatus.NOT_APPLICABLE,
        }
        applicability = (
            Applicability.NOT_APPLICABLE
            if verdict is Verdict.NOT_APPLICABLE
            else Applicability.APPLICABLE
        )
        identity = {
            "snapshot_id": snapshot_id,
            "rubric_id": rubric.id,
            "rubric_version": rubric.version,
            "plan_fingerprint": plan_fingerprint,
            "run_id": run_id,
            "criterion_id": criterion.id,
            "origin": "legacy_field_adapter",
        }
        evaluations.append(
            CriterionEvaluation(
                evaluation_id=_hash(identity),
                criterion_id=criterion.id,
                snapshot_id=snapshot_id,
                rubric_id=rubric.id,
                rubric_version=rubric.version,
                plan_fingerprint=plan_fingerprint,
                run_ids=[run_id],
                batch_ids=["legacy-consolidated"],
                coverage_complete=True,
                applicability=applicability,
                status=statuses[verdict],
                evidence=_merge_by_id(spans, "evidence_id"),
                claims=claims,
                evidence_sets=sets,
                gaps=gaps,
                assertion_outcomes=[
                    AssertionOutcome(
                        assertion_id=assertion.id,
                        status=(
                            "supported"
                            if any(
                                claim.assertion_id == assertion.id for claim in claims
                            )
                            else "gap"
                            if assertion.required
                            else "unclear"
                        ),
                        agreement=1.0,
                        run_count=1,
                        evidence_ids=sorted(
                            {
                                evidence_id
                                for claim in claims
                                if claim.assertion_id == assertion.id
                                for evidence_id in claim.evidence_ids
                            }
                        ),
                    )
                    for assertion in criterion.evaluation.assertions
                ],
                confidence=EvaluationConfidence(
                    agreement=1.0,
                    run_count=1,
                    expected_run_count=1,
                    basis="legacy_extraction_runs",
                ),
                origin="legacy_field_adapter",
                legacy_extraction=extraction.model_copy(deep=True),
            )
        )
    return evaluations


def legacy_extraction_run_from_evaluations(
    rubric: Rubric, evaluations: list[CriterionEvaluation]
) -> list[CriterionExtraction]:
    restored: list[CriterionExtraction] = []
    for evaluation in evaluations:
        if evaluation.origin != "legacy_field_adapter" or evaluation.legacy_extraction is None:
            raise ValueError("only legacy adapter evaluations can re-enter scoring")
        rubric.criterion(evaluation.criterion_id)
        restored.append(evaluation.legacy_extraction.model_copy(deep=True))
    return restored


def consolidate_evaluation_fragments(
    evaluations: list[CriterionEvaluation],
    *,
    expected_batch_ids: list[str],
    criterion: Criterion | None = None,
) -> CriterionEvaluation:
    if not evaluations:
        raise ValueError("no criterion evaluation fragments supplied")
    first = evaluations[0]
    identity = (
        first.criterion_id,
        first.snapshot_id,
        first.rubric_id,
        first.rubric_version,
        first.plan_fingerprint,
        tuple(first.run_ids),
        first.origin,
    )
    if any(
        (
            item.criterion_id,
            item.snapshot_id,
            item.rubric_id,
            item.rubric_version,
            item.plan_fingerprint,
            tuple(item.run_ids),
            item.origin,
        )
        != identity
        for item in evaluations
    ):
        raise ValueError("cannot consolidate fragments from different plans or runs")
    batch_ids = [batch for item in evaluations for batch in item.batch_ids]
    duplicates = sorted(
        batch for batch, count in Counter(batch_ids).items() if count > 1
    )
    missing = sorted(set(expected_batch_ids) - set(batch_ids))
    unknown = sorted(set(batch_ids) - set(expected_batch_ids))
    if duplicates:
        raise ValueError("duplicate batch fragments: " + ", ".join(duplicates))
    if missing:
        raise ValueError("missing batch fragments: " + ", ".join(missing))
    if unknown:
        raise ValueError("unknown batch fragments: " + ", ".join(unknown))

    evidence = _merge_by_id(
        [span for item in evaluations for span in item.evidence], "evidence_id"
    )
    claims = _merge_by_id(
        [claim for item in evaluations for claim in item.claims], "claim_id"
    )
    evidence_sets = _merge_by_id(
        [item for evaluation in evaluations for item in evaluation.evidence_sets],
        "evidence_set_id",
    )
    gaps = _merge_by_id(
        [gap for evaluation in evaluations for gap in evaluation.gaps], "gap_id"
    )
    ambiguities = _merge_by_id(
        [issue for evaluation in evaluations for issue in evaluation.ambiguities],
        "issue_id",
    )
    contradictions = _merge_by_id(
        [issue for evaluation in evaluations for issue in evaluation.contradictions],
        "issue_id",
    )
    relations = {item.relation for item in evidence_sets}
    statuses = {item.status for item in evaluations}
    if contradictions or SupportRelation.CONTRADICTS in relations:
        status = SemanticStatus.CONTRADICTORY
    elif ambiguities:
        status = SemanticStatus.UNCLEAR
    elif SupportRelation.SUPPORTS in relations:
        status = (
            SemanticStatus.SUPPORTED
            if statuses == {SemanticStatus.SUPPORTED}
            else SemanticStatus.PARTIAL
        )
    elif gaps:
        status = SemanticStatus.UNSUPPORTED
    elif statuses == {SemanticStatus.UNSUPPORTED}:
        status = SemanticStatus.UNSUPPORTED
    else:
        status = SemanticStatus.UNCLEAR
    payload = {
        "identity": identity,
        "batch_ids": sorted(batch_ids),
        "status": status.value,
        "evidence_ids": [item.evidence_id for item in evidence],
    }
    assertion_outcomes = (
        derive_assertion_outcomes(
            criterion,
            evidence_sets,
            gaps,
            ambiguities,
            contradictions,
            coverage_complete=True,
        )
        if criterion is not None
        else _merge_assertion_outcomes(evaluations)
    )
    return first.model_copy(
        update={
            "evaluation_id": _hash(payload),
            "batch_ids": sorted(batch_ids),
            "coverage_complete": True,
            "status": status,
            "evidence": evidence,
            "claims": claims,
            "evidence_sets": evidence_sets,
            "gaps": gaps,
            "ambiguities": ambiguities,
            "contradictions": contradictions,
            "assertion_outcomes": assertion_outcomes,
        },
        deep=True,
    )


def consolidate_evaluation_runs(
    evaluations: list[CriterionEvaluation],
    *,
    expected_run_count: int,
    criterion: Criterion | None = None,
) -> CriterionEvaluation:
    if not evaluations:
        raise ValueError("no criterion evaluation runs supplied")
    first = evaluations[0]
    identity = (
        first.criterion_id,
        first.snapshot_id,
        first.rubric_id,
        first.rubric_version,
        first.plan_fingerprint,
        first.origin,
    )
    if any(
        (
            item.criterion_id,
            item.snapshot_id,
            item.rubric_id,
            item.rubric_version,
            item.plan_fingerprint,
            item.origin,
        )
        != identity
        for item in evaluations
    ):
        raise ValueError("cannot consolidate evaluations from different plans")
    run_ids = [run_id for item in evaluations for run_id in item.run_ids]
    if len(run_ids) != len(set(run_ids)):
        raise ValueError("duplicate evaluation run identity")
    counts = Counter(item.status for item in evaluations)
    selected, count = counts.most_common(1)[0]
    if count <= len(evaluations) / 2:
        selected = SemanticStatus.UNCLEAR
        count = max(counts.values())
    evidence = _merge_by_id(
        [span for item in evaluations for span in item.evidence], "evidence_id"
    )
    claims = _merge_by_id(
        [claim for item in evaluations for claim in item.claims], "claim_id"
    )
    evidence_sets = _merge_by_id(
        [item for evaluation in evaluations for item in evaluation.evidence_sets],
        "evidence_set_id",
    )
    gaps = _merge_by_id(
        [gap for evaluation in evaluations for gap in evaluation.gaps], "gap_id"
    )
    ambiguities = _merge_by_id(
        [issue for evaluation in evaluations for issue in evaluation.ambiguities],
        "issue_id",
    )
    contradictions = _merge_by_id(
        [issue for evaluation in evaluations for issue in evaluation.contradictions],
        "issue_id",
    )
    payload = {
        "identity": identity,
        "run_ids": sorted(run_ids),
        "status": selected.value,
    }
    assertion_outcomes = _consolidate_assertion_outcomes(evaluations, criterion)
    if criterion is not None:
        assert criterion.evaluation is not None
        required_ids = {
            assertion.id
            for assertion in criterion.evaluation.assertions
            if assertion.required
        }
        required = [
            outcome
            for outcome in assertion_outcomes
            if outcome.assertion_id in required_ids
        ]
        required_statuses = {outcome.status for outcome in required}
        if "contradictory" in required_statuses:
            selected = SemanticStatus.CONTRADICTORY
        elif required_statuses & {"ambiguous", "unclear"}:
            selected = SemanticStatus.UNCLEAR
        elif required and required_statuses == {"supported"}:
            selected = SemanticStatus.SUPPORTED
        elif "supported" in required_statuses:
            selected = SemanticStatus.PARTIAL
        elif required and required_statuses == {"gap"}:
            selected = SemanticStatus.UNSUPPORTED
        else:
            selected = SemanticStatus.UNCLEAR
        count = round(
            sum(outcome.agreement for outcome in required) / len(required), 4
        ) if required else 0.0
    return first.model_copy(
        update={
            "evaluation_id": _hash(payload),
            "run_ids": sorted(run_ids),
            "batch_ids": sorted(
                {batch for item in evaluations for batch in item.batch_ids}
            ),
            "status": selected,
            "evidence": evidence,
            "claims": claims,
            "evidence_sets": evidence_sets,
            "gaps": gaps,
            "ambiguities": ambiguities,
            "contradictions": contradictions,
            "assertion_outcomes": assertion_outcomes,
            "confidence": EvaluationConfidence(
                agreement=(
                    count
                    if criterion is not None
                    else count / len(evaluations)
                ),
                run_count=len(evaluations),
                expected_run_count=expected_run_count,
                basis=(
                    "legacy_extraction_runs"
                    if first.origin == "legacy_field_adapter"
                    else "independent_evaluation_runs"
                ),
            ),
            "legacy_extraction": None,
        },
        deep=True,
    )


def _merge_assertion_outcomes(
    evaluations: list[CriterionEvaluation],
) -> list[AssertionOutcome]:
    by_assertion: dict[str, list[AssertionOutcome]] = {}
    for evaluation in evaluations:
        for outcome in evaluation.assertion_outcomes:
            by_assertion.setdefault(outcome.assertion_id, []).append(outcome)
    return [
        AssertionOutcome(
            assertion_id=assertion_id,
            status=next(
                (
                    status
                    for status in (
                        "contradictory",
                        "ambiguous",
                        "supported",
                        "gap",
                        "unclear",
                    )
                    if any(item.status == status for item in outcomes)
                ),
                "unclear",
            ),
            agreement=1.0,
            run_count=1,
            evidence_ids=sorted(
                {evidence for item in outcomes for evidence in item.evidence_ids}
            ),
            issue_ids=sorted(
                {issue for item in outcomes for issue in item.issue_ids}
            ),
        )
        for assertion_id, outcomes in sorted(by_assertion.items())
    ]


def _consolidate_assertion_outcomes(
    evaluations: list[CriterionEvaluation], criterion: Criterion | None
) -> list[AssertionOutcome]:
    assertion_ids = (
        [assertion.id for assertion in criterion.evaluation.assertions]
        if criterion is not None
        else sorted(
            {
                outcome.assertion_id
                for evaluation in evaluations
                for outcome in evaluation.assertion_outcomes
            }
        )
    )
    results: list[AssertionOutcome] = []
    for assertion_id in assertion_ids:
        observed = [
            next(
                (
                    outcome
                    for outcome in evaluation.assertion_outcomes
                    if outcome.assertion_id == assertion_id
                ),
                AssertionOutcome(
                    assertion_id=assertion_id,
                    status="unclear",
                    agreement=1.0,
                    run_count=1,
                ),
            )
            for evaluation in evaluations
        ]
        counts = Counter(item.status for item in observed)
        status, votes = counts.most_common(1)[0]
        if votes <= len(observed) / 2:
            status = "unclear"
            votes = max(counts.values())
        issue_ids = sorted(
            {
                issue
                for item in observed
                if item.status == status or status == "unclear"
                for issue in item.issue_ids
            }
        )
        if status == "contradictory":
            issue_ids = _majority_contradiction_issue_ids(
                evaluations, assertion_id
            )
        results.append(
            AssertionOutcome(
                assertion_id=assertion_id,
                status=status,
                agreement=votes / len(observed),
                run_count=len(observed),
                evidence_ids=sorted(
                    {
                        evidence
                        for item in observed
                        if item.status == status or status == "unclear"
                        for evidence in item.evidence_ids
                    }
                ),
                issue_ids=issue_ids,
            )
        )
    return results


def _majority_contradiction_issue_ids(
    evaluations: list[CriterionEvaluation], assertion_id: str
) -> list[str]:
    grouped: dict[
        tuple[str, tuple[tuple[str, ...], tuple[str, ...]]],
        list[EvaluationContradiction],
    ] = {}
    for evaluation in evaluations:
        for issue in evaluation.contradictions:
            sides = tuple(
                sorted(
                    (
                        tuple(sorted(issue.left_evidence_ids)),
                        tuple(sorted(issue.right_evidence_ids)),
                    )
                )
            )
            grouped.setdefault((issue.relation, sides), []).append(issue)

    selected: list[str] = []
    for issues in grouped.values():
        supporting_runs = {
            run_id for issue in issues for run_id in issue.run_ids
        }
        if len(supporting_runs) <= len(evaluations) / 2:
            continue
        target_issues = [
            issue for issue in issues if assertion_id in issue.assertion_ids
        ]
        if target_issues:
            selected.append(min(issue.issue_id for issue in target_issues))
    return sorted(selected)
