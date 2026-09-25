from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from forge.extract.models import CriterionExtraction, Evidence
from forge.ingest.models import NormalizedDocument, normalize_for_match
from forge.rubric.models import Rubric


FindingKind = Literal[
    "impossible_range",
    "conflicting_threshold",
    "conflicting_timeline",
    "metric_not_computable",
    "enum_domain_conflict",
    "schema_type_conflict",
    "opposite_polarity",
    "duplicate_rank",
    "precedence_cycle",
    "precedence_conflict",
    "scoped_contradiction",
    "superseded_requirement",
    "implied_exception",
    "ambiguous_scope",
]
GraphNodeKind = Literal["claim", "milestone", "metric", "event"]
GraphEdgeKind = Literal[
    "scheduled_on",
    "declares_event",
    "computes_metric",
    "computed_from",
]


class ClaimOccurrence(BaseModel):
    claim_id: str
    criterion_id: str
    field_name: str
    value: str
    quote: str
    run_indexes: list[int]
    batch_ids: list[str]
    provenance: str
    source_block_id: str
    source_parent_block_id: str | None = None
    page: int | None = None
    section: str | None = None
    quote_start_char: int | None = None
    quote_end_char: int | None = None


class ClaimInterpretation(BaseModel):
    """Deterministic explicit-language projection of one verified claim."""

    interpretation_id: str
    claim_id: str
    subject_keys: list[str] = Field(default_factory=list)
    scope_keys: list[str] = Field(default_factory=list)
    phase_keys: list[str] = Field(default_factory=list)
    modality: Literal["must", "should", "may", "unknown"] = "unknown"
    provenance: Literal["deterministic"] = "deterministic"


class FindingEvidence(BaseModel):
    claim_id: str
    quote: str
    page: int | None = None
    section: str | None = None
    source_block_id: str


class DeepReviewFinding(BaseModel):
    finding_id: str
    kind: FindingKind
    title: str
    summary: str
    evidence: list[FindingEvidence]
    affected_consumers: list[str]
    implementation_consequence: str
    required_decision: str
    review_order: int
    # `deterministic` findings were proved in Python. `classified` findings
    # additionally required a bounded model choice, so they are reported as a
    # weaker claim even though both quotes were source-verified.
    confidence: Literal["deterministic", "classified"] = "deterministic"


class RequirementGraphNode(BaseModel):
    node_id: str
    kind: GraphNodeKind
    label: str
    claim_id: str | None = None


class RequirementGraphEdge(BaseModel):
    edge_id: str
    source_id: str
    target_id: str
    relation: GraphEdgeKind
    claim_id: str


class RequirementGraph(BaseModel):
    nodes: list[RequirementGraphNode] = Field(default_factory=list)
    edges: list[RequirementGraphEdge] = Field(default_factory=list)


class DeepReviewReport(BaseModel):
    summary: str
    findings: list[DeepReviewFinding] = Field(default_factory=list)
    claims: list[ClaimOccurrence] = Field(default_factory=list)
    interpretations: list[ClaimInterpretation] = Field(default_factory=list)
    graph: RequirementGraph = Field(default_factory=RequirementGraph)
    candidate_count: int = 0
    advisory: bool = True


def claim_occurrences(
    criteria: list[CriterionExtraction], *, run_index: int, batch_id: str
) -> list[ClaimOccurrence]:
    occurrences: list[ClaimOccurrence] = []
    for criterion in criteria:
        for field in criterion.fields:
            if isinstance(field.value, list):
                for item in field.value:
                    evidence = next(
                        (
                            candidate
                            for candidate in field.item_evidence
                            if candidate.quote == item
                        ),
                        None,
                    )
                    if evidence is None:
                        continue
                    occurrences.append(
                        _claim(
                            criterion.criterion_id,
                            field.name,
                            item,
                            evidence,
                            run_index,
                            batch_id,
                        )
                    )
            elif isinstance(field.value, str) and field.evidence is not None:
                occurrences.append(
                    _claim(
                        criterion.criterion_id,
                        field.name,
                        field.evidence.quote,
                        field.evidence,
                        run_index,
                        batch_id,
                    )
                )
    return occurrences


def mechanical_claim_occurrences(
    document: NormalizedDocument,
    existing: list[ClaimOccurrence],
) -> list[ClaimOccurrence]:
    """Extract the small set of source patterns Python can prove directly."""
    known_spans = {
        (claim.source_block_id, claim.quote_start_char, claim.quote_end_char)
        for claim in existing
    }
    occurrences: list[ClaimOccurrence] = []
    for block in document.blocks:
        cursor = 0
        for segment in re.split(r"(?<=[.!?])\s+|\n+", block.text):
            quote = segment.strip()
            if not quote:
                cursor += len(segment)
                continue
            start = block.text.find(quote, cursor)
            if start < 0:
                start = block.text.find(quote)
            end = start + len(quote)
            cursor = max(cursor, end)
            criterion_id, field_name = _mechanical_field(quote)
            if criterion_id is None or field_name is None:
                continue
            if (block.id, start, end) in known_spans:
                continue
            evidence = Evidence(
                quote=quote,
                section=block.section,
                page=block.page,
                provenance=block.provenance,
                source_block_id=block.id,
                source_parent_block_id=block.parent_id,
                source_start_char=block.start_char,
                source_end_char=block.end_char,
                quote_start_char=start,
                quote_end_char=end,
            )
            occurrence = _claim(
                criterion_id,
                field_name,
                quote,
                evidence,
                0,
                "source-scan",
            )
            occurrence.run_indexes = []
            occurrences.append(occurrence)
    occurrences.extend(
        _structured_claim_occurrences(document, known_spans | {
            (claim.source_block_id, claim.quote_start_char, claim.quote_end_char)
            for claim in occurrences
        })
    )
    return occurrences


