from __future__ import annotations

import json

from forge.ingest.batching import batch_document, plan_fingerprint
from forge.ingest.document import ingest_document
from forge.rubric.loader import load_rubric
from forge.service import assess_extraction_json


def _empty_criteria():
    rubric = load_rubric("prd")
    return [
        {
            "criterion_id": criterion.id,
            "fields": [
                {"name": field.name, "value": None, "evidence": None}
                for field in criterion.fields
            ],
        }
        for criterion in rubric.criteria
    ]


def _set_requirement(criteria, quote: str) -> None:
    extraction = next(
        item
        for item in criteria
        if item["criterion_id"] == "functional_requirements"
    )
    field = next(item for item in extraction["fields"] if item["name"] == "requirements")
    field["value"] = [quote]
    field["evidence"] = {"quote": quote}


def test_deep_review_preserves_cross_batch_claims_and_finds_threshold_conflicts(
    tmp_path,
):
    first = "Hard skip means watch duration <= 5 secs."
    second = (
        "Hard skip means watch duration >= 5 secs, while soft skip uses "
        "21secs>=X>=40secs."
    )
    path = tmp_path / "conflicting-prd.md"
    path.write_text(first + (" Neutral context." * 9_000) + " " + second)

    batches = batch_document(ingest_document(path))
    assert len(batches) > 1
    rubric = load_rubric("prd")
    fingerprint = plan_fingerprint(batches, rubric.version)
    fragments = []
    for batch in batches:
        criteria = _empty_criteria()
        if first in batch.document.text:
            _set_requirement(criteria, first)
        if second in batch.document.text:
            _set_requirement(criteria, second)
        fragments.append(
            {
                "batch_id": batch.id,
                "plan_fingerprint": fingerprint,
                "criteria": criteria,
            }
        )

    response = assess_extraction_json(
        str(path), json.dumps({"runs": [{"fragments": fragments}]})
    )

    claims = response.deep_review.claims
    assert {claim.quote for claim in claims} == {first, second}
    assert all(claim.quote_start_char is not None for claim in claims)
    assert all(claim.quote_end_char is not None for claim in claims)

    findings = response.deep_review.findings
    assert [finding.kind for finding in findings] == [
        "impossible_range",
        "conflicting_threshold",
    ]
    impossible = findings[0]
    assert impossible.evidence[0].quote == second
    assert "lower bound exceeds its upper bound" in impossible.summary

    conflict = findings[1]
    assert len(conflict.evidence) == 2
    assert "canonical hard-skip threshold" in conflict.required_decision
    assert response.deep_review.advisory


def test_deep_review_merges_repeated_run_observations(tmp_path):
    quote = "Hard skip means watch duration <= 5 secs."
    path = tmp_path / "prd.md"
    path.write_text(quote)
    payload = {
        "criteria": [
            {
                "criterion_id": "functional_requirements",
                "fields": [
                    {
                        "name": "requirements",
                        "value": [quote],
                        "evidence": {"quote": quote},
                    }
                ],
            }
        ]
    }

    response = assess_extraction_json(
        str(path), json.dumps({"runs": [payload, payload, payload]})
    )

    assert len(response.deep_review.claims) == 1
    assert response.deep_review.claims[0].run_indexes == [1, 2, 3]
    assert response.deep_review.findings == []


def test_deep_review_exposes_deterministic_claim_interpretations(tmp_path):
    quote = "Product 1 hard skip must be disabled in Phase 2."
    path = tmp_path / "interpreted-prd.md"
    path.write_text(quote)

    response = assess_extraction_json(str(path), '{"criteria": []}')

    claim = next(item for item in response.deep_review.claims if item.quote == quote)
    interpretation = next(
        item
        for item in response.deep_review.interpretations
        if item.claim_id == claim.claim_id
    )
    assert interpretation.subject_keys == ["skip:hard"]
    assert interpretation.scope_keys == ["phase 2", "product 1"]
    assert interpretation.phase_keys == ["phase 2"]
    assert interpretation.modality == "must"
    assert interpretation.provenance == "deterministic"


