"""Measure deep review against a synthetic proxy label artifact.

This answers one question: when Forge already knows a defect exists, does the
current pipeline surface it, offer it for classification, or miss it entirely?

It is a transfer diagnostic, never calibration. The labels are AI-produced
(D-048), so a good score here means the detectors reproduce a synthetic panel,
not that they agree with human reviewers. Precision against real documents
still requires the blinded human study in `docs/VALIDATION_PROTOCOL.md`.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from forge.proxy_labels import ProxyLabel, verify_proxy_artifact
from forge.score.consistency import build_consistency_candidates
from forge.service import assess_extraction_json

# A finding covers a label when it cites the same source text the label cites.
# Multi-quote labels must match at least two quotes so a single shared sentence
# cannot claim credit for a cross-section conflict.
_REQUIRED_QUOTE_MATCHES = 2


class LabelOutcome(BaseModel):
    label_id: str
    consensus_status: str
    blocker_status: str
    finding_matched: bool
    candidate_matched: bool
    matched_finding_ids: list[str] = Field(default_factory=list)
    matched_finding_kinds: list[str] = Field(default_factory=list)


class Rate(BaseModel):
    matched: int
    total: int
    rate: float | None


class ProxyDiagnosticReport(BaseModel):
    source_path: str
    source_sha256: str
    artifact_id: str
    label_authority: Literal["synthetic_ai_proxy"] = "synthetic_ai_proxy"
    calibration_eligible: Literal[False] = False
    finding_count: int
    candidate_count: int
    finding_recall: Rate
    blocker_finding_recall: Rate
    candidate_or_finding_coverage: Rate
    unmatched_findings: list[str] = Field(default_factory=list)
    hard_negative_violations: list[str] = Field(default_factory=list)
    findings_by_kind: dict[str, int] = Field(default_factory=dict)
    outcomes: list[LabelOutcome] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def run_proxy_diagnostics(
    artifact_path: Path, *, workspace_root: Path
) -> ProxyDiagnosticReport:
    artifact = verify_proxy_artifact(artifact_path, workspace_root=workspace_root)
    source = workspace_root / artifact.document.source_path

    # Deterministic path only: no model runs, so this measures what Forge can
    # find on its own rather than what a particular model produced today.
    response = assess_extraction_json(str(source), '{"criteria": []}')
    review = response.deep_review
    findings = review.findings if review else []
    claims = review.claims if review else []
    candidates = build_consistency_candidates(
        claims, proven_claim_pairs=_proven_pairs(findings)
    )

    finding_quotes = {
        finding.finding_id: [_normalize(item.quote) for item in finding.evidence]
        for finding in findings
    }
    candidate_quotes = [
        [_normalize(candidate.left_quote), _normalize(candidate.right_quote)]
        for candidate in candidates
    ]

    outcomes: list[LabelOutcome] = []
    matched_finding_ids: set[str] = set()
    hard_negative_violations: list[str] = []

    for label in artifact.labels:
        quotes = [_fragments(item.quote) for item in label.evidence]
        required = min(_REQUIRED_QUOTE_MATCHES, len(quotes))

        hits = [
            finding_id
            for finding_id, evidence in finding_quotes.items()
            if _covered(quotes, evidence) >= required
        ]
        candidate_hit = any(
            _covered(quotes, pair) >= required for pair in candidate_quotes
        )

        if label.consensus_status == "supported":
            matched_finding_ids.update(hits)
        elif hits:
            # A published finding on a hard negative or compatible pair is the
            # expensive failure: it accuses the author of a defect that the
            # panel explicitly rejected.
            hard_negative_violations.append(label.label_id)
            matched_finding_ids.update(hits)

        outcomes.append(
            LabelOutcome(
                label_id=label.label_id,
                consensus_status=label.consensus_status,
                blocker_status=label.blocker_status,
                finding_matched=bool(hits),
                candidate_matched=candidate_hit,
                matched_finding_ids=sorted(hits),
                matched_finding_kinds=sorted(
                    {
                        finding.kind
                        for finding in findings
                        if finding.finding_id in hits
                    }
                ),
            )
        )

    supported = [
        label for label in artifact.labels if label.consensus_status == "supported"
    ]
    supported_ids = {label.label_id for label in supported}
    blockers = [
        label for label in supported if label.blocker_status == "implementation_blocker"
    ]
    blocker_ids = {label.label_id for label in blockers}
    by_id = {outcome.label_id: outcome for outcome in outcomes}

    notes = [
        "Synthetic proxy labels (D-048). This is a transfer diagnostic and "
        "cannot establish precision, calibration, or organization validity.",
        "Unmatched findings are not necessarily false positives; they may be "
        "real defects the proxy panel did not record.",
    ]
    if hard_negative_violations:
        notes.append(
            "A finding fired on a label the panel rejected; investigate before "
            "adding further detectors."
        )

    return ProxyDiagnosticReport(
        source_path=artifact.document.source_path,
        source_sha256=artifact.document.source_sha256,
        artifact_id=artifact.artifact_id,
        finding_count=len(findings),
        candidate_count=len(candidates),
        finding_recall=_rate(
            sum(1 for label_id in supported_ids if by_id[label_id].finding_matched),
            len(supported_ids),
        ),
        blocker_finding_recall=_rate(
            sum(1 for label_id in blocker_ids if by_id[label_id].finding_matched),
            len(blocker_ids),
        ),
        candidate_or_finding_coverage=_rate(
            sum(
                1
                for label_id in supported_ids
                if by_id[label_id].finding_matched or by_id[label_id].candidate_matched
            ),
            len(supported_ids),
        ),
        unmatched_findings=sorted(
            finding.finding_id
            for finding in findings
            if finding.finding_id not in matched_finding_ids
        ),
        hard_negative_violations=sorted(hard_negative_violations),
        findings_by_kind=_counts(finding.kind for finding in findings),
        outcomes=sorted(outcomes, key=lambda outcome: outcome.label_id),
        notes=notes,
    )


def _proven_pairs(findings) -> set[tuple[str, str]]:
    """Claim pairs a deterministic finding already cites together."""
    pairs: set[tuple[str, str]] = set()
    for finding in findings:
        claim_ids = sorted({item.claim_id for item in finding.evidence})
        for position, left in enumerate(claim_ids):
            for right in claim_ids[position + 1 :]:
                pairs.add((left, right))
    return pairs


def _covered(label_quotes: list[list[str]], evidence: list[str]) -> int:
    """Count label quotes whose text appears in the cited evidence.

    A label quote lifted from a PDF table often spans several lines, while a
    claim is one line. Comparing whole strings would therefore score a correct
    finding as a miss, so each quote matches when the evidence contains the
    whole span or any one substantial line of it.
    """
    return sum(
        1
        for fragments in label_quotes
        if any(
            fragment in item or item in fragment
            for fragment in fragments
            for item in evidence
        )
    )


def _fragments(quote: str) -> list[str]:
    whole = _normalize(quote)
    lines = [_normalize(line) for line in quote.splitlines()]
    return [whole] + [line for line in lines if len(line) >= 12 and line != whole]


def _counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _rate(matched: int, total: int) -> Rate:
    return Rate(
        matched=matched,
        total=total,
        rate=round(matched / total, 4) if total else None,
    )


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Measure deep-review coverage against a synthetic proxy label "
            "artifact. Diagnostic only; never calibration."
        )
    )
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--workspace-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    report = run_proxy_diagnostics(
        args.artifact, workspace_root=args.workspace_root.resolve()
    )
    print(json.dumps(report.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
