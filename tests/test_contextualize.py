from __future__ import annotations

import json

import pytest

from forge.rubric.loader import load_rubric
from forge.score.contextualize import (
    ContextCandidate,
    EDGE_CASE_TYPES,
    apply_edge_case_choice,
    apply_choice,
    build_candidates,
    build_choice_prompt,
    build_coverage_pairs,
    build_coverage_prompt,
    build_edge_case_prompt,
    build_framing_prompt,
    build_requirement_candidates,
    document_display_name,
    parse_choice,
    parse_coverage_classification,
    parse_edge_case_choice,
    parse_framing_choice,
)
from forge.score.planner import level0_question
from forge.service import assess_extraction_json


def _candidate(index: int, criterion_id: str = "problem_statement") -> ContextCandidate:
    return ContextCandidate(
        index=index,
        criterion_id=criterion_id,
        field_name="affected_users",
        description="Who specifically experiences it.",
        value="Finance administrators",
        quote="Finance administrators are affected.",
    )


def test_document_display_name_strips_extension_and_separators():
    assert document_display_name("/a/b/Micro Dramas.docx") == "Micro Dramas"
    assert document_display_name("/a/b/quarterly_report-v2.pdf") == "quarterly report v2"


def test_level0_question_prefixes_with_display_name():
    assert level0_question("What is the problem?", "Micro Dramas") == (
        'For "Micro Dramas": What is the problem?'
    )


def test_level0_question_is_a_noop_without_a_display_name():
    assert level0_question("What is the problem?", None) == "What is the problem?"


def test_parse_choice_accepts_only_a_closed_set_of_integers():
    assert parse_choice('{"choice": 2}', max_index=3) == 2
    assert parse_choice('{"choice": 0}', max_index=3) == 0


@pytest.mark.parametrize(
    "raw",
    [
        "not json at all",
        "```json\n{\"choice\": 1}\n```",  # markdown fence is rejected, not stripped
        '{"choice": 1, "reason": "because"}',  # extra key
        '{"choice": "1"}',  # string, not int
        '{"choice": true}',  # bool is technically an int subtype; must be rejected
        '{"choice": 99}',  # out of range
        '{"choice": -1}',  # negative
        "{}",
        "[1, 2, 3]",
    ],
)
def test_parse_choice_fails_safe_to_zero_on_any_deviation(raw):
    assert parse_choice(raw, max_index=3) == 0


_DOC_TEXT = (
    "Users cannot export invoices. Finance administrators are affected. "
    "42 support tickets were filed about this in the last quarter."
)


def test_build_candidates_prefers_same_criterion_then_orders_deterministically(tmp_path):
    path = tmp_path / "prd.md"
    path.write_text(_DOC_TEXT)
    response = assess_extraction_json(
        str(path), json.dumps({"runs": [{"criteria": _full_extraction_payload()}]})
    )
    candidates = build_candidates(
        response.assessment, target_criterion_id="problem_statement", limit=5
    )
    # problem_statement itself is fully satisfied, so its own fields should
    # appear before any candidate borrowed from another criterion.
    assert candidates
    assert all(c.index == position + 1 for position, c in enumerate(candidates))
    same_criterion = [c for c in candidates if c.criterion_id == "problem_statement"]
    assert same_criterion
    assert candidates[: len(same_criterion)] == same_criterion


def test_build_candidates_respects_the_limit(tmp_path):
    path = tmp_path / "prd.md"
    path.write_text(_DOC_TEXT)
    response = assess_extraction_json(
        str(path), json.dumps({"runs": [{"criteria": _full_extraction_payload()}]})
    )
    candidates = build_candidates(
        response.assessment, target_criterion_id="success_metrics", limit=2
    )
    assert len(candidates) <= 2
    # success_metrics has no satisfied fields of its own, so every candidate
    # must be borrowed from another (already-verified) criterion.
    assert all(c.criterion_id != "success_metrics" for c in candidates)


def test_list_items_become_candidates_only_after_individual_quote_verification(
    tmp_path,
):
    path = tmp_path / "prd.md"
    path.write_text("Web is out of scope. Offline downloads are excluded.")
    extraction = {
        "runs": [
            {
                "criteria": [
                    {
                        "criterion_id": "non_goals",
                        "fields": [
                            {
                                "name": "non_goals",
                                "value": [
                                    "Web is out of scope.",
                                    "Offline downloads are excluded.",
                                    "This invented item is not in the document.",
                                ],
                                "evidence": {"quote": "Web is out of scope."},
                            }
                        ],
                    }
                ]
            }
        ]
    }
    response = assess_extraction_json(str(path), json.dumps(extraction))
    candidates = build_candidates(response.assessment, "edge_cases_and_states", limit=10)
    quotes = [
        candidate.quote
        for candidate in candidates
        if candidate.criterion_id == "non_goals"
    ]

    assert quotes == ["Web is out of scope.", "Offline downloads are excluded."]


