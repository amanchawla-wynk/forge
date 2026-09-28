"""Generate prediction-free synthetic AI proxy reviewer sheets."""

from __future__ import annotations

from pathlib import Path

from forge.evaluate.labels import make_reviewer_sheet
from forge.rubric.loader import load_rubric


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "sampleDoc/.forge"
    output.mkdir(parents=True, exist_ok=True)
    cases = [
        ("micro-dramas", "sampleDoc/Micro Dramas.docx"),
        (
            "rush-playback-quality-selection-guide",
            "sampleDoc/Rush_Playback_Quality_Selection_Guide.docx",
        ),
    ]
    rubric = load_rubric("prd")
    for reviewer_id in ("ai-proxy-1", "ai-proxy-2", "ai-proxy-3"):
        sheet = make_reviewer_sheet(
            rubric, reviewer_id=reviewer_id, cases=cases
        )
        path = output / f"evaluation-{reviewer_id}.json"
        path.write_text(sheet.model_dump_json(indent=2) + "\n")
        print(path)


if __name__ == "__main__":
    main()
