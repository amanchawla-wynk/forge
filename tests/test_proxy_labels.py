from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from forge.proxy_labels import (
    ProxyPanelArtifact,
    verify_proxy_artifact,
)
from forge.review_eval import GoldenSuite
from forge.rubric.loader import load_rubric


ROOT = Path(__file__).parents[1]
ARTIFACT = (
    ROOT
    / "fixtures"
    / "proxy"
    / "microdrama-recommendations.proxy-panel.v1.json"
)


def test_proxy_artifact_is_source_verified_and_calibration_ineligible():
    artifact = verify_proxy_artifact(ARTIFACT, workspace_root=ROOT)

    assert len(artifact.labels) == 29
    assert Counter(label.consensus_status for label in artifact.labels) == {
        "supported": 19,
        "hard_negative": 5,
        "compatible": 4,
        "contested": 1,
    }
    assert artifact.calibration_eligible is False
    assert artifact.headline_metrics_eligible is False
    assert artifact.human_independent_review is False

    for label in artifact.labels:
        assert label.score_effect == "none"
        assert label.advisory is True
        assert label.evidence


def test_proxy_artifact_cannot_be_retyped_as_internal_or_human_labels():
    payload = json.loads(ARTIFACT.read_text())
    payload["dataset_tier"] = "internal"
    payload["label_authority"] = "internal_human"
    payload["calibration_eligible"] = True

    with pytest.raises(ValidationError):
        ProxyPanelArtifact.model_validate(payload)
    with pytest.raises(ValidationError):
        GoldenSuite.model_validate(payload)


def test_proxy_rubric_delta_changes_fields_but_not_weights_or_gates():
    rubric = load_rubric("prd")

    assert rubric.version == "0.6.0-expert-baseline"
    assert [field.name for field in rubric.criterion("functional_requirements").fields][
        -1
    ] == "decision_rules_and_precedence"
    assert [field.name for field in rubric.criterion("acceptance_criteria").fields][
        -1
    ] == "requirement_coverage"
    assert {
        criterion.id: (criterion.weight, criterion.gate.value)
        for criterion in rubric.criteria
    } == {
        "problem_statement": (3.0, "caps_at_needs_work"),
        "success_metrics": (3.0, "caps_at_needs_work"),
        "non_goals": (2.0, "caps_at_ready_with_gaps"),
        "functional_requirements": (3.0, "none"),
        "acceptance_criteria": (3.0, "caps_at_ready_with_gaps"),
        "edge_cases_and_states": (2.0, "none"),
        "instrumentation": (2.0, "none"),
        "dependencies": (2.0, "none"),
        "risk_compliance": (2.0, "none"),
        "rollout": (2.0, "none"),
        "open_questions_owned": (1.0, "none"),
        "alternatives_considered": (1.0, "none"),
        "assumptions_validation": (2.0, "none"),
        "operational_readiness": (2.0, "none"),
        "document_governance": (1.0, "none"),
    }