def build_deep_review(
    rubric: Rubric,
    observed_claims: list[ClaimOccurrence],
    *,
    extra_findings: list[DeepReviewFinding] | None = None,
) -> DeepReviewReport:
    claims = _merge_observations(observed_claims)
    interpretations = _claim_interpretations(claims)
    findings: list[DeepReviewFinding] = []
    graph = _build_requirement_graph(claims)
    seen: set[str] = set()
    candidates = 0

    for claim in claims:
        impossible = _impossible_range(claim.quote)
        if impossible is None:
            continue
        signature = "impossible_range:" + normalize_for_match(claim.quote)
        if signature in seen:
            continue
        seen.add(signature)
        candidates += 1
        finding = _impossible_range_finding(rubric, claim, impossible)
        findings.append(finding)

    threshold_rules: dict[str, list[tuple[ClaimOccurrence, str]]] = defaultdict(list)
    for claim in claims:
        for label, expression in _skip_thresholds(claim.quote):
            threshold_rules[label].append((claim, expression))

    for label, rules in sorted(threshold_rules.items()):
        unique_expressions = {expression for _, expression in rules}
        if len(unique_expressions) < 2:
            continue
        candidates += 1
        finding = _threshold_finding(rubric, label, rules)
        signature = "conflicting_threshold:" + label
        if signature not in seen:
            seen.add(signature)
            findings.append(finding)

    timeline_rules = _timeline_rules(claims)
    for milestone, rules in sorted(timeline_rules.items()):
        if not _timeline_values_conflict([value for _, value in rules]):
            continue
        signature = "conflicting_timeline:" + milestone
        if signature in seen:
            continue
        seen.add(signature)
        candidates += 1
        findings.append(_timeline_finding(rubric, milestone, rules))

    declared_events = _declared_events(claims)
    if declared_events:
        for claim, operands in _metric_formulas(claims):
            missing = sorted(set(operands) - set(declared_events))
            if not missing:
                continue
            signature = "metric_not_computable:" + claim.claim_id
            if signature in seen:
                continue
            seen.add(signature)
            candidates += 1
            findings.append(
                _metric_finding(rubric, claim, missing, declared_events)
            )

    for label, rules, domains in _enum_conflicts(claims):
        signature = "enum_domain_conflict:" + label
        if signature in seen:
            continue
        seen.add(signature)
        candidates += 1
        findings.append(_enum_finding(rubric, label, rules, domains))

    for field, declarations in _schema_conflicts(claims):
        signature = "schema_type_conflict:" + field
        if signature in seen:
            continue
        seen.add(signature)
        candidates += 1
        findings.append(_schema_finding(rubric, field, declarations))

    for subject, axis, rules in _polarity_conflicts(claims):
        signature = f"opposite_polarity:{subject}:{axis}"
        if signature in seen:
            continue
        seen.add(signature)
        candidates += 1
        findings.append(_polarity_finding(rubric, subject, axis, rules))

    for ranking, rank, rules in _duplicate_ranks(claims):
        signature = f"duplicate_rank:{ranking}:{rank}"
        if signature in seen:
            continue
        seen.add(signature)
        candidates += 1
        findings.append(_duplicate_rank_finding(rubric, ranking, rank, rules))

    for cycle in _precedence_cycles(claims):
        identity = "\x1f".join(sorted(claim.claim_id for claim, _, _ in cycle))
        signature = "precedence_cycle:" + hashlib.sha256(identity.encode()).hexdigest()
        if signature in seen:
            continue
        seen.add(signature)
        candidates += 1
        findings.append(_precedence_cycle_finding(rubric, cycle))

    for finding in extra_findings or []:
        if finding.finding_id in seen:
            continue
        seen.add(finding.finding_id)
        candidates += 1
        findings.append(finding)

    findings.sort(key=lambda finding: (finding.review_order, finding.finding_id))
    return DeepReviewReport(
        summary=(
            f"Found {len(findings)} source-verified implementation blocker(s) "
            f"across {len(claims)} source-backed claim(s)."
            if findings
            else (
                f"No source-verified implementation blockers were found across "
                f"{len(claims)} source-backed claim(s)."
            )
        ),
        findings=findings,
        claims=claims,
        interpretations=interpretations,
        graph=graph,
        candidate_count=candidates,
    )


def _claim(
    criterion_id: str,
    field_name: str,
    value: str,
    evidence: Evidence,
    run_index: int,
    batch_id: str,
) -> ClaimOccurrence:
    source_identity = evidence.source_parent_block_id or evidence.source_block_id or ""
    source_offset = evidence.source_start_char or 0
    quote_start = (
        source_offset + evidence.quote_start_char
        if evidence.quote_start_char is not None
        else None
    )
    quote_end = (
        source_offset + evidence.quote_end_char
        if evidence.quote_end_char is not None
        else None
    )
    identity = "\x1f".join(
        [
            criterion_id,
            field_name,
            value.strip(),
            evidence.quote.strip(),
            source_identity,
            str(quote_start),
            str(quote_end),
        ]
    )
    return ClaimOccurrence(
        claim_id=hashlib.sha256(identity.encode()).hexdigest()[:20],
        criterion_id=criterion_id,
        field_name=field_name,
        value=value.strip(),
        quote=evidence.quote,
        run_indexes=[run_index],
        batch_ids=[batch_id],
        provenance=evidence.provenance,
        source_block_id=evidence.source_block_id or "unknown",
        source_parent_block_id=evidence.source_parent_block_id,
        page=evidence.page,
        section=evidence.section,
        quote_start_char=quote_start,
        quote_end_char=quote_end,
    )


def _merge_observations(claims: list[ClaimOccurrence]) -> list[ClaimOccurrence]:
    merged: dict[str, ClaimOccurrence] = {}
    for claim in claims:
        existing = merged.get(claim.claim_id)
        if existing is None:
            merged[claim.claim_id] = claim.model_copy(deep=True)
            continue
        existing.run_indexes = sorted(set(existing.run_indexes + claim.run_indexes))
        existing.batch_ids = sorted(set(existing.batch_ids + claim.batch_ids))
    return sorted(
        merged.values(),
        key=lambda claim: (
            claim.page or 0,
            claim.section or "",
            claim.source_block_id,
            claim.quote_start_char or 0,
            claim.claim_id,
        ),
    )


def _mechanical_field(text: str) -> tuple[str | None, str | None]:
    if _event_formula_operands(text):
        return "instrumentation", "metric_link"
    if _event_declarations(text):
        return "instrumentation", "events"
    if _timeline_values(text):
        return "rollout", "launch_and_stop_criteria"
    if _SKIP_LABEL.search(text) or _CHAINED_RANGE.search(text):
        return "functional_requirements", "requirements"
    if _POLARITY.search(text) or _PRECEDENCE.search(text) or _RANK_ASSIGNMENT.search(text):
        return "functional_requirements", "decision_rules_and_precedence"
    # Conflicts written in prose (a state's lifetime, a dependency's status, a
    # ranking order) are not provable in Python, but they cannot even be
    # offered for classification unless the sentence is retained as a claim.
    for category in category_tokens(text):
        return _CATEGORY_FIELDS[category]
    return None, None


_CATEGORY_FIELDS: dict[str, tuple[str, str]] = {
    "lifetime": ("edge_cases_and_states", "transitional_or_degraded_states"),
    "ranking": ("functional_requirements", "decision_rules_and_precedence"),
    "status": ("dependencies", "dependency_readiness"),
}


