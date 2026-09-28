# Parser Benchmark: Forge, Docling, and PyMuPDF4LLM

Date: 2026-09-26

## Scope

The developer-only `spikes/parser_benchmark.py` compared:

- Forge legacy parser `forge.legacy-document-parser/1.0`;
- Docling `2.130.0` for DOCX and PDF;
- PyMuPDF4LLM `1.28.2` as a PDF-only control.

The inputs were the two DOCX files and one PDF in `sampleDoc/`. Candidate
packages were installed ephemerally with `uv run --with`; neither was added to
Forge's dependencies. Two repeated runs checked deterministic text, followed by
one run after adding format-insensitive token-retention metrics.

## Results

| Document | Parser | Observed seconds | Characters | Token recall | Token precision | Headings | Tables | Markdown table rows | Images |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Micro Dramas DOCX, 14.1 MB | Forge | 0.092-0.104 | 35,003 | 1.0000 | 1.0000 | 0 | 1 | 0 | 24 |
| Micro Dramas DOCX, 14.1 MB | Docling | 5.231-65.652 | 39,953 | 0.9941 | 0.8754 | 27 | 2 | 7 | 25 |
| Rush quality DOCX, 39.8 KB | Forge | 0.029-0.036 | 7,552 | 1.0000 | 1.0000 | 0 | 12 | 0 | 0 |
| Rush quality DOCX, 39.8 KB | Docling | 0.417-0.421 | 11,605 | 0.9923 | 0.9453 | 12 | 13 | 62 | 0 |
| MicroDrama recommendations PDF, 1.19 MB | Forge | 0.099-0.103 | 42,223 | 1.0000 | 1.0000 | 0 | 0 | 0 | 21 page visuals |
| MicroDrama recommendations PDF, 1.19 MB | Docling | 63.958-150.014 | 62,478 | 0.9826 | 0.9042 | 46 | 29 | 162 | 3 |
| MicroDrama recommendations PDF, 1.19 MB | PyMuPDF4LLM | 6.321-9.601 | 46,278 | 0.9834 | 0.8698 | 21 | 0 metadata tables | 152 | 0 |

All three parsers produced identical text hashes across their two repeated runs.
The wide first-run Docling ranges include model initialization and OCR startup.
Docling used RapidOCR on two PDF pages and downloaded a substantial optional
runtime including Torch, ONNX Runtime, OpenCV, and layout models.

Token recall and precision are relative to Forge's current output, not ground
truth. Recall near 1.0 means the candidate retained almost all current-parser
tokens despite line reflow. Precision below 1.0 means it emitted additional
tokens, which may be useful recovered structure/text or unwanted duplication.
The very low exact-line recall values (0.033-0.118) are therefore mostly a
formatting effect and are not an accuracy result.

## Interpretation

- Forge remains dramatically faster and has the smallest dependency surface.
- Docling recovers materially richer structure in all three samples. The PDF
  result is the strongest difference: 46 headings and 29 tables instead of one
  text block per page.
- PyMuPDF4LLM recovers useful PDF heading/table-shaped Markdown at roughly one
  eighth of Docling's warm PDF runtime, but its page-chunk table metadata did not
  enumerate the 152 Markdown table rows it rendered.
- Docling's DOCX `prov` lists are empty because DOCX has no stable rendered page
  geometry. A Forge adapter would need to derive stable canonical ids from
  Docling item references and retain source order rather than interpreting this
  benchmark's zero as no possible provenance.
- Candidate output is larger than Forge output. Exact quote alignment, repeated
  headers, OCR additions, table-cell order, and image handling need manual
  source comparison before candidate text can become score-eligible evidence.

## Decision

Do not replace the production parser yet. The measurements justify a bounded
Docling adapter prototype because richer table and heading structure directly
targets the measured multi-line claim-fragmentation problem. Keep
PyMuPDF4LLM as the lower-cost PDF control. Before adoption, manually label exact
text/table/provenance fidelity on these samples, run the existing corpus and
proxy diagnostics through each adapter, and require a new parser fingerprint so
no existing extraction or review can be mistaken for the new baseline.
