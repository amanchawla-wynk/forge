"""Deterministic edge-case coverage ledger and stopping rule.

The model may classify only predeclared requirement/taxonomy pairs. Python
verifies every requirement and coverage quote, derives the criterion verdict,
and chooses the next uncovered pair. "Complete" always means complete against
this versioned taxonomy, never every imaginable real-world edge case.
"""

from __future__ import annotations

from enum import Enum
from collections import Counter

from pydantic import BaseModel, Field

from forge.ingest.models import NormalizedDocument, SupplementalAnswer
from forge.rubric.models import Verdict

EDGE_CASE_TAXONOMY_VERSION = "1.0"


class EdgeCaseType(BaseModel):
    id: str
    label: str
    question: str


EDGE_CASE_TYPES = [
    EdgeCaseType(
        id="interruption_recovery",
        label="Interruption and recovery",
        question=(
            "What should happen if this flow is interrupted after it starts, "
            "and how does the user recover?"
        ),
    ),
    EdgeCaseType(
        id="connectivity_loss",
        label="Connectivity loss",
        question=(
            "What should happen if connectivity is lost at this point and "
            "later restored?"
        ),
    ),
    EdgeCaseType(
        id="time_or_entitlement_expiry",
        label="Time, entitlement, or content expiry",
        question=(
            "What should happen if a time limit, entitlement, or content "
            "availability changes while this is in progress?"
        ),
    ),
    EdgeCaseType(
        id="eligibility_change",
        label="Login, consent, subscription, or eligibility change",
        question=(
            "What should happen if the user's login, subscription, consent, "
            "or eligibility changes during this flow?"
        ),
    ),
    EdgeCaseType(
        id="duplicate_or_retry",
        label="Duplicate action or retry",
        question="What should happen if this action is retried or submitted twice?",
    ),
    EdgeCaseType(
        id="concurrent_state_change",
        label="Concurrent state change",
        question=(
            "What should happen if the same state changes on another device "
            "or session at the same time?"
        ),
    ),
    EdgeCaseType(
        id="partial_completion",
        label="Partial completion",
        question="What state is preserved if only part of this flow completes?",
    ),
    EdgeCaseType(
        id="empty_or_exhausted",
        label="Empty or exhausted state",
        question=(
            "What should happen when this list, quota, or result set is empty "
            "or exhausted?"
        ),
    ),
    EdgeCaseType(
        id="app_lifecycle",
        label="App background, termination, and restart",
        question=(
            "What state is preserved if the app is backgrounded, killed, or "
            "reopened here?"
        ),
    ),
    EdgeCaseType(
        id="stale_or_conflicting_state",
        label="Stale or conflicting state",
        question=(
            "What should happen if the client and backend disagree about this state?"
        ),
    ),
]

_EDGE_BY_ID = {edge.id: edge for edge in EDGE_CASE_TYPES}


class CoverageStatus(str, Enum):
    COVERED = "covered"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"
    UNCLEAR = "unclear"


class EdgeCaseCoverageItem(BaseModel):
    requirement_criterion_id: str
    requirement_field: str
    requirement_quote: str
    edge_case_id: str
    status: CoverageStatus
    evidence_quote: str | None = None
    requirement_block_id: str | None = None
    evidence_block_id: str | None = None


class EdgeCaseCoverageLedger(BaseModel):
    taxonomy_version: str = EDGE_CASE_TAXONOMY_VERSION
    items: list[EdgeCaseCoverageItem] = Field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return bool(self.items) and all(
            item.status in {CoverageStatus.COVERED, CoverageStatus.NOT_APPLICABLE}
            for item in self.items
        )


def verify_coverage_ledger(
    document: NormalizedDocument, ledger: EdgeCaseCoverageLedger
) -> EdgeCaseCoverageLedger:
    """Verify anchors/evidence and downgrade unsupported positive claims.

    Structural errors are rejected because they indicate stale or malformed
    state. Unsupported `covered`/`not_applicable` claims become `unclear`, so
    model optimism can never inflate readiness.
    """
    if ledger.taxonomy_version != EDGE_CASE_TAXONOMY_VERSION:
        raise ValueError(
            f"edge-case taxonomy {ledger.taxonomy_version!r} is stale; expected "
            f"{EDGE_CASE_TAXONOMY_VERSION!r}"
        )
    seen: set[tuple[str, str]] = set()
    verified: list[EdgeCaseCoverageItem] = []
    for supplied in ledger.items:
        key = (supplied.requirement_quote, supplied.edge_case_id)
        if key in seen:
            raise ValueError("edge-case coverage contains a duplicate pair")
        seen.add(key)
        if supplied.edge_case_id not in _EDGE_BY_ID:
            raise ValueError(
                f"unknown edge_case_id {supplied.edge_case_id!r}"
            )
        requirement_block = document.locate_quote(supplied.requirement_quote)
        if requirement_block is None or requirement_block.provenance != "document":
            raise ValueError(
                "edge-case requirement anchor is not verified original-document text: "
                + supplied.requirement_quote
            )
        item = supplied.model_copy(deep=True)
        item.requirement_block_id = requirement_block.id
        item.evidence_block_id = None

        if item.status in {CoverageStatus.COVERED, CoverageStatus.NOT_APPLICABLE}:
            evidence_block = (
                document.locate_quote(item.evidence_quote)
                if item.evidence_quote
                else None
            )
            if evidence_block is None or (
                evidence_block.provenance == "supplemental_answer"
                and evidence_block.criterion_id != "edge_cases_and_states"
            ):
                item.status = CoverageStatus.UNCLEAR
                item.evidence_quote = None
            else:
                item.evidence_block_id = evidence_block.id
        else:
            item.evidence_quote = None
        verified.append(item)
    return EdgeCaseCoverageLedger(items=verified)