_ENUM_ROW = re.compile(
    r"(?im)^(?P<label>hard|soft|medium|mid|no)(?:\s+skip[^\n]*)?\s*$"
    r"(?P<body>(?:\n[^\n]*){1,5}?)\n\s*tier\s*(?P<value>\d+)\s*$"
)
_ENUM_DOMAIN = re.compile(
    r"(?i)\b(?P<identifier>[A-Za-z][A-Za-z0-9_]*(?:tiers?|states?|statuses))\s*:"
    r"[^\n]{0,100}?\btier\s*\(\s*(?P<low>\d+)\s*[-–—]\s*(?P<high>\d+)\s*\)"
)
_SCHEMA_ARRAY = re.compile(r"\b(?P<field>[A-Za-z][A-Za-z0-9_]*)\s*\[\s*\]")
_SCHEMA_TABLE = re.compile(
    r"(?im)^(?P<field>[A-Za-z][A-Za-z0-9_]*)\s*\n\s*"
    r"(?P<type>string|integer|int(?:32|64)?|float|number|boolean|bool|array|list)"
    r"(?:\s*\([^\n)]*\))?\s*$"
)
_SCHEMA_INLINE = re.compile(
    r"(?i)\b(?P<field>[A-Za-z][A-Za-z0-9_]*)\s*:\s*"
    r"(?P<type>string|integer|int(?:32|64)?|float|number|boolean|bool|array|list)\b"
)
_EXPLICIT_SCOPE = re.compile(
    r"(?i)\b(?:product|variant|phase|surface|fallback)\s*[-:#]?\s*[A-Za-z0-9.]+"
)
_MACHINE_IDENTIFIER = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b")
_POLARITY = re.compile(
    rf"(?i)\b(?P<subject>{_MACHINE_IDENTIFIER.pattern})\s+"
    r"(?:is|must\s+be|shall\s+be|should\s+be)\s+"
    r"(?P<value>enabled|disabled|allowed|prohibited|forbidden|included|excluded|required|optional)\b"
)
_PRECEDENCE = re.compile(
    rf"(?i)\b(?P<before>{_MACHINE_IDENTIFIER.pattern})\s+"
    r"(?:comes\s+before|before|precedes|ahead\s+of|higher\s+priority\s+than)\s+"
    rf"(?P<after>{_MACHINE_IDENTIFIER.pattern})\b"
)
_RANK_ASSIGNMENT = re.compile(
    rf"(?i)\b(?P<ranking>{_MACHINE_IDENTIFIER.pattern})\s+"
    r"(?:rank|priority)\s*(?P<rank>\d+)\s*[:=]\s*"
    rf"(?P<item>{_MACHINE_IDENTIFIER.pattern})\b"
)


def _structured_claim_occurrences(
    document: NormalizedDocument,
    known_spans: set[tuple[str, int | None, int | None]],
) -> list[ClaimOccurrence]:
    """Retain exact structured snippets that sentence splitting would destroy."""
    occurrences: list[ClaimOccurrence] = []
    for block in document.blocks:
        spans: set[tuple[int, int]] = set()
        spans.update(
            _with_scope_line(block.text, match.start(), match.end())
            for match in _ENUM_ROW.finditer(block.text)
        )
        spans.update(
            (match.start(), match.end()) for match in _ENUM_DOMAIN.finditer(block.text)
        )
        spans.update(
            _line_span(block.text, match.start(), match.end())
            for match in _SCHEMA_ARRAY.finditer(block.text)
        )
        spans.update(
            _with_scope_line(block.text, match.start(), match.end())
            for match in _SCHEMA_TABLE.finditer(block.text)
        )
        spans.update(
            _line_span(block.text, match.start(), match.end())
            for match in _SCHEMA_INLINE.finditer(block.text)
        )
        for start, end in sorted(spans):
            quote = block.text[start:end].strip()
            start = block.text.find(quote, start, end)
            end = start + len(quote)
            identity = (block.id, start, end)
            if not quote or identity in known_spans:
                continue
            evidence = Evidence(
                quote=quote,
                section=block.section,
                page=block.page,
                provenance=block.provenance,
                source_block_id=block.id,
                source_parent_block_id=block.parent_id,
                source_start_char=block.start_char,
                source_end_char=block.end_char,
                quote_start_char=start,
                quote_end_char=end,
            )
            occurrence = _claim(
                "functional_requirements",
                "requirements",
                quote,
                evidence,
                0,
                "source-scan",
            )
            occurrence.run_indexes = []
            occurrences.append(occurrence)
            known_spans.add(identity)
    return occurrences


def _line_span(text: str, start: int, end: int) -> tuple[int, int]:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    return line_start, len(text) if line_end < 0 else line_end


def _with_scope_line(text: str, start: int, end: int) -> tuple[int, int]:
    previous_end = max(0, start - 1)
    previous_start = text.rfind("\n", 0, previous_end) + 1
    previous = text[previous_start:previous_end].strip()
    return (previous_start, end) if _EXPLICIT_SCOPE.search(previous) else (start, end)


