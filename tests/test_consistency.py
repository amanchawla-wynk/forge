from __future__ import annotations

import json

from forge.deep_review import mechanical_claim_occurrences
from forge.ingest.document import ingest_document
from forge.rubric.loader import load_rubric
from forge.score.consistency import (
    ConsistencyRelation,
    build_consistency_candidates,
    build_consistency_prompt,
    consistency_findings,
    consolidate_consistency_ledgers,
    parse_consistency_classification,
    verify_consistency_ledger,
)
from forge.service import assess_extraction_json

_SOURCE = (
    "Mood picker is shown after 3 consecutive hard skips.\n"
    "Mood picker is shown after 5 consecutive hard skips.\n"
)


def _claims(tmp_path):
    path = tmp_path / "prd.md"
    path.write_text(_SOURCE)
    document = ingest_document(path)
    return path, document, mechanical_claim_occurrences(document, [])


def _completion(candidates, relation_index: int) -> str:
    return json.dumps(
        {
            "relations": [
                {"candidate": position, "relation": relation_index}
                for position, _ in enumerate(candidates, start=1)
            ]
        }
    )


def test_candidates_pair_only_statements_sharing_a_named_subject(tmp_path):
    _, _, claims = _claims(tmp_path)

    candidates = build_consistency_candidates(claims)

    assert len(candidates) == 1
    assert candidates[0].subject_key == "skip:hard"
    assert candidates[0].left_quote != candidates[0].right_quote
    prompt = build_consistency_prompt(candidates)
    assert '{"relations": [{"candidate": <int>, "relation": <int>}]}' in prompt
    assert "Return JSON only." in prompt


def test_classified_conflict_becomes_an_advisory_finding(tmp_path):
    path, document, claims = _claims(tmp_path)
    candidates = build_consistency_candidates(claims)
    ledger = verify_consistency_ledger(
        document,
        consolidate_consistency_ledgers(
            [
                parse_consistency_classification(_completion(candidates, 2), candidates)
                for _ in range(3)
            ]
        ),
    )

    assert [item.relation for item in ledger.items] == [
        ConsistencyRelation.SCOPED_CONTRADICTION
    ]

    findings = consistency_findings(load_rubric("prd"), ledger, claims)
    assert len(findings) == 1
    assert findings[0].kind == "scoped_contradiction"
    assert findings[0].confidence == "classified"
    assert len(findings[0].evidence) == 2

    response = assess_extraction_json(
        str(path), '{"criteria": []}', consistency_ledger=ledger
    )
    kinds = {finding.kind for finding in response.deep_review.findings}
    assert "scoped_contradiction" in kinds
    assert response.consistency_ledger is not None
    assert any("advisory" in warning for warning in response.warnings)


def test_compatible_and_disagreeing_runs_publish_nothing(tmp_path):
    path, document, claims = _claims(tmp_path)
    candidates = build_consistency_candidates(claims)

    compatible = verify_consistency_ledger(
        document,
        consolidate_consistency_ledgers(
            [
                parse_consistency_classification(_completion(candidates, 4), candidates)
                for _ in range(3)
            ]
        ),
    )
    assert compatible.publishable == []

    disputed = consolidate_consistency_ledgers(
        [
            parse_consistency_classification(_completion(candidates, index), candidates)
            for index in (1, 2, 4)
        ]
    )
    assert disputed.items[0].relation is ConsistencyRelation.UNCLEAR

    response = assess_extraction_json(
        str(path), '{"criteria": []}', consistency_ledger=compatible
    )
    assert not any(
        finding.confidence == "classified"
        for finding in response.deep_review.findings
    )


def test_malformed_and_unverifiable_classifications_fail_safe(tmp_path):
    _, document, claims = _claims(tmp_path)
    candidates = build_consistency_candidates(claims)

    for invalid in (
        "not json",
        json.dumps({"relations": []}),
        json.dumps({"relations": [{"candidate": 1, "relation": 9}]}),
        json.dumps({"relations": [{"candidate": 1, "relation": True}]}),
        json.dumps({"relations": [{"candidate": 2, "relation": 1}]}),
        json.dumps({"relations": [{"candidate": 1, "relation": 1}], "extra": 1}),
    ):
        assert parse_consistency_classification(invalid, candidates) is None

    parsed = parse_consistency_classification(_completion(candidates, 1), candidates)
    assert parsed is not None
    parsed.items[0].left_quote = "A quote that is not in the document."
    verified = verify_consistency_ledger(document, parsed)
    assert verified.items[0].verified is False
    assert verified.items[0].relation is ConsistencyRelation.UNCLEAR
    assert verified.publishable == []


def test_category_pairing_needs_shared_vocabulary(tmp_path):
    path = tmp_path / "lifetime-prd.md"
    path.write_text(
        "The chosen filter is kept only for the same session.\n"
        "The chosen filter is stored for the last 30 days.\n"
        "Invoices are retained for seven years.\n"
    )
    document = ingest_document(path)
    claims = mechanical_claim_occurrences(document, [])

    subjects = {
        candidate.subject_key
        for candidate in build_consistency_candidates(claims)
    }

    # The two filter statements share concrete vocabulary; the unrelated
    # retention sentence must not be paired with them.
    assert any(subject.startswith("lifetime:") for subject in subjects)
    assert not any("invoices" in subject for subject in subjects)


def test_duplicate_text_and_proven_pairs_are_not_classified(tmp_path):
    path = tmp_path / "duplicate-prd.md"
    path.write_text(
        "Hard skip means watch duration <= 5 secs.\n"
        "Hard skip means watch duration >= 9 secs.\n"
        "Hard skip means watch duration <= 5 secs.\n"
        "Hard skip means watch duration >= 9 secs.\n"
    )
    document = ingest_document(path)
    claims = mechanical_claim_occurrences(document, [])

    candidates = build_consistency_candidates(claims)
    texts = [
        tuple(sorted((candidate.left_quote, candidate.right_quote)))
        for candidate in candidates
    ]
    assert len(texts) == len(set(texts))

    first = candidates[0]
    remaining = build_consistency_candidates(
        claims,
        proven_claim_pairs={
            tuple(sorted((first.left_claim_id, first.right_claim_id)))
        },
    )
    assert all(
        candidate.candidate_id != first.candidate_id for candidate in remaining
    )


def test_implied_exception_and_ambiguous_scope_use_fixed_findings(tmp_path):
    _, document, claims = _claims(tmp_path)
    candidates = build_consistency_candidates(claims)

    for relation_index, expected_kind in (
        (5, "implied_exception"),
        (6, "ambiguous_scope"),
    ):
        parsed = parse_consistency_classification(
            _completion(candidates, relation_index), candidates
        )
        assert parsed is not None
        ledger = verify_consistency_ledger(document, parsed)
        findings = consistency_findings(load_rubric("prd"), ledger, claims)
        assert [finding.kind for finding in findings] == [expected_kind]
        assert findings[0].confidence == "classified"
        assert len(findings[0].evidence) == 2
