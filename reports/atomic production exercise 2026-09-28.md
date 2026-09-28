# Atomic Production Exercise - 2026-09-28

## Scope

This owner-approved synthetic exercise ran the production atomic review lifecycle
against both ignored internal DOCX PRDs:

- `sampleDoc/Micro Dramas.docx`
- `sampleDoc/Rush_Playback_Quality_Selection_Guide.docx`

The harness reused and reverified the frozen three-run 0.9.1 native evaluations,
started durable atomic sessions, answered every surfaced question, replayed every
answer operation with the same operation id, applied verified delta checkpoints,
previewed and approved integrated revisions, wrote new DOCX copies, and completed
fresh final assessments without supplemental evidence.

The machine-readable record is
`reports/atomic production exercise 2026-09-28.json`. The reproducible harness is
`spikes/run_internal_atomic_production.py`.

## Results

| Metric | Micro Dramas | Rush | Combined |
| --- | ---: | ---: | ---: |
| Workflow completed | yes | yes | 2/2 |
| Questions | 64 | 65 | 129 |
| Atomic questions | 41 | 42 | 83 |
| Legacy fallback questions | 23 | 23 | 46 |
| Legacy fallback rate | 35.94% | 35.38% | 35.66% |
| Credited answers | 64 | 65 | 129 |
| Uncredited answers | 0 | 0 | 0 |
| Answer closure rate | 100% | 100% | 100% |
| Attempted atomic issue ids | 41 | 42 | 83 |
| Resolved atomic issue ids | 41 | 42 | 83 |
| Issue closure rate | 100% | 100% | 100% |
| Transport retries | 65 | 66 | 131 |
| Delta extractions | 45 | 45 | 90 |
| Delta prompt characters | 268,991 | 273,656 | 542,647 |
| Local elapsed time | 77.03 s | 44.38 s | 121.41 s |
| Initial band | Not a PRD | Not a PRD | n/a |
| Final band | Ready to build | Ready to build | n/a |

Every retried start and answer operation returned the original durable session or
version. No replay created a duplicate answer or advanced a session twice.

## Interpretation

The 35.66% fallback rate is expected under the additive production design. Native
evaluation supplied one atomic issue at a time; after those verified issues were
resolved, remaining required legacy fields continued through the compatibility
queue. It is a product-efficiency measurement, not a quality failure.

The exercise also caught and fixed three release defects before measurement:

- atomic closure now requires credit on the exact target field, not merely any
  field in the criterion;
- resolved assertion identity is keyed by criterion plus assertion;
- pre-v4 sessions upcast to schema v4 on their next write instead of persisting
  v4-shaped state under a v3 label.

## Limitations

- This is synthetic owner-authority evidence, not human calibration.
- The initial extraction was a deterministic complete null baseline so every
  remediation transition was exercised. Final extraction deterministically cited
  the materialized exercise answers. Band movement therefore validates lifecycle
  mechanics, not real-world PRD improvement quality.
- No provider inference occurred. Provider token counts and model latency are
  unavailable. Reporting zero tokens would be misleading, so the JSON records
  availability as false and provider calls as zero.
- Local elapsed time includes parsing, hashing, SQLite, scoring, revision writing,
  and final verification. It excludes human think time and provider latency.
- Generated copies are ignored local artifacts under
  `sampleDoc/.forge/production-exercise-release-v2/`.

## Reproduce

```bash
uv run python spikes/prepare_internal_atomic_evaluation.py validate
uv run python -u spikes/run_internal_atomic_production.py \
  --artifact-dir sampleDoc/.forge/production-exercise-release-next \
  --output "reports/atomic production exercise rerun.json"
```

Use a new artifact directory for each run. Production revision writing correctly
refuses to overwrite an existing output.