_CHAINED_RANGE = re.compile(
    r"(?P<left>\d+(?:\.\d+)?)\s*(?:secs?|seconds?|%)?\s*"
    r"(?P<left_op><=|>=|≤|≥|<|>)\s*(?P<variable>[A-Za-z]\w*)\s*"
    r"(?P<right_op><=|>=|≤|≥|<|>)\s*(?P<right>\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _impossible_range(text: str) -> str | None:
    for match in _CHAINED_RANGE.finditer(text):
        left = float(match.group("left"))
        right = float(match.group("right"))
        left_op = _normalize_operator(match.group("left_op"))
        right_op = _normalize_operator(match.group("right_op"))
        lower: float | None = None
        upper: float | None = None

        if left_op in {"<=", "<"}:
            lower = left
        else:
            upper = left
        if right_op in {"<=", "<"}:
            upper = right
        else:
            lower = right
        if lower is not None and upper is not None and lower > upper:
            return match.group(0)
    return None


_SKIP_LABEL = re.compile(
    r"\b(hard|soft|medium|mid|no)[\s_-]*skip(?:s|ped)?\b", re.IGNORECASE
)
_COMPARATOR = re.compile(
    r"(?P<op><=|>=|≤|≥|<|>)\s*(?P<number>\d+(?:\.\d+)?)\s*(?:secs?|seconds?|%)?",
    re.IGNORECASE,
)
_RANGE = re.compile(
    r"(?P<low>\d+(?:\.\d+)?)\s*(?:-|to)\s*(?P<high>\d+(?:\.\d+)?)\s*(?:secs?|seconds?|%)?",
    re.IGNORECASE,
)


def _skip_thresholds(text: str) -> list[tuple[str, str]]:
    rules: list[tuple[str, str]] = []
    for label_match in _SKIP_LABEL.finditer(text):
        window = text[label_match.end() : label_match.end() + 100]
        comparator = _COMPARATOR.search(window)
        range_match = _RANGE.search(window)
        if comparator is not None:
            expression = _normalize_operator(comparator.group("op")) + comparator.group("number")
        elif range_match is not None:
            expression = range_match.group("low") + ".." + range_match.group("high")
        else:
            continue
        label = label_match.group(1).lower()
        if label == "mid":
            label = "medium"
        rules.append((label, expression))
    return rules


def _normalize_operator(operator: str) -> str:
    return {"≤": "<=", "≥": ">="}.get(operator, operator)


_MONTH_NAMES = (
    "January|February|March|April|May|June|July|August|September|October|"
    "November|December"
)
_ISO_DATE = re.compile(r"\b(?P<date>\d{4}-\d{2}-\d{2})\b")
_MONTH_FIRST_DATE = re.compile(
    rf"\b(?P<date>(?:{_MONTH_NAMES})\s+\d{{1,2}},\s+\d{{4}})\b",
    re.IGNORECASE,
)
_DAY_FIRST_DATE = re.compile(
    rf"\b(?P<date>\d{{1,2}}\s+(?:{_MONTH_NAMES})\s+\d{{4}})\b",
    re.IGNORECASE,
)
_RELATIVE_WEEKS = re.compile(
    r"\b(?P<low>\d+)\s*(?:[-–—]\s*(?P<high>\d+)\s*)?weeks?\s*"
    r"(?:post[- ]launch|after\s+(?:the\s+)?(?:initial\s+|mvp\s+)?launch|"
    r"from\s+(?:the\s+)?(?:initial\s+|mvp\s+)?launch)\b",
    re.IGNORECASE,
)
_TIMELINE_EXCLUSION = re.compile(
    r"\b(?:by|before|no later than|previously|was planned|tentative|proposed|"
    r"tbd|not launching|superseded)\b",
    re.IGNORECASE,
)
_MILESTONE_ALIASES: dict[str, tuple[str, ...]] = {
    "general_availability": ("general availability", "ga"),
    "pilot_launch": ("pilot launch",),
    "beta_launch": ("beta launch",),
    "public_launch": ("public launch",),
    "mvp_launch": ("mvp launch",),
    "trending_feed": ("trending feed", "top trending contents"),
    "highlighted_rail": ("highlighted rail",),
    "multi_armed_bandit": ("multi-armed bandit", "mab"),
    "content_based_filtering": ("content-based filtering", "cbf"),
    "collaborative_filtering": (
        "collaborative filtering",
        "apriori model",
        "user recommendations",
    ),
}


def _timeline_values(text: str) -> list[tuple[str, str]]:
    if _TIMELINE_EXCLUSION.search(text):
        return []
    subjects = _milestone_subjects(text)
    if not subjects:
        return []

    values: list[str] = []
    for pattern, date_format in (
        (_ISO_DATE, "%Y-%m-%d"),
        (_MONTH_FIRST_DATE, "%B %d, %Y"),
        (_DAY_FIRST_DATE, "%d %B %Y"),
    ):
        for match in pattern.finditer(text):
            parsed = _parse_date(match.group("date"), date_format)
            if parsed is not None:
                values.append("date:" + parsed.isoformat())
    for match in _RELATIVE_WEEKS.finditer(text):
        low = int(match.group("low"))
        high = int(match.group("high") or low)
        if low <= high:
            values.append(f"weeks:{low}-{high}:post_launch")
    return [(subject, value) for subject in subjects for value in values]


def _parse_date(value: str, date_format: str) -> date | None:
    try:
        return datetime.strptime(value.title(), date_format).date()
    except ValueError:
        return None


def subject_keys(text: str) -> list[str]:
    """Named subjects this statement provably talks about.

    These are the only anchors used to pair statements for semantic review, so
    candidate generation stays deterministic and explainable. Two statements
    are never compared because they merely look similar.
    """
    keys = {f"milestone:{subject}" for subject in _milestone_subjects(text)}
    keys.update(f"skip:{match.group(1).lower()}" for match in _SKIP_LABEL.finditer(text))
    keys.update(
        f"identifier:{match.group(0).casefold()}"
        for match in _MACHINE_IDENTIFIER.finditer(text)
    )
    return sorted(keys)


# Categories whose statements are worth comparing even when they share no
# machine identifier. These only decide *eligibility*; a pair still has to
# share concrete vocabulary before it becomes a candidate.
_CATEGORY_TRIGGERS: dict[str, re.Pattern[str]] = {
    "lifetime": re.compile(
        r"(?i)\b(?:session|rolling|retain(?:ed|s)?|persist(?:s|ed|ent)?|"
        r"stored?|expir(?:e|es|ed|y)|lifecycle|ttl|"
        r"last\s+\d+\s+(?:day|days|hour|hours|minute|minutes)|"
        r"\d+\s*(?:day|days|hour|hours|minute|minutes)\s*(?:window)?)\b"
    ),
    "status": re.compile(
        r"(?i)\b(?:open\s+point|point\s+closed|closed|blocked|pending|"
        r"unresolved|resolved|to\s+be\s+(?:decided|built|validated|confirmed)|"
        r"must\s+be\s+(?:built|validated|ready|confirmed)|tbd|"
        r"in\s+progress|not\s+started|sign[-\s]?off|approved)\b"
    ),
    "ranking": re.compile(
        r"(?i)\b(?:priority\s+order|priority|rank(?:ed|ing)?|precedence|"
        r"sorted\s+by|order(?:ing|ed)?|followed\s+by)\b"
    ),
}

# Deliberately generic. Adding product vocabulary here would overfit candidate
# generation to one document.
_CONTENT_STOPWORDS = frozenset(
    {
        "after", "also", "才能", "been", "before", "being", "below", "both",
        "case", "cases", "content", "contents", "data", "does", "done", "each",
        "else", "event", "events", "every", "feature", "from", "have", "having",
        "here", "into", "item", "items", "just", "like", "make", "many", "more",
        "most", "must", "need", "needs", "next", "only", "other", "over",
        "product", "same", "screen", "should", "shown", "some", "such", "system",
        "than", "that", "their", "them", "then", "there", "these", "they",
        "this", "those", "time", "user", "users", "using", "value", "very",
        "were", "what", "when", "where", "which", "while", "will", "with",
        "would", "your",
    }
)
MAX_CONTENT_TOKENS = 12


def category_tokens(text: str) -> dict[str, list[str]]:
    """Comparison categories this statement triggers, with its content words.

    Two statements become a candidate only when they trigger the same category
    and share several concrete words, so pairing stays explainable and cannot
    degrade into "these look similar".
    """
    triggered = {
        category
        for category, pattern in _CATEGORY_TRIGGERS.items()
        if pattern.search(text)
    }
    if not triggered:
        return {}
    tokens = sorted(
        {
            token
            for token in re.findall(r"[a-z][a-z_]{3,}", text.casefold())
            if token not in _CONTENT_STOPWORDS
        }
    )[:MAX_CONTENT_TOKENS]
    if not tokens:
        return {}
    return {category: tokens for category in sorted(triggered)}


_PHASE = re.compile(
    r"(?i)\b(?:phase\s*[A-Za-z0-9.]+|launch\s+day|post[- ]launch|"
    r"pre[- ]launch|pilot|general\s+availability)\b"
)
_MUST_MODALITY = re.compile(r"(?i)\b(?:must|shall|required)\b")
_SHOULD_MODALITY = re.compile(r"(?i)\bshould\b")
_MAY_MODALITY = re.compile(r"(?i)\b(?:may|optional)\b")


def _claim_interpretations(
    claims: list[ClaimOccurrence],
) -> list[ClaimInterpretation]:
    interpretations: list[ClaimInterpretation] = []
    for claim in claims:
        subjects = subject_keys(claim.quote)
        scopes = list(_scope_keys(claim.quote))
        phases = sorted(
            {normalize_for_match(match.group(0)) for match in _PHASE.finditer(claim.quote)}
        )
        modality: Literal["must", "should", "may", "unknown"] = "unknown"
        if _MUST_MODALITY.search(claim.quote):
            modality = "must"
        elif _SHOULD_MODALITY.search(claim.quote):
            modality = "should"
        elif _MAY_MODALITY.search(claim.quote):
            modality = "may"
        identity = "\x1f".join(
            [claim.claim_id, *subjects, *scopes, *phases, modality, "deterministic"]
        )
        interpretations.append(
            ClaimInterpretation(
                interpretation_id=hashlib.sha256(identity.encode()).hexdigest()[:20],
                claim_id=claim.claim_id,
                subject_keys=subjects,
                scope_keys=scopes,
                phase_keys=phases,
                modality=modality,
            )
        )
    return interpretations


def _milestone_subjects(text: str) -> list[str]:
    normalized = normalize_for_match(text)
    return [
        key
        for key, aliases in _MILESTONE_ALIASES.items()
        if any(re.search(rf"\b{re.escape(alias)}\b", normalized) for alias in aliases)
    ]


_EVENT_DECLARATION = re.compile(
    r"\b(?:log|emit|track|record|capture)(?:s|ed|ing)?\b|"
    r"\bevents?\s+(?:include|includes|required|are|required:)\b|\bevents?\s*:",
    re.IGNORECASE,
)
_EVENT_DIVISION = re.compile(
    rf"(?P<numerator>{_MACHINE_IDENTIFIER.pattern})\s*(?:/|divided\s+by)\s*"
    rf"(?P<denominator>{_MACHINE_IDENTIFIER.pattern})",
    re.IGNORECASE,
)
_EVENT_INTERVAL = re.compile(
    rf"\binterval\s+between\s+(?P<first>{_MACHINE_IDENTIFIER.pattern})\s+and\s+"
    rf"(?P<second>{_MACHINE_IDENTIFIER.pattern})",
    re.IGNORECASE,
)
_EVENT_COUNT = re.compile(
    rf"\bcount\s+of\s+(?P<event>{_MACHINE_IDENTIFIER.pattern})",
    re.IGNORECASE,
)
_NON_EVENT_IDENTIFIERS = {
    "content_id",
    "feed_position",
    "session_id",
    "timestamp_epoch_ms",
    "user_id",
    "watch_duration_ms",
    "watch_pct",
    "watch_pct_at_skip",
}


def _event_declarations(text: str) -> list[str]:
    if not _EVENT_DECLARATION.search(text):
        return []
    return sorted(
        {
            match.group(0).casefold()
            for match in _MACHINE_IDENTIFIER.finditer(text)
            if match.group(0).casefold() not in _NON_EVENT_IDENTIFIERS
        }
    )


def _event_formula_operands(text: str) -> list[str]:
    operands: set[str] = set()
    for match in _EVENT_DIVISION.finditer(text):
        operands.update(
            {
                match.group("numerator").casefold(),
                match.group("denominator").casefold(),
            }
        )
    for match in _EVENT_INTERVAL.finditer(text):
        operands.update(
            {match.group("first").casefold(), match.group("second").casefold()}
        )
    for match in _EVENT_COUNT.finditer(text):
        operands.add(match.group("event").casefold())
    return sorted(operands)


def _timeline_rules(
    claims: list[ClaimOccurrence],
) -> dict[str, list[tuple[ClaimOccurrence, str]]]:
    rules: dict[str, list[tuple[ClaimOccurrence, str]]] = defaultdict(list)
    for claim in claims:
        for subject, value in _timeline_values(claim.quote):
            rules[subject].append((claim, value))
    return rules


def _timeline_values_conflict(values: list[str]) -> bool:
    unique = set(values)
    if len(unique) < 2:
        return False
    kinds = {value.split(":", maxsplit=1)[0] for value in unique}
    if kinds == {"date"}:
        return True
    if kinds != {"weeks"}:
        # An exact date and a relative range are not comparable without a
        # verified launch date, so deterministic analysis must abstain.
        return False
    ranges = [
        tuple(int(part) for part in value.split(":", maxsplit=2)[1].split("-"))
        for value in unique
    ]
    return max(low for low, _ in ranges) > min(high for _, high in ranges)


def _declared_events(
    claims: list[ClaimOccurrence],
) -> dict[str, list[ClaimOccurrence]]:
    declarations: dict[str, list[ClaimOccurrence]] = defaultdict(list)
    for claim in claims:
        for event in _declared_events_for_claim(claim):
            declarations[event].append(claim)
    return declarations


def _declared_events_for_claim(claim: ClaimOccurrence) -> list[str]:
    if claim.field_name != "events":
        return _event_declarations(claim.quote)
    return [
        match.group(0).casefold()
        for match in _MACHINE_IDENTIFIER.finditer(claim.quote)
        if match.group(0).casefold() not in _NON_EVENT_IDENTIFIERS
    ]


def _metric_formulas(
    claims: list[ClaimOccurrence],
) -> list[tuple[ClaimOccurrence, list[str]]]:
    formulas: list[tuple[ClaimOccurrence, list[str]]] = []
    for claim in claims:
        operands = _event_formula_operands(claim.quote)
        if operands:
            formulas.append((claim, operands))
    return formulas


def _enum_conflicts(
    claims: list[ClaimOccurrence],
) -> list[
    tuple[
        str,
        list[tuple[ClaimOccurrence, int]],
        list[tuple[ClaimOccurrence, int, int]],
    ]
]:
    assignments: dict[str, list[tuple[ClaimOccurrence, int]]] = defaultdict(list)
    domains_by_range: dict[
        tuple[tuple[str, ...], int, int], tuple[ClaimOccurrence, int, int]
    ] = {}
    for claim in claims:
        for match in _ENUM_ROW.finditer(claim.quote):
            label = match.group("label").lower()
            if label == "mid":
                label = "medium"
            assignments[label].append((claim, int(match.group("value"))))
        for match in _ENUM_DOMAIN.finditer(claim.quote):
            if "skip" in match.group("identifier").casefold():
                low = int(match.group("low"))
                high = int(match.group("high"))
                key = (_scope_keys(claim.quote), low, high)
                existing = domains_by_range.get(key)
                if existing is None or len(claim.quote) < len(existing[0].quote):
                    domains_by_range[key] = (claim, low, high)

    domains = list(domains_by_range.values())

    conflicts: list[
        tuple[
            str,
            list[tuple[ClaimOccurrence, int]],
            list[tuple[ClaimOccurrence, int, int]],
        ]
    ] = []
    for label, rules in sorted(assignments.items()):
        for scoped_rules in _groups_by_scope(rules):
            unique_values = {value for _, value in scoped_rules}
            applicable_domains = [
                domain
                for domain in domains
                if _scopes_compatible(scoped_rules[0][0].quote, domain[0].quote)
            ]
            outside_domain = any(
                value < low or value > high
                for _, value in scoped_rules
                for _, low, high in applicable_domains
            )
            if len(unique_values) > 1 or outside_domain:
                conflicts.append((label, scoped_rules, applicable_domains))
                break
    return conflicts


def _schema_conflicts(
    claims: list[ClaimOccurrence],
) -> list[tuple[str, list[tuple[ClaimOccurrence, str]]]]:
    declarations: dict[str, list[tuple[ClaimOccurrence, str]]] = defaultdict(list)
    for claim in claims:
        for field, schema_type in _schema_declarations(claim.quote):
            declarations[field].append((claim, schema_type))

    conflicts: list[tuple[str, list[tuple[ClaimOccurrence, str]]]] = []
    for field, rules in sorted(declarations.items()):
        for scoped_rules in _groups_by_scope(rules):
            if len({schema_type for _, schema_type in scoped_rules}) > 1:
                conflicts.append((field, scoped_rules))
                break
    return conflicts


_POLARITY_VALUES: dict[str, tuple[str, bool]] = {
    "enabled": ("enabled", True),
    "disabled": ("enabled", False),
    "allowed": ("allowed", True),
    "prohibited": ("allowed", False),
    "forbidden": ("allowed", False),
    "included": ("included", True),
    "excluded": ("included", False),
    "required": ("required", True),
    "optional": ("required", False),
}


def _polarity_conflicts(
    claims: list[ClaimOccurrence],
) -> list[tuple[str, str, list[tuple[ClaimOccurrence, bool]]]]:
    rules: dict[
        tuple[str, str], list[tuple[ClaimOccurrence, bool]]
    ] = defaultdict(list)
    for claim in claims:
        for match in _POLARITY.finditer(claim.quote):
            axis, positive = _POLARITY_VALUES[match.group("value").casefold()]
            rules[(match.group("subject").casefold(), axis)].append((claim, positive))

    conflicts: list[tuple[str, str, list[tuple[ClaimOccurrence, bool]]]] = []
    for (subject, axis), subject_rules in sorted(rules.items()):
        for scoped_rules in _groups_by_scope(subject_rules):
            if {positive for _, positive in scoped_rules} == {False, True}:
                conflicts.append((subject, axis, scoped_rules))
                break
    return conflicts


def _duplicate_ranks(
    claims: list[ClaimOccurrence],
) -> list[tuple[str, int, list[tuple[ClaimOccurrence, str]]]]:
    rules: dict[
        tuple[str, int], list[tuple[ClaimOccurrence, str]]
    ] = defaultdict(list)
    for claim in claims:
        for match in _RANK_ASSIGNMENT.finditer(claim.quote):
            key = (match.group("ranking").casefold(), int(match.group("rank")))
            rules[key].append((claim, match.group("item").casefold()))

    conflicts: list[tuple[str, int, list[tuple[ClaimOccurrence, str]]]] = []
    for (ranking, rank), rank_rules in sorted(rules.items()):
        for scoped_rules in _groups_by_scope(rank_rules):
            if len({item for _, item in scoped_rules}) > 1:
                conflicts.append((ranking, rank, scoped_rules))
                break
    return conflicts


def _precedence_cycles(
    claims: list[ClaimOccurrence],
) -> list[list[tuple[ClaimOccurrence, str, str]]]:
    by_scope: dict[
        tuple[str, ...], list[tuple[ClaimOccurrence, str, str]]
    ] = defaultdict(list)
    for claim in claims:
        for match in _PRECEDENCE.finditer(claim.quote):
            before = match.group("before").casefold()
            after = match.group("after").casefold()
            if before != after:
                by_scope[_scope_keys(claim.quote)].append((claim, before, after))

    cycles: dict[str, list[tuple[ClaimOccurrence, str, str]]] = {}
    for edges in by_scope.values():
        for edge in edges:
            path = _precedence_path(edges, edge[2], edge[1], {edge[1]})
            if path is None:
                continue
            cycle = [edge, *path]
            identity = "\x1f".join(sorted(item[0].claim_id for item in cycle))
            cycles.setdefault(identity, cycle)
    return [cycles[key] for key in sorted(cycles)]


def _precedence_path(
    edges: list[tuple[ClaimOccurrence, str, str]],
    current: str,
    target: str,
    visited: set[str],
) -> list[tuple[ClaimOccurrence, str, str]] | None:
    if current == target:
        return []
    if current in visited:
        return None
    next_visited = visited | {current}
    for edge in edges:
        if edge[1] != current:
            continue
        path = _precedence_path(edges, edge[2], target, next_visited)
        if path is not None:
            return [edge, *path]
    return None


def _schema_declarations(text: str) -> list[tuple[str, str]]:
    declarations: set[tuple[str, str]] = set()
    declarations.update(
        (match.group("field").casefold(), "array")
        for match in _SCHEMA_ARRAY.finditer(text)
    )
    for pattern in (_SCHEMA_TABLE, _SCHEMA_INLINE):
        declarations.update(
            (
                match.group("field").casefold(),
                _normalize_schema_type(match.group("type")),
            )
            for match in pattern.finditer(text)
        )
    return sorted(declarations)


def _normalize_schema_type(value: str) -> str:
    normalized = value.casefold()
    if normalized in {"array", "list"}:
        return "array"
    if normalized.startswith("int") or normalized in {"float", "number"}:
        return "number"
    if normalized in {"bool", "boolean"}:
        return "boolean"
    return "string"


def _groups_by_scope(
    rules: list[tuple[ClaimOccurrence, int | str]],
) -> list[list[tuple[ClaimOccurrence, int | str]]]:
    groups: dict[tuple[str, ...], list[tuple[ClaimOccurrence, int | str]]] = (
        defaultdict(list)
    )
    for rule in rules:
        groups[_scope_keys(rule[0].quote)].append(rule)
    return [groups[key] for key in sorted(groups)]


def _scope_keys(text: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            normalize_for_match(match.group(0)).rstrip(".,;:")
            for match in _EXPLICIT_SCOPE.finditer(text)
        )
    )


