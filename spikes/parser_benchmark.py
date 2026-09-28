"""Developer-only parser comparison; no candidate is a Forge dependency.

Examples:

    uv run python spikes/parser_benchmark.py fixtures/corpus/complete.md

    uv run --with docling --with pymupdf4llm \
      python spikes/parser_benchmark.py /path/to/sample.pdf /path/to/sample.docx

The current parser is the control. Candidate outputs are compared for observable
text and structure only; this script does not make an adoption decision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import time
from collections import Counter
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from forge.ingest.adapters import LocalFileSourceAdapter, SourceRef
from forge.ingest.parsers import LegacyDocumentParser


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "unknown"


def _normalized_lines(text: str) -> set[str]:
    return {
        " ".join(line.lower().split())
        for line in text.splitlines()
        if " ".join(line.split())
    }


def _tokens(text: str) -> Counter[str]:
    return Counter(re.findall(r"[\w.-]+", text.lower()))


def _metrics(
    text: str,
    *,
    baseline_text: str,
    pages: int | None,
    tables: int | None,
    images: int | None,
    provenance_items: int | None,
) -> dict[str, object]:
    lines = _normalized_lines(text)
    baseline_lines = _normalized_lines(baseline_text)
    tokens = _tokens(text)
    baseline_tokens = _tokens(baseline_text)
    shared_tokens = sum((tokens & baseline_tokens).values())
    return {
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "characters": len(text),
        "nonempty_lines": len(lines),
        "baseline_line_recall": (
            round(len(lines & baseline_lines) / len(baseline_lines), 4)
            if baseline_lines
            else 1.0
        ),
        "baseline_token_recall": (
            round(shared_tokens / baseline_tokens.total(), 4)
            if baseline_tokens
            else 1.0
        ),
        "baseline_token_precision": (
            round(shared_tokens / tokens.total(), 4) if tokens else 1.0
        ),
        "markdown_headings": len(re.findall(r"(?m)^#{1,6}\s+", text)),
        "markdown_table_rows": len(
            re.findall(r"(?m)^\s*\|(?:[^\n|]*\|)+\s*$", text)
        ),
        "pages": pages,
        "tables": tables,
        "images": images,
        "provenance_items": provenance_items,
    }


def _run_repeated(
    convert: Callable[[], dict[str, Any]], runs: int
) -> tuple[dict[str, Any], list[float], bool]:
    outputs: list[dict[str, Any]] = []
    elapsed: list[float] = []
    for _ in range(runs):
        started = time.perf_counter()
        outputs.append(convert())
        elapsed.append(time.perf_counter() - started)
    hashes = {
        hashlib.sha256(output["text"].encode("utf-8")).hexdigest()
        for output in outputs
    }
    return outputs[-1], elapsed, len(hashes) == 1


def _result(
    name: str,
    parser_version: str,
    convert: Callable[[], dict[str, Any]],
    *,
    runs: int,
    baseline_text: str,
) -> dict[str, object]:
    try:
        output, elapsed, deterministic = _run_repeated(convert, runs)
    except Exception as exc:  # Candidate failures are benchmark results.
        return {
            "parser": name,
            "version": parser_version,
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "parser": name,
        "version": parser_version,
        "status": "ok",
        "runs": runs,
        "seconds": {
            "median": round(statistics.median(elapsed), 6),
            "minimum": round(min(elapsed), 6),
            "all": [round(value, 6) for value in elapsed],
        },
        "deterministic_text": deterministic,
        "metrics": _metrics(
            output["text"],
            baseline_text=baseline_text,
            pages=output.get("pages"),
            tables=output.get("tables"),
            images=output.get("images"),
            provenance_items=output.get("provenance_items"),
        ),
    }


def _legacy(path: Path) -> dict[str, Any]:
    artifact = LocalFileSourceAdapter().acquire(SourceRef.local_file(path))
    parsed = LegacyDocumentParser().parse(artifact)
    return {
        "text": "\n\n".join(block.text for block in parsed.document.blocks),
        "pages": len(
            {block.page for block in parsed.document.blocks if block.page is not None}
        )
        or None,
        "tables": len(
            {
                node.table.table_id
                for node in parsed.canonical_nodes
                if node.table is not None
            }
        ),
        "images": len(parsed.document.visual_assets),
        "provenance_items": sum(
            node.provenance is not None for node in parsed.canonical_nodes
        ),
    }


def _docling(path: Path) -> dict[str, Any]:
    from docling.document_converter import DocumentConverter

    document = DocumentConverter().convert(path).document
    exported = document.export_to_dict()
    return {
        "text": document.export_to_markdown(),
        "pages": len(exported.get("pages", {})),
        "tables": len(exported.get("tables", [])),
        "images": len(exported.get("pictures", [])),
        "provenance_items": sum(
            bool(getattr(item, "prov", None))
            for item, _level in document.iterate_items()
        ),
    }


def _pymupdf4llm(path: Path) -> dict[str, Any]:
    if path.suffix.lower() != ".pdf":
        raise ValueError("PyMuPDF4LLM control is limited to PDF inputs")
    import pymupdf4llm

    chunks = pymupdf4llm.to_markdown(path, page_chunks=True, show_progress=False)
    return {
        "text": "\n\n".join(chunk.get("text", "") for chunk in chunks),
        "pages": len(chunks),
        "tables": sum(len(chunk.get("tables", [])) for chunk in chunks),
        "images": sum(len(chunk.get("images", [])) for chunk in chunks),
        "provenance_items": sum(bool(chunk.get("metadata")) for chunk in chunks),
    }


def benchmark(path: Path, runs: int) -> dict[str, object]:
    baseline = _legacy(path)
    baseline_text = baseline["text"]
    parsers: list[dict[str, object]] = [
        _result(
            "forge_legacy",
            LegacyDocumentParser.fingerprint,
            lambda: _legacy(path),
            runs=runs,
            baseline_text=baseline_text,
        )
    ]
    try:
        import docling  # noqa: F401
    except ImportError:
        parsers.append({"parser": "docling", "status": "unavailable"})
    else:
        parsers.append(
            _result(
                "docling",
                _package_version("docling"),
                lambda: _docling(path),
                runs=runs,
                baseline_text=baseline_text,
            )
        )
    try:
        import pymupdf4llm  # noqa: F401
    except ImportError:
        parsers.append({"parser": "pymupdf4llm", "status": "unavailable"})
    else:
        if path.suffix.lower() != ".pdf":
            parsers.append(
                {
                    "parser": "pymupdf4llm",
                    "version": _package_version("pymupdf4llm"),
                    "status": "not_applicable",
                    "reason": "PDF-only benchmark control",
                }
            )
        else:
            parsers.append(
                _result(
                    "pymupdf4llm",
                    _package_version("pymupdf4llm"),
                    lambda: _pymupdf4llm(path),
                    runs=runs,
                    baseline_text=baseline_text,
                )
            )
    return {
        "source": str(path.resolve()),
        "source_type": path.suffix.lower().removeprefix("."),
        "source_bytes": path.stat().st_size,
        "parsers": parsers,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare Forge's parser with optional structured parsers."
    )
    parser.add_argument("sources", nargs="+", type=Path)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    report = {
        "schema_version": "1.0",
        "adoption_decision": "none",
        "notes": [
            "Candidate packages are optional and are not Forge dependencies.",
            "baseline_line_recall compares normalized non-empty lines with the current parser; it is not semantic accuracy.",
            "baseline_token recall/precision compare token multisets and tolerate line reflow, but still do not establish semantic or provenance accuracy.",
            "Evaluate representative PDFs and DOCX files manually before adopting a parser.",
        ],
        "documents": [benchmark(path, args.runs) for path in args.sources],
    }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
