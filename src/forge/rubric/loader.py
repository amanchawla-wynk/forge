from __future__ import annotations

from pathlib import Path

import yaml

from forge.rubric.models import Rubric

LIBRARY = Path(__file__).parent / "library"


def load_rubric(source: str | Path) -> Rubric:
    """Load by rubric name (from the bundled library) or by explicit path.

    Company-tuned rubrics live outside the package and are passed by path, so
    tuning never requires forking the code.
    """
    path = Path(source)
    if not path.exists():
        matches = sorted(LIBRARY.glob(f"{source}.*.yaml"))
        if not matches:
            available = ", ".join(p.stem for p in LIBRARY.glob("*.yaml"))
            raise FileNotFoundError(
                f"no rubric {source!r}; available: {available or '(none)'}"
            )
        path = matches[-1]  # highest version
    return Rubric.model_validate(yaml.safe_load(path.read_text()))


def list_rubrics() -> list[str]:
    return sorted(p.stem for p in LIBRARY.glob("*.yaml"))