def _scopes_compatible(first: str, second: str) -> bool:
    first_scope = _scope_keys(first)
    second_scope = _scope_keys(second)
    return first_scope == second_scope


def _build_requirement_graph(claims: list[ClaimOccurrence]) -> RequirementGraph:
    nodes: dict[str, RequirementGraphNode] = {}
    edges: dict[str, RequirementGraphEdge] = {}

    def add_node(node: RequirementGraphNode) -> None:
        nodes.setdefault(node.node_id, node)

    def add_edge(
        source_id: str,
        target_id: str,
        relation: GraphEdgeKind,
        claim_id: str,
    ) -> None:
        identity = "\x1f".join([source_id, target_id, relation, claim_id])
        edge_id = hashlib.sha256(identity.encode()).hexdigest()[:20]
        edges.setdefault(
            edge_id,
            RequirementGraphEdge(
                edge_id=edge_id,
                source_id=source_id,
                target_id=target_id,
                relation=relation,
                claim_id=claim_id,
            ),
        )

    for claim in claims:
        claim_node_id = "claim:" + claim.claim_id
        add_node(
            RequirementGraphNode(
                node_id=claim_node_id,
                kind="claim",
                label=claim.quote,
                claim_id=claim.claim_id,
            )
        )
        for subject, value in _timeline_values(claim.quote):
            milestone_id = f"milestone:{subject}:{value}"
            add_node(
                RequirementGraphNode(
                    node_id=milestone_id,
                    kind="milestone",
                    label=f"{_display_key(subject)} at {_display_timeline(value)}",
                )
            )
            add_edge(claim_node_id, milestone_id, "scheduled_on", claim.claim_id)
        for event in _declared_events_for_claim(claim):
            event_id = "event:" + event
            add_node(
                RequirementGraphNode(node_id=event_id, kind="event", label=event)
            )
            add_edge(claim_node_id, event_id, "declares_event", claim.claim_id)
        operands = _event_formula_operands(claim.quote)
        if operands:
            metric_id = "metric:" + claim.claim_id
            add_node(
                RequirementGraphNode(
                    node_id=metric_id,
                    kind="metric",
                    label="Derived metric",
                    claim_id=claim.claim_id,
                )
            )
            add_edge(claim_node_id, metric_id, "computes_metric", claim.claim_id)
            for event in operands:
                event_id = "event:" + event
                add_node(
                    RequirementGraphNode(node_id=event_id, kind="event", label=event)
                )
                add_edge(metric_id, event_id, "computed_from", claim.claim_id)
    return RequirementGraph(
        nodes=sorted(nodes.values(), key=lambda node: node.node_id),
        edges=sorted(edges.values(), key=lambda edge: edge.edge_id),
    )