def test_build_choice_prompt_is_a_closed_set_instruction():
    candidates = [_candidate(1), _candidate(2, criterion_id="success_metrics")]
    prompt = build_choice_prompt("Who runs into this problem?", "Problem is stated", candidates)
    assert "UNTRUSTED DATA" in prompt
    assert '{"choice": <integer>}' in prompt
    assert "1. [problem_statement.affected_users]" in prompt
    assert "2. [success_metrics.affected_users]" in prompt
    assert "0. None of these help" in prompt
    assert "Never invent a new index" in prompt


def test_apply_choice_zero_returns_the_level0_question_and_no_candidate():
    text, chosen = apply_choice(
        "Who runs into this problem?", "Micro Dramas", [_candidate(1)], choice=0
    )
    assert text == 'For "Micro Dramas": Who runs into this problem?'
    assert chosen is None


def test_apply_choice_out_of_range_falls_back_safely():
    text, chosen = apply_choice(
        "Who runs into this problem?", "Micro Dramas", [_candidate(1)], choice=7
    )
    assert text == 'For "Micro Dramas": Who runs into this problem?'
    assert chosen is None


def test_apply_choice_valid_index_weaves_in_only_verified_text():
    candidate = _candidate(1)
    text, chosen = apply_choice(
        "What specific problem does this solve?",
        "Micro Dramas",
        [candidate],
        choice=1,
    )
    assert chosen is candidate
    # Every substantive word in the enrichment comes from one of three
    # sources: the base question, the display name, or the candidate itself.
    assert "Micro Dramas" in text
    assert "What specific problem does this solve?" in text
    assert candidate.quote in text
    assert "who specifically experiences it" in text.lower()


def test_build_framing_prompt_exposes_only_declared_options():
    rubric = load_rubric("prd")
    prompt = build_framing_prompt(rubric, [_candidate(1)])

    assert "UNTRUSTED DATA" in prompt
    assert '{"framing": <integer>}' in prompt
    assert "1. [problem_fix]" in prompt
    assert "2. [opportunity_bet]" in prompt
    assert "3. [compliance_mandate]" in prompt
    assert "4. [migration_replatform]" in prompt
    assert "0. Unclear" in prompt


def test_parse_framing_choice_maps_only_valid_indexes():
    rubric = load_rubric("prd")
    assert parse_framing_choice('{"framing": 2}', rubric) == "opportunity_bet"
    assert parse_framing_choice('{"framing": 0}', rubric) is None


@pytest.mark.parametrize(
    "raw",
    [
        "opportunity_bet",
        '{"framing": "2"}',
        '{"framing": true}',
        '{"framing": 99}',
        '{"framing": 2, "reason": "growth"}',
        "```json\n{\"framing\": 2}\n```",
    ],
)
def test_parse_framing_choice_fails_safe(raw):
    assert parse_framing_choice(raw, load_rubric("prd")) is None


def test_planner_uses_rubric_authored_opportunity_question(tmp_path):
    path = tmp_path / "Micro Dramas.md"
    path.write_text("GenZ users watch short vertical video on mobile.")
    response = assess_extraction_json(
        str(path), json.dumps({"runs": [{"criteria": []}]}), framing="opportunity_bet"
    )

    assert response.framing == "opportunity_bet"
    assert response.next_question is not None
    assert response.next_question.framing == "opportunity_bet"
    assert response.next_question.base_question == (
        "What opportunity is this going after, and what does the business "
        "lose by not taking it now?"
    )
    assert response.next_question.question.startswith('For "Micro Dramas":')


def test_edge_case_prompt_is_a_two_axis_closed_set():
    prompt = build_edge_case_prompt(
        "transitional_or_degraded_states", [_candidate(1)]
    )
    assert '{"fact": <integer>, "edge_case": <integer>}' in prompt
    assert '1. [problem_statement.affected_users] "Finance administrators are affected."' in prompt
    assert "1. [interruption_recovery]" in prompt
    assert f"{len(EDGE_CASE_TYPES)}. [stale_or_conflicting_state]" in prompt
    assert "Never invent a fact" in prompt


def test_parse_edge_case_choice_accepts_only_valid_pairs():
    assert parse_edge_case_choice('{"fact": 1, "edge_case": 2}', 3) == (1, 2)
    assert parse_edge_case_choice('{"fact": 0, "edge_case": 0}', 3) is None


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        '{"fact": 1}',
        '{"fact": 1, "edge_case": 2, "reason": "offline"}',
        '{"fact": "1", "edge_case": 2}',
        '{"fact": true, "edge_case": 2}',
        '{"fact": 0, "edge_case": 2}',
        '{"fact": 1, "edge_case": 0}',
        '{"fact": 99, "edge_case": 1}',
        '{"fact": 1, "edge_case": 99}',
    ],
)
def test_parse_edge_case_choice_fails_safe(raw):
    assert parse_edge_case_choice(raw, candidate_count=2) is None


