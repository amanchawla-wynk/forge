"""Schema for synthetic public-guidance proxy labels.

Proxy panels improve regression coverage when human reviewers are unavailable,
but they are not calibration evidence. This intentionally does not reuse the
human-label models in ``forge.calibration`` or ``forge.review_eval``.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from forge.ingest.document import ingest_document


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProxyEvidence(_ClosedModel):
    quote: str = Field(min_length=1)
    page: int = Field(ge=1)
    source_block_id: str = Field(min_length=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)

    @model_validator(mode="after")
    def _valid_span(self) -> ProxyEvidence:
        if self.end_char <= self.start_char:
            raise ValueError("evidence end_char must be greater than start_char")
        return self


class ProxyLabel(_ClosedModel):
    label_id: str = Field(pattern=r"^PXY-[A-Z0-9-]+$")
    consensus_status: Literal[
        "supported", "hard_negative", "compatible", "contested", "unclear"
    ]
    finding_kind: str = Field(min_length=1)
    evidence: list[ProxyEvidence] = Field(min_length=1)
    downstream_consumers: list[
        Literal[
            "product",
            "engineering",
            "design",
            "qa",
            "data_ml",
            "risk",
            "operations",
            "leadership",
        ]
    ] = Field(min_length=1)
    consequence: str = Field(min_length=1)
    required_decision: str = Field(min_length=1)
    blocker_status: Literal[
        "implementation_blocker", "conditional_blocker", "non_blocker"
    ]
    supporting_proxy_reviews: list[str] = Field(default_factory=list)
    disagreements: list[str] = Field(default_factory=list)
    destination: list[Literal["rubric", "deep_review"]] = Field(min_length=1)
    advisory: Literal[True] = True
    score_effect: Literal["none"] = "none"


class ProxyDocument(_ClosedModel):
    source_path: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_count: int = Field(ge=1)


class ProxyReview(_ClosedModel):
    review_id: str = Field(min_length=1)
    source_family: str = Field(min_length=1)
    notes_path: str = Field(min_length=1)


class ProxyPanel(_ClosedModel):
    panel_version: Literal["public-prd-proxy-panel.v1"]
    reviews: list[ProxyReview] = Field(min_length=1)
    independence_note: str = Field(min_length=1)


class ProxySource(_ClosedModel):
    source_id: str = Field(min_length=1)
    source_kind: Literal["public_first_party_guidance"]
    url: str = Field(pattern=r"^https://")
    claim_scope: str = Field(min_length=1)


class ProxyPanelArtifact(_ClosedModel):
    schema_uri: Literal[
        "https://forge.local/schemas/proxy-panel-labels.v1.json"
    ]
    artifact_type: Literal["forge.synthetic_public_guidance_proxy_panel.v1"]
    artifact_id: str = Field(min_length=1)
    label_namespace: Literal["proxy_public_guidance"]
    label_authority: Literal["synthetic_ai_proxy"]
    dataset_tier: Literal["external_proxy_diagnostic"]
    human_independent_review: Literal[False]
    organization_validation: Literal[False]
    calibration_eligible: Literal[False]
    headline_metrics_eligible: Literal[False]
    allowed_uses: list[
        Literal[
            "content_validity_hypothesis",
            "regression_fixture",
            "hard_negative_fixture",
            "transfer_diagnostic",
        ]
    ] = Field(min_length=1)
    prohibited_uses: list[
        Literal[
            "forge_review_eval_internal_label",
            "weight_tuning",
            "gate_tuning",
            "band_tuning",
            "severity_calibration",
            "organization_readiness_claim",
        ]
    ] = Field(min_length=1)
    document: ProxyDocument
    panel: ProxyPanel
    labels: list[ProxyLabel] = Field(min_length=1)
    source_registry: list[ProxySource] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_identity(self) -> ProxyPanelArtifact:
        label_ids = [label.label_id for label in self.labels]
        if len(label_ids) != len(set(label_ids)):
            raise ValueError("proxy artifact contains duplicate label ids")
        review_ids = [review.review_id for review in self.panel.reviews]
        if len(review_ids) != len(set(review_ids)):
            raise ValueError("proxy artifact contains duplicate review ids")
        known_reviews = set(review_ids)
        for label in self.labels:
            unknown = sorted(set(label.supporting_proxy_reviews) - known_reviews)
            if unknown:
                raise ValueError(
                    f"label {label.label_id!r} references unknown proxy reviews: "
                    + ", ".join(unknown)
                )
        if not re.search(r"(?:^|:)proxy-panel(?:$|:)", self.artifact_id):
            raise ValueError("proxy artifact_id must use the proxy-panel namespace")
        return self


def load_proxy_artifact(path: Path) -> ProxyPanelArtifact:
    """Load a closed proxy artifact; never convert it to human-label DTOs."""
    return ProxyPanelArtifact.model_validate(json.loads(path.read_text()))


def verify_proxy_artifact(
    path: Path, *, workspace_root: Path
) -> ProxyPanelArtifact:
    """Verify artifact identity and every evidence span against its source."""
    artifact = load_proxy_artifact(path)
    root = workspace_root.resolve()
    source = (root / artifact.document.source_path).resolve()
    if not source.is_relative_to(root):
        raise ValueError("proxy source_path escapes the workspace root")
    if not source.is_file():
        raise ValueError("proxy source document does not exist")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != artifact.document.source_sha256:
        raise ValueError("proxy source SHA-256 does not match")

    document = ingest_document(source)
    pages = [block.page for block in document.blocks if block.page is not None]
    if pages and max(pages) != artifact.document.page_count:
        raise ValueError("proxy source page count does not match")
    for label in artifact.labels:
        for evidence in label.evidence:
            located = document.locate_quote_span(evidence.quote)
            if located is None:
                raise ValueError(f"label {label.label_id!r} has unverified evidence")
            block, start, end = located
            observed = (block.id, block.page, start, end)
            expected = (
                evidence.source_block_id,
                evidence.page,
                evidence.start_char,
                evidence.end_char,
            )
            if observed != expected:
                raise ValueError(
                    f"label {label.label_id!r} evidence location does not match"
                )
    return artifact