def _display_key(value: str) -> str:
    return value.replace("_", " ")


def _display_timeline(value: str) -> str:
    if value.startswith("date:"):
        return value.removeprefix("date:")
    if value.startswith("weeks:"):
        span = value.removeprefix("weeks:").split(":", maxsplit=1)[0]
        low, high = span.split("-", maxsplit=1)
        return (
            f"{low} week(s) post-launch"
            if low == high
            else f"{low}-{high} weeks post-launch"
        )
    return value


def _finding_evidence(claim: ClaimOccurrence) -> FindingEvidence:
    return FindingEvidence(
        claim_id=claim.claim_id,
        quote=claim.quote,
        page=claim.page,
        section=claim.section,
        source_block_id=claim.source_block_id,
    )


def _affected_consumers(rubric: Rubric, claims: list[ClaimOccurrence]) -> list[str]:
    consumers = {
        consumer.value
        for claim in claims
        for consumer in rubric.criterion(claim.criterion_id).consumers
    }
    return sorted(consumers)


def _impossible_range_finding(
    rubric: Rubric, claim: ClaimOccurrence, expression: str
) -> DeepReviewFinding:
    finding_id = "impossible-range-" + claim.claim_id
    return DeepReviewFinding(
        finding_id=finding_id,
        kind="impossible_range",
        title="A requirement contains an impossible numeric range",
        summary=f'"{expression}" cannot be satisfied because its lower bound exceeds its upper bound.',
        evidence=[_finding_evidence(claim)],
        affected_consumers=_affected_consumers(rubric, [claim]),
        implementation_consequence=(
            "Engineering and QA cannot classify any value consistently from this rule."
        ),
        required_decision=(
            "Correct the inequality and publish one canonical interval with explicit boundary ownership."
        ),
        review_order=0,
    )