def test_apply_edge_case_choice_uses_only_verified_quote_and_fixed_text():
    candidate = _candidate(1)
    text, chosen, edge_case = apply_edge_case_choice(
        "Micro Dramas", [candidate], (1, 2)
    )
    assert chosen is candidate
    assert edge_case is EDGE_CASE_TYPES[1]
    assert candidate.quote in text
    assert edge_case.question in text
    assert text.startswith('For "Micro Dramas", the PRD says:')


def test_apply_edge_case_choice_none_returns_no_generated_question():
    assert apply_edge_case_choice("Micro Dramas", [_candidate(1)], None) == (
        None,
        None,
        None,
    )


def test_coverage_matrix_uses_verified_requirement_atoms(tmp_path):
    path = tmp_path / "prd.md"
    path.write_text(
        "Progress should sync with the backend every 10 seconds. "
        "Playback should start immediately."
    )
    extraction = {
        "runs": [
            {
                "criteria": [
                    {
                        "criterion_id": "functional_requirements",
                        "fields": [
                            {
                                "name": "primary_flow",
                                "value": "Playback should start immediately.",
                                "evidence": {
                                    "quote": "Playback should start immediately."
                                },
                            },
                            {"name": "preconditions", "value": None},
                            {
                                "name": "requirements",
                                "value": [
                                    "Progress should sync with the backend every 10 seconds."
                                ],
                                "evidence": {
                                    "quote": "Progress should sync with the backend every 10 seconds."
                                },
                            },
                            {"name": "prioritisation", "value": None},
                        ],
                    }
                ]
            }
        ]
    }
    response = assess_extraction_json(str(path), json.dumps(extraction))
    requirements = build_requirement_candidates(response.assessment)
    pairs = build_coverage_pairs(requirements)

    assert [item.quote for item in requirements] == [
        "Playback should start immediately.",
        "Progress should sync with the backend every 10 seconds.",
    ]
    progress_index = requirements[1].index
    progress_edge_ids = {
        EDGE_CASE_TYPES[pair.edge_case_index - 1].id
        for pair in pairs
        if pair.requirement_index == progress_index
    }
    assert {
        "connectivity_loss",
        "concurrent_state_change",
        "stale_or_conflicting_state",
    }.issubset(progress_edge_ids)


def test_coverage_classification_requires_every_pair_exactly_once():
    requirements = [_candidate(1)]
    requirements[0].field_name = "requirements"
    requirements[0].quote = "Playback starts immediately."
    pairs = build_coverage_pairs(requirements)
    evidence = [_candidate(1)]
    prompt = build_coverage_prompt(requirements, evidence, pairs)
    assert "Return every PAIR exactly once" in prompt

    valid = {
        "items": [
            {"pair": pair.index, "status": 2, "evidence": 0}
            for pair in pairs
        ]
    }
    ledger = parse_coverage_classification(
        json.dumps(valid), requirements, evidence, pairs
    )
    assert ledger is not None
    assert len(ledger.items) == len(pairs)
    assert all(item.status.value == "missing" for item in ledger.items)

    valid["items"].pop()
    assert (
        parse_coverage_classification(
            json.dumps(valid), requirements, evidence, pairs
        )
        is None
    )


def test_coverage_positive_status_requires_evidence_index():
    requirements = [_candidate(1)]
    requirements[0].field_name = "requirements"
    pairs = build_coverage_pairs(requirements)
    evidence = [_candidate(1)]
    payload = {
        "items": [
            {"pair": pair.index, "status": 1, "evidence": 0}
            for pair in pairs
        ]
    }
    assert (
        parse_coverage_classification(
            json.dumps(payload), requirements, evidence, pairs
        )
        is None
    )


def _full_extraction_payload() -> list[dict[str, object]]:
    return [
        {
            "criterion_id": "problem_statement",
            "fields": [
                {
                    "name": "problem",
                    "value": "Users cannot export invoices",
                    "evidence": {"quote": "Users cannot export invoices."},
                },
                {
                    "name": "affected_users",
                    "value": "Finance administrators",
                    "evidence": {"quote": "Finance administrators are affected."},
                },
                {
                    "name": "evidence",
                    "value": "42 support tickets",
                    "evidence": {"quote": "42 support tickets"},
                },
                {"name": "cost_of_inaction", "value": None, "evidence": None},
            ],
        },
        {
            "criterion_id": "success_metrics",
            "fields": [
                {"name": "primary_metric", "value": None, "evidence": None},
                {"name": "baseline", "value": None, "evidence": None},
                {"name": "target", "value": None, "evidence": None},
                {"name": "measurement_window", "value": None, "evidence": None},
                {"name": "guardrail_metric", "value": None, "evidence": None},
            ],
        },
    ]