def test_deep_review_finds_conflicting_relative_timelines(tmp_path):
    first = "Trending feed goes live 2-3 weeks post-launch."
    second = "Top trending contents go live 4-5 weeks after initial launch."
    path = tmp_path / "timeline-prd.md"
    path.write_text(first + "\n" + second)

    response = assess_extraction_json(str(path), '{"criteria": []}')

    findings = [
        finding
        for finding in response.deep_review.findings
        if finding.kind == "conflicting_timeline"
    ]
    assert len(findings) == 1
    assert {item.quote for item in findings[0].evidence} == {first, second}
    assert "2-3 weeks post-launch" in findings[0].summary
    assert "4-5 weeks post-launch" in findings[0].summary
    assert any(
        edge.relation == "scheduled_on"
        for edge in response.deep_review.graph.edges
    )


def test_deep_review_normalizes_equivalent_exact_dates(tmp_path):
    path = tmp_path / "dates-prd.md"
    path.write_text(
        "General availability is scheduled for 2026-10-02.\n"
        "GA is scheduled for October 2, 2026.\n"
        "Beta launch is scheduled for October 1, 2026."
    )

    response = assess_extraction_json(str(path), '{"criteria": []}')

    assert not any(
        finding.kind == "conflicting_timeline"
        for finding in response.deep_review.findings
    )


def test_deep_review_does_not_call_overlapping_timeline_ranges_a_conflict(tmp_path):
    path = tmp_path / "overlapping-timeline-prd.md"
    path.write_text(
        "Trending feed goes live 2-4 weeks post-launch.\n"
        "Top trending contents go live 2-3 weeks after MVP launch."
    )

    response = assess_extraction_json(str(path), '{"criteria": []}')

    assert not any(
        finding.kind == "conflicting_timeline"
        for finding in response.deep_review.findings
    )


def test_deep_review_finds_metric_formula_with_undeclared_event(tmp_path):
    declaration = "Track checkout_started and purchase_completed."
    formula = "Checkout conversion is checkout_started / checkout_completed."
    path = tmp_path / "metric-prd.md"
    path.write_text(declaration + "\n" + formula)

    response = assess_extraction_json(str(path), '{"criteria": []}')

    findings = [
        finding
        for finding in response.deep_review.findings
        if finding.kind == "metric_not_computable"
    ]
    assert len(findings) == 1
    assert "checkout_completed" in findings[0].summary
    assert findings[0].evidence[0].quote == formula
    relations = {edge.relation for edge in response.deep_review.graph.edges}
    assert {"declares_event", "computes_metric", "computed_from"} <= relations


def test_deep_review_abstains_when_no_events_are_declared(tmp_path):
    path = tmp_path / "metric-prd.md"
    path.write_text("Conversion is checkout_started / checkout_completed.")

    response = assess_extraction_json(str(path), '{"criteria": []}')

    assert not any(
        finding.kind == "metric_not_computable"
        for finding in response.deep_review.findings
    )


def test_deep_review_accepts_complete_formula_and_ignores_deadlines(tmp_path):
    path = tmp_path / "complete-measurement-prd.md"
    path.write_text(
        "Track refund_requested and refund_settled.\n"
        "Refund completion is refund_settled / refund_requested.\n"
        "General availability must happen by October 2, 2026.\n"
        "GA must happen by October 15, 2026."
    )

    response = assess_extraction_json(str(path), '{"criteria": []}')

    assert not any(
        finding.kind in {"metric_not_computable", "conflicting_timeline"}
        for finding in response.deep_review.findings
    )