def _threshold_finding(
    rubric: Rubric,
    label: str,
    rules: list[tuple[ClaimOccurrence, str]],
) -> DeepReviewFinding:
    by_expression: dict[str, ClaimOccurrence] = {}
    for claim, expression in rules:
        by_expression.setdefault(expression, claim)
    selected = [by_expression[key] for key in sorted(by_expression)]
    identity = "\x1f".join([label] + [claim.claim_id for claim in selected])
    return DeepReviewFinding(
        finding_id="conflicting-threshold-" + hashlib.sha256(identity.encode()).hexdigest()[:16],
        kind="conflicting_threshold",
        title=f"Conflicting {label}-skip thresholds",
        summary=(
            f"The PRD assigns {len(by_expression)} different numeric definitions "
            f"to the same {label}-skip classification."
        ),
        evidence=[_finding_evidence(claim) for claim in selected],
        affected_consumers=_affected_consumers(rubric, selected),
        implementation_consequence=(
            "Clients, analytics, persona computation, ranking, and QA may classify the same interaction differently."
        ),
        required_decision=(
            f"Choose one canonical {label}-skip threshold and identify which conflicting passages it supersedes."
        ),
        review_order=1,
    )


def _timeline_finding(
    rubric: Rubric,
    milestone: str,
    rules: list[tuple[ClaimOccurrence, str]],
) -> DeepReviewFinding:
    by_value: dict[str, ClaimOccurrence] = {}
    for claim, value in rules:
        by_value.setdefault(value, claim)
    selected = [by_value[key] for key in sorted(by_value)]
    identity = "\x1f".join([milestone] + sorted(by_value))
    label = _display_key(milestone)
    values = ", ".join(_display_timeline(value) for value in sorted(by_value))
    return DeepReviewFinding(
        finding_id="conflicting-timeline-"
        + hashlib.sha256(identity.encode()).hexdigest()[:16],
        kind="conflicting_timeline",
        title=f"Conflicting {label} timelines",
        summary=f"The PRD schedules {label} at incompatible times: {values}.",
        evidence=[_finding_evidence(claim) for claim in selected],
        affected_consumers=_affected_consumers(rubric, selected),
        implementation_consequence=(
            "Teams cannot plan dependencies, launch readiness, or downstream milestones against one authoritative schedule."
        ),
        required_decision=(
            f"Choose one canonical {label} timeline and identify which conflicting passages it supersedes."
        ),
        review_order=2,
    )