def apply_coverage_answers(
    ledger: EdgeCaseCoverageLedger, answers: list[SupplementalAnswer]
) -> EdgeCaseCoverageLedger:
    """Apply explicitly cell-bound user answers before evidence verification."""
    updated = ledger.model_copy(deep=True)
    by_pair = {
        (item.requirement_quote, item.edge_case_id): item for item in updated.items
    }
    for answer in answers:
        if answer.criterion_id != "edge_cases_and_states":
            continue
        if not answer.requirement_quote or not answer.edge_case_id:
            continue
        if answer.taxonomy_version != updated.taxonomy_version:
            raise ValueError(
                "edge-case answer taxonomy version does not match the ledger"
            )
        item = by_pair.get((answer.requirement_quote, answer.edge_case_id))
        if item is None:
            raise ValueError(
                "edge-case answer does not match a requirement/taxonomy pair "
                "in the supplied ledger"
            )
        item.status = CoverageStatus.COVERED
        item.evidence_quote = answer.answer
    return updated


def coverage_verdict(ledger: EdgeCaseCoverageLedger) -> Verdict:
    """Derive the edge-case criterion verdict from taxonomy coverage."""
    if not ledger.items:
        return Verdict.ABSENT
    if ledger.is_complete:
        return Verdict.PRESENT
    if any(item.status == CoverageStatus.COVERED for item in ledger.items):
        return Verdict.PARTIAL
    return Verdict.ABSENT


def next_uncovered_item(
    ledger: EdgeCaseCoverageLedger,
) -> EdgeCaseCoverageItem | None:
    """Stable queue: explicit missing items before ambiguous ones."""
    for status in (CoverageStatus.MISSING, CoverageStatus.UNCLEAR):
        for item in ledger.items:
            if item.status == status:
                return item
    return None


def render_coverage_question(display_name: str, item: EdgeCaseCoverageItem) -> str:
    edge = _EDGE_BY_ID[item.edge_case_id]
    return (
        f'For "{display_name}", the PRD says: "{item.requirement_quote}" '
        f"{edge.question}"
    )


def edge_case_type(edge_case_id: str) -> EdgeCaseType:
    return _EDGE_BY_ID[edge_case_id]


def consolidate_coverage_ledgers(
    ledgers: list[EdgeCaseCoverageLedger],
) -> tuple[EdgeCaseCoverageLedger, list[float]]:
    """Modal status per pair with a pessimistic tie-break."""
    if not ledgers:
        raise ValueError("no edge-case coverage runs supplied")
    expected = [
        (item.requirement_quote, item.edge_case_id) for item in ledgers[0].items
    ]
    for ledger in ledgers[1:]:
        actual = [(item.requirement_quote, item.edge_case_id) for item in ledger.items]
        if actual != expected:
            raise ValueError("edge-case coverage runs classify different pairs")
    severity = {
        CoverageStatus.MISSING: 0,
        CoverageStatus.UNCLEAR: 1,
        CoverageStatus.NOT_APPLICABLE: 2,
        CoverageStatus.COVERED: 3,
    }
    consolidated: list[EdgeCaseCoverageItem] = []
    agreement: list[float] = []
    for index in range(len(expected)):
        observed = [ledger.items[index] for ledger in ledgers]
        counts = Counter(item.status for item in observed)
        top = max(counts.values())
        tied = [status for status, count in counts.items() if count == top]
        chosen_status = min(tied, key=lambda status: severity[status])
        chosen = next(item for item in observed if item.status is chosen_status)
        consolidated.append(chosen.model_copy(deep=True))
        agreement.append(counts[chosen_status] / len(observed))
    return EdgeCaseCoverageLedger(items=consolidated), agreement
