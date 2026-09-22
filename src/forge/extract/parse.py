from __future__ import annotations

import json

from forge.extract.batch import ExtractionRun


def parse_extraction(text: str) -> ExtractionRun:
    """Parse a client completion, tolerating an accidental Markdown fence."""
    stripped = text.strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        final_fence = stripped.rfind("```")
        if first_newline != -1 and final_fence > first_newline:
            stripped = stripped[first_newline + 1 : final_fence].strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError("client model did not return valid extraction JSON") from exc
    return ExtractionRun.model_validate(payload)