def _metric_finding(
    rubric: Rubric,
    formula_claim: ClaimOccurrence,
    missing: list[str],
    declared_events: dict[str, list[ClaimOccurrence]],
) -> DeepReviewFinding:
    declaration_claims: list[ClaimOccurrence] = []
    for event in sorted(declared_events):
        claim = declared_events[event][0]
        if claim.claim_id not in {item.claim_id for item in declaration_claims}:
            declaration_claims.append(claim)
        if len(declaration_claims) == 2:
            break
    evidence_claims = [formula_claim] + declaration_claims
    rendered_missing = ", ".join(missing)
    return DeepReviewFinding(
        finding_id="metric-not-computable-" + formula_claim.claim_id,
        kind="metric_not_computable",
        title="The success metric references undeclared events",
        summary=(
            f"The metric formula requires {rendered_missing}, but the PRD's "
            "explicit event declarations do not define that event."
        ),
        evidence=[_finding_evidence(claim) for claim in evidence_claims],
        affected_consumers=_affected_consumers(rubric, evidence_claims),
        implementation_consequence=(
            "Data and engineering cannot compute the stated metric from the specified instrumentation."
        ),
        required_decision=(
            f"Define and instrument {rendered_missing}, or revise the formula to use declared events."
        ),
        review_order=3,
    )


def _enum_finding(
    rubric: Rubric,
    label: str,
    rules: list[tuple[ClaimOccurrence, int]],
    domains: list[tuple[ClaimOccurrence, int, int]],
) -> DeepReviewFinding:
    by_value: dict[int, ClaimOccurrence] = {}
    for claim, value in rules:
        by_value.setdefault(value, claim)
    domain_claims: dict[str, ClaimOccurrence] = {
        claim.claim_id: claim for claim, _, _ in domains
    }
    selected = [by_value[value] for value in sorted(by_value)] + list(
        domain_claims.values()
    )
    identity = "\x1f".join([label] + [claim.claim_id for claim in selected])
    values = ", ".join(f"tier {value}" for value in sorted(by_value))
    return DeepReviewFinding(
        finding_id="enum-domain-conflict-"
        + hashlib.sha256(identity.encode()).hexdigest()[:16],
        kind="enum_domain_conflict",
        title=f"Conflicting {label}-skip tier definitions",
        summary=(
            f"The same {label}-skip classification maps to incompatible enum "
            f"values ({values}) or falls outside its declared tier domain."
        ),
        evidence=[_finding_evidence(claim) for claim in selected],
        affected_consumers=_affected_consumers(rubric, selected),
        implementation_consequence=(
            "Producers, persisted state, ranking consumers, and QA cannot share one enum contract."
        ),
        required_decision=(
            f"Define one tier domain and map every {label}-skip rule and example to it."
        ),
        review_order=1,
    )


def _schema_finding(
    rubric: Rubric,
    field: str,
    declarations: list[tuple[ClaimOccurrence, str]],
) -> DeepReviewFinding:
    by_type: dict[str, ClaimOccurrence] = {}
    for claim, schema_type in declarations:
        by_type.setdefault(schema_type, claim)
    selected = [by_type[schema_type] for schema_type in sorted(by_type)]
    identity = "\x1f".join([field] + sorted(by_type))
    types = ", ".join(sorted(by_type))
    return DeepReviewFinding(
        finding_id="schema-type-conflict-"
        + hashlib.sha256(identity.encode()).hexdigest()[:16],
        kind="schema_type_conflict",
        title=f"Conflicting types for {field}",
        summary=f'The field "{field}" is declared with incompatible types: {types}.',
        evidence=[_finding_evidence(claim) for claim in selected],
        affected_consumers=_affected_consumers(rubric, selected),
        implementation_consequence=(
            "Producers and consumers can serialize incompatible payloads, preventing one reliable contract and test oracle."
        ),
        required_decision=(
            f"Choose the cardinality and type for {field}, then define nullability and compatibility behavior."
        ),
        review_order=2,
    )


def _polarity_finding(
    rubric: Rubric,
    subject: str,
    axis: str,
    rules: list[tuple[ClaimOccurrence, bool]],
) -> DeepReviewFinding:
    by_polarity: dict[bool, ClaimOccurrence] = {}
    for claim, positive in rules:
        by_polarity.setdefault(positive, claim)
    selected = [by_polarity[False], by_polarity[True]]
    identity = "\x1f".join([subject, axis] + sorted(claim.claim_id for claim in selected))
    return DeepReviewFinding(
        finding_id="opposite-polarity-"
        + hashlib.sha256(identity.encode()).hexdigest()[:16],
        kind="opposite_polarity",
        title=f"Opposite requirements for {subject}",
        summary=(
            f'The exact subject "{subject}" is explicitly both positive and '
            f"negative on the {axis} decision."
        ),
        evidence=[_finding_evidence(claim) for claim in selected],
        affected_consumers=_affected_consumers(rubric, selected),
        implementation_consequence=(
            "Implementers and QA cannot choose one observable behavior for the same explicit switch or policy."
        ),
        required_decision=(
            f"Choose the authoritative {axis} state for {subject} and mark the other statement superseded or differently scoped."
        ),
        review_order=1,
    )


def _duplicate_rank_finding(
    rubric: Rubric,
    ranking: str,
    rank: int,
    rules: list[tuple[ClaimOccurrence, str]],
) -> DeepReviewFinding:
    by_item: dict[str, ClaimOccurrence] = {}
    for claim, item in rules:
        by_item.setdefault(item, claim)
    selected = [by_item[item] for item in sorted(by_item)]
    items = ", ".join(sorted(by_item))
    identity = "\x1f".join([ranking, str(rank), *sorted(by_item)])
    return DeepReviewFinding(
        finding_id="duplicate-rank-"
        + hashlib.sha256(identity.encode()).hexdigest()[:16],
        kind="duplicate_rank",
        title=f"Duplicate rank {rank} in {ranking}",
        summary=f"The ranking assigns rank {rank} to multiple items: {items}.",
        evidence=[_finding_evidence(claim) for claim in selected],
        affected_consumers=_affected_consumers(rubric, selected),
        implementation_consequence=(
            "The ordered rule set has no deterministic winner at the duplicated position."
        ),
        required_decision=(
            f"Assign one item to each {ranking} rank or define an explicit tie-break."
        ),
        review_order=1,
    )


def _precedence_cycle_finding(
    rubric: Rubric,
    cycle: list[tuple[ClaimOccurrence, str, str]],
) -> DeepReviewFinding:
    selected: list[ClaimOccurrence] = []
    for claim, _, _ in cycle:
        if claim.claim_id not in {item.claim_id for item in selected}:
            selected.append(claim)
    rendered = " -> ".join([cycle[0][1], *[after for _, _, after in cycle]])
    identity = "\x1f".join(sorted(claim.claim_id for claim in selected))
    return DeepReviewFinding(
        finding_id="precedence-cycle-"
        + hashlib.sha256(identity.encode()).hexdigest()[:16],
        kind="precedence_cycle",
        title="The precedence rules contain a cycle",
        summary=f"The explicit ordering cannot be satisfied: {rendered}.",
        evidence=[_finding_evidence(claim) for claim in selected],
        affected_consumers=_affected_consumers(rubric, selected),
        implementation_consequence=(
            "No implementation can satisfy every ordering edge, so different components may resolve the cycle differently."
        ),
        required_decision=(
            "Remove at least one ordering edge and publish one acyclic authoritative precedence order."
        ),
        review_order=1,
    )
