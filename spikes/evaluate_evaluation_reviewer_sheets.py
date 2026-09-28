"""Report agreement after both blinded internal reviewer sheets are complete."""

from __future__ import annotations

from pathlib import Path

from forge.evaluate.labels import (
    EvaluationReviewerSheet,
    evaluate_reviewer_sheets,
)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    sheets = [
        EvaluationReviewerSheet.model_validate_json(
            (
                root / f"sampleDoc/.forge/evaluation-ai-proxy-{index}.json"
            ).read_text()
        )
        for index in (1, 2, 3)
    ]
    print(evaluate_reviewer_sheets(sheets).model_dump_json(indent=2))


if __name__ == "__main__":
    main()