def test_deep_review_finds_enum_domain_and_schema_type_conflicts(tmp_path):
    path = tmp_path / "contracts-prd.md"
    path.write_text(
        "Hard skip on preview\n"
        "watch duration <= 5 secs\n"
        "Tier 3\n"
        "Hard\n"
        "2 secs\n"
        "Tier 1\n"
        "skip_tiers: { content_id -> tier (0-2) }\n"
        "Event fields: content_id, genre_tags[], language\n"
        "genre_tags\n"
        "string\n"
        "No\n"
        "All genre tags attached to this item"
    )

    response = assess_extraction_json(str(path), '{"criteria": []}')
    by_kind = {finding.kind: finding for finding in response.deep_review.findings}

    enum_finding = by_kind["enum_domain_conflict"]
    assert len(enum_finding.evidence) == 3
    assert "tier 1, tier 3" in enum_finding.summary
    assert "one tier domain" in enum_finding.required_decision

    schema_finding = by_kind["schema_type_conflict"]
    assert len(schema_finding.evidence) == 2
    assert '"genre_tags"' in schema_finding.summary
    assert "array, string" in schema_finding.summary
    assert schema_finding.confidence == "deterministic"


def test_deep_review_abstains_for_scoped_enum_and_schema_variants(tmp_path):
    path = tmp_path / "scoped-contracts-prd.md"
    path.write_text(
        "Variant 1\n"
        "Hard skip\n"
        "2 secs\n"
        "Tier 1\n"
        "Variant 2\n"
        "Hard skip\n"
        "2 secs\n"
        "Tier 2\n"
        "Product 1 schema: genre_tags[]\n"
        "Product 2 schema: genre_tags: string"
    )

    response = assess_extraction_json(str(path), '{"criteria": []}')

    assert not any(
        finding.kind in {"enum_domain_conflict", "schema_type_conflict"}
        for finding in response.deep_review.findings
    )


def test_deep_review_accepts_repeated_compatible_contract_declarations(tmp_path):
    path = tmp_path / "compatible-contracts-prd.md"
    path.write_text(
        "Hard skip\n"
        "2 secs\n"
        "Tier 1\n"
        "Hard skip\n"
        "3 secs\n"
        "Tier 1\n"
        "genre_tags[]\n"
        "genre_tags: array"
    )

    response = assess_extraction_json(str(path), '{"criteria": []}')

    assert not any(
        finding.kind in {"enum_domain_conflict", "schema_type_conflict"}
        for finding in response.deep_review.findings
    )


def test_deep_review_finds_polarity_rank_and_precedence_conflicts(tmp_path):
    path = tmp_path / "decision-rules-prd.md"
    path.write_text(
        "restricted_content must be enabled.\n"
        "restricted_content must be disabled.\n"
        "feed_order rank 1: editorial_source.\n"
        "feed_order rank 1: engagement_source.\n"
        "editorial_source before engagement_source.\n"
        "engagement_source before freshness_source.\n"
        "freshness_source before editorial_source."
    )

    response = assess_extraction_json(str(path), '{"criteria": []}')
    by_kind = {finding.kind: finding for finding in response.deep_review.findings}

    assert len(by_kind["opposite_polarity"].evidence) == 2
    assert "restricted_content" in by_kind["opposite_polarity"].summary
    assert len(by_kind["duplicate_rank"].evidence) == 2
    assert "rank 1" in by_kind["duplicate_rank"].summary
    assert len(by_kind["precedence_cycle"].evidence) == 3
    assert "editorial_source" in by_kind["precedence_cycle"].summary


def test_deep_review_abstains_from_cross_scope_decision_rules(tmp_path):
    path = tmp_path / "scoped-decisions-prd.md"
    path.write_text(
        "Product 1 restricted_content must be enabled.\n"
        "Product 2 restricted_content must be disabled.\n"
        "Variant 1 feed_order rank 1: editorial_source.\n"
        "Variant 2 feed_order rank 1: engagement_source.\n"
        "Phase 1 editorial_source before engagement_source.\n"
        "Phase 2 engagement_source before editorial_source."
    )

    response = assess_extraction_json(str(path), '{"criteria": []}')

    assert not any(
        finding.kind in {"opposite_polarity", "duplicate_rank", "precedence_cycle"}
        for finding in response.deep_review.findings
    )
