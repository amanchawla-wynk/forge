# Forge Must Evolve Questions, Not Authority

**Forge does not have, and does not need, a trained classifier or runtime labelled-data dependency.** Its production intelligence comes from a host LLM performing structured extraction and closed-set semantic classifications; Python verifies source spans and deterministically derives verdicts, gates, bands, and workflow transitions. Human labels are an offline prerequisite only for claims of calibration, precision/recall, organization validity, and threshold tuning, not for operating the product (`docs/PRODUCT.md:172-185`; `docs/SCORING_THEORY.md:369-406`). The central architectural defect is instead that Forge asks the model to fill rubric fields, then asks users **preset field questions and preset framing variants embedded in YAML, plus fixed edge-case questions embedded in Python**; optional contextualization merely selects an already-satisfied fact and appends it to an existing question. This cannot generate the smallest question implied by the actual evidence, ambiguity, contradiction, or missing decision in one PRD. Forge should preserve its strongest boundary, **LLM extraction and semantic judgment followed by Python evidence verification and deterministic scoring**, while changing the model-facing contract from field-presence extraction to criterion evaluation over evidence sets, gaps, unsupported claims, ambiguities, contradictions, and confidence. Retrieval should reduce criterion-specific context, never decide evidence eligibility or prove absence without an exhaustive recall safeguard. The smallest sensible route is incremental: improve source structure; introduce versioned criterion-evaluation records beside current extractions; generate one gap-specific question plan; fix session/provenance defects; then benchmark in-process lexical retrieval before considering SQLite FTS, PostgreSQL, pgvector, or a framework.

## The implemented system is deterministic after lossy extraction

### The actual authority boundary

Forge is a local Python application with two adapters around one domain core. The default MCP package owns no provider key and depends on Pydantic, MCP, PyMuPDF, python-docx, and semchunk (`pyproject.toml:1-13`). The optional dashboard adds FastAPI and LiteLLM behind the `dashboard` extra (`pyproject.toml:15-25`) and is the only direct provider path. This distinction is sound and should remain.

```text
                         inference owner
                  +---------------------------+
                  | MCP host / connected LLM  |
local file ------>| or dashboard LiteLLM      |
                  +-------------+-------------+
                                |
                      extraction/classification JSON
                                v
+-------------+  +--------------+---------------+  +----------------+
| PyMuPDF /   |->| Forge normalized blocks,     |->| verified fields |
| python-docx |  | exhaustive batches, prompts  |  | and claims      |
+-------------+  +------------------------------+  +-------+--------+
                                                               |
                                     +-------------------------+------------------+
                                     v                                            v
                           Python readiness score                       advisory deep review
                           verdicts -> weights ->                       claims -> bounded graph ->
                           gates -> band                               deterministic/classified findings
                                     |
                                     v
                           static question queue -> SQLite session -> answer deltas
```

The LLM never receives rubric weights and never assigns numeric points. `FieldSpec`, `Criterion`, gates, bands, and extraction-run count form a versioned contract (`src/forge/rubric/models.py:52-97`, `116-140`, `158-195`). `verify_run()` retains evidence only if its quote can be relocated in a normalized block and prevents supplemental evidence from crossing criterion boundaries (`src/forge/extract/batch.py:115-180`). `derive_verdict()` counts satisfied required fields, while `score()` applies fixed credits, configured weights, gates, all-applicable-present semantics, and consumer rollups (`src/forge/extract/models.py:78-117`; `src/forge/score/engine.py:156-257`). This is the architecture to preserve.

There is **no trained classifier** in the repository. Framing is a prompt-time four-way choice (`src/forge/score/contextualize.py:456-518`); edge coverage is a prompt-time four-status classification over deterministic pairs (`src/forge/score/contextualize.py:226-361`); consistency is likewise a repeated closed-set host-model task. No model weights, training job, feature pipeline, labelled training set, or inference artifact appears in the core dependency graph. The regression corpus locks deterministic behavior, proxy labels are explicitly synthetic and calibration-ineligible, and human labels are consumed by offline `forge.calibration` and `forge.review_eval`. Documentation is correct that the expert baseline works without company data (`docs/SCORING_THEORY.md:80-98`), but references to “classifier precision” must not be read as a trained-runtime prerequisite.

### Actual runtime flows

| Flow | Implemented execution | Model calls and state | Material qualification |
|---|---|---|---|
| Ingest | `ingest_document()` resolves a local `.pdf`, `.docx`, `.md`, or `.txt`; PDFs become one block per page; DOCX emits headings/paragraphs and flattened table rows, then appends headers/footers and inventories image relationships (`src/forge/ingest/document.py:23-47`, `73-167`). | None; no persistent normalized snapshot. | Repeated callers reparse the same file. No URL, Confluence, inline snapshot, OCR evidence, or parser-version identity exists. |
| Initial MCP native review | Each of three static resolvers calls `_sample()`, which independently ingests, batches, and builds the same prompt; `assess_prd()` parses three completions and `assess_extractions()` ingests and batches again (`src/forge/mcp/server.py:558-618`, `639-663`; `src/forge/service.py:63-84`). | Three extraction calls for one batch. Long documents require client-side iteration over `assess_prd_batch`. | Legacy server-initiated sampling is deprecated under SEP-2577; OpenCode and Cursor already use fallback. ([SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577)) |
| Initial fallback review | `prepare_prd_assessment()` ingests, batches, returns full prompts and a fingerprint; the host runs every batch and submits fragments to `score_prd_extraction()`, which reparses the file and verifies/scorers the JSON (`src/forge/mcp/server.py:799-873`). | Normally `3 x batch_count` host calls, orchestrated outside Forge. | This is the most portable model-ownership boundary and should become normative. |
| Dashboard review | `run_assessment_with_remediation()` ingests once to run extraction, then calls `assess_extractions()` for preliminary framing facts, again for framed output, potentially again with coverage, and `begin_remediation()` again to create state (`src/forge_dashboard/runner.py:68-150`). | Three extraction calls, optional one framing call, **one** coverage call. | Ingestion and complete assessment are recomputed repeatedly in one request. Dashboard coverage lacks MCP's three-run consolidation. |
| Choose question | `plan_questions()` selects the first missing required field of the highest-ranked failed criterion; `plan_question_queue()` materializes every currently missing field. Text comes from `FieldSpec.remediation_question` or `framing_questions` (`src/forge/score/planner.py:120-212`, `215-291`). | No model unless a separate advisory tool is called. | Selection is deterministic, but the semantic unit is a preset field, not the smallest document-specific gap. |
| Contextualize question | `build_candidates()` lists up to five already-satisfied facts; the model returns one index; `apply_choice()` appends the selected static description and quote to the static question (`src/forge/score/contextualize.py:94-134`, `364-449`). | One optional closed-set call. | It selects context, not a question. It cannot identify what is specifically ambiguous or ask for the missing decision implied by two passages. |
| Answer | `record_answer()` binds exact text to the queue head, appends a pending delta answer, and pops the queue without model work (`src/forge/remediation.py:343-368`). SQLite persists the whole Pydantic state JSON with optimistic versioning and operation idempotency (`src/forge/sessions.py:424-539`). | No model; score remains stale until checkpoint. | Good boundary, but queued sibling questions remain even when one answer would satisfy them. |
| Reevaluation | At a checkpoint, only pending-answer blocks, affected criterion schemas, and previous values enter `build_delta_extraction_plan()`; verified patches replace those criteria in every baseline run and Python rescoring rebuilds the queue (`src/forge/extract/delta.py:51-155`, `171-241`; `src/forge/remediation.py:371-456`). | One delta call per checkpoint. | Efficient and criterion-bound, but deep review is not rebuilt and list-item verifier evidence is not durable. |
| Summary | `build_narrative_report()` deterministically projects counts, gates, consumer blockers, queue gaps, next step, and run agreement (`src/forge/score/report.py:31-131`). | No model. | Faithful to readiness state, but not a synthesis of criterion ambiguities/contradictions and can inherit duplicate queue records. |
| Revision | Dashboard revision endpoints participate in session transitions; MCP `preview_prd_revision`, `write_integrated_prd_revision`, and `write_prd_revision` accept source paths and caller-supplied answers/plans directly (`src/forge/mcp/server.py:1216-1254`). | No model for writing; final assessment is caller responsibility in MCP. | The MCP revision surface bypasses authoritative session state, verified-answer membership, optimistic version, operation id, and lifecycle transitions. |

The runtime model-call budget is therefore not simply “three extraction calls.” A one-batch dashboard review can perform three extraction calls, one framing call, one coverage call, and several full deterministic reassessments/reingestions. An MCP fallback can add three coverage calls, three consistency calls, one framing call, and one contextualization call after `3 x batches` extraction calls. `Completion` stores only text and model (`src/forge_dashboard/llm.py:20-24`, `67-83`), so documented phase-level token accounting is not implemented for dashboard provider usage; `RemediationState.delta_input_characters` records prompt characters, not tokens (`src/forge/remediation.py:71-74`).

### The rubric is an evaluation contract, not a questionnaire

`prd.v0.yaml` currently combines at least six responsibilities: criterion definitions, field extraction schemas, objective constraints, weights/gates, remediation prose, and framing variants (`src/forge/rubric/library/prd.v0.yaml:99-524`). This makes static questions look intrinsic to scoring even though they are only one presentation strategy. For example, the problem criterion embeds “What goes wrong for users today?” plus three framing variants (`prd.v0.yaml:100-152`), while edge-case questions are ten fixed strings in `EDGE_CASE_TYPES` (`src/forge/score/edge_coverage.py:19-102`).

The target rubric should instead be a **versioned evaluation contract**:

| Contract concern | Keep in rubric | Move out of rubric |
|---|---|---|
| Meaning | Criterion purpose, downstream consumers, applicability, required assertions/decisions, objective constraints, examples and hard negatives | Per-document conclusions |
| Scoring | Weight, gate, verdict policy, band policy; hidden from model | Numeric score assignment by LLM |
| Evidence | Required evidence roles and minimum evidence-set shape, such as problem + affected actor + support | One model-selected field quote standing in for all support |
| Semantic evaluation | Allowed statuses and issue taxonomy: supported, unsupported, ambiguous, contradictory, not applicable | Preset field-presence as the only judgment |
| Remediation | Answer contract, such as “must identify owner and decision date,” plus safe fallback template | Primary static question sentence and four hand-authored variants for every field |
| Validation | Criterion-specific deterministic checks and evidence constraints | Organization-validity claims without independent labels |

This preserves reproducibility: the contract remains fixed and versioned, but the model evaluates how one PRD satisfies it. Python still rejects unlocatable evidence, enforces objective constraints, maps criterion status to credit, applies gates, and selects the band. **The LLM may judge entailment, ambiguity, contradiction, and formulate an advisory question; it may not assign points, weights, gates, severity, or bands.**

## Twelve concrete defects distort evidence, questions, and cost

The following are implementation findings, not generic risks. Several conflict with stronger claims in canonical documentation and should be fixed before adding infrastructure.

| Priority | Defect or hotspot | Evidence and consequence | Correction |
|---|---|---|---|
| P0 | Static questions are the product's central architectural error. | `FieldSpec` stores `remediation_question` and `framing_questions`, and `plan_question_queue()` copies them directly (`src/forge/rubric/models.py:72-88`; `src/forge/score/planner.py:249-289`). Closed-set contextualization chooses an existing satisfied fact, not the missing fact or decision (`src/forge/score/contextualize.py:94-134`, `426-449`). | Select a verified criterion gap, then ask the host LLM for one bounded, gap-specific `QuestionPlan`; validate referenced span/gap IDs and retain a deterministic fallback. |
| P0 | Quote existence does not establish entailment. | `verify_run()` checks only that `evidence.quote` appears in a block; `FieldExtraction.is_satisfied()` separately checks that the extracted value is non-placeholder/pattern-matching, but does not prove the quote supports that value (`src/forge/extract/batch.py:127-178`; `src/forge/extract/models.py:45-63`). A model can attach an existing numeric quote to a different claimed value. | Store claim-to-span support judgments; require value/span consistency where mechanical, otherwise a closed semantic `supports / contradicts / unclear` judgment before credit. |
| P0 | Multi-batch consolidation is first-satisfied and lossy. | `_consolidate_fragments()` takes the first satisfied field across fragments and discards later satisfied candidates (`src/forge/extract/batch.py:299-353`). Preconsolidation claims partly protect deep review, but readiness, satisfied-field context, and criterion evaluation retain one arbitrary witness. | Preserve all verified field/criterion evidence occurrences; derive a criterion evaluation from evidence sets rather than selecting one witness. |
| P0 | Single-batch schema validation is missing. | Fragment paths call `_validate_fragment_schema()` (`src/forge/extract/batch.py:88-103`), but the non-fragment path calls `verify_run()` directly (`src/forge/extract/batch.py:105-112`). A one-batch `{"criteria": []}` is accepted; tests explicitly use this (`tests/test_mcp.py:101-168`, `tests/dashboard/test_runner.py:23-50`). | Run one schema validator for both direct and fragmented runs. Reject missing, duplicate, and unknown criteria/fields everywhere. |
| P0 | Parser structure limits evidence and deep-review recall. | PDF is one plain-text page block; DOCX retains only one current heading, flattens table rows after deleting empty cells, appends headers/footers, and inventories images without anchors (`src/forge/ingest/document.py:73-167`). `SourceBlock` lacks node type, heading path, table coordinates, list depth, links, bbox, and image relationships (`src/forge/ingest/models.py:14-33`). D-051 measured proxy recall at 3/19 and traced a missed conflict to PDF line fragmentation (`docs/DECISIONS.md:982-1011`). | Add source-neutral snapshots and canonical typed nodes; benchmark Docling and PyMuPDF4LLM before replacement. Keep current parser as migration fallback because parser identity affects persisted evidence. |
| P1 | Repeated ingestion and assessment passes waste CPU and create drift opportunities. | Each native sampling resolver reparses; scoring reparses; dashboard framing, coverage, final response, and remediation initialization each call full assessment paths (`src/forge/mcp/server.py:558-577`; `src/forge/service.py:78-84`; `src/forge_dashboard/runner.py:81-150`). Advisory preparation often calls `assess_extraction_json()` and then `prepare_assessment_input()` again (`src/forge/mcp/server.py:1951-1989`). | Create one immutable `DocumentSnapshot`/`ReviewBaseline` per source+parser+rubric fingerprint and pass it through service operations. Cache only by exact fingerprints. |
| P1 | The queue duplicates questions before checkpoints. | `plan_question_queue()` enqueues every missing field up front (`src/forge/score/planner.py:246-290`); `record_answer()` merely pops one (`src/forge/remediation.py:343-368`). One broad answer may satisfy multiple fields, but users still see queued siblings until a checkpoint, contrary to adaptive-question expectations. | Queue stable `gap_id`s, not all field prompts. After each answer, either run a cheap answer-to-current-gap validator or suppress same-criterion siblings until checkpoint. Prefer one unresolved decision at a time. |
| P1 | Edge-case coverage has a synthetic queue gap. | `_decorate_edge_question()` mutates only the first queued `edge_cases_and_states` question into the ledger's first uncovered cell (`src/forge/remediation.py:134-166`). After it is popped, remaining prebuilt questions are ordinary broad field prompts; the next ledger cell appears only after checkpoint/rebuild. | Represent each missing coverage cell as a real gap/question identity or derive the next cell lazily from the ledger on every turn. Do not mutate an unrelated field queue entry. |
| P1 | `item_evidence` is lost on serialization. | `FieldExtraction.item_evidence` is `exclude=True` (`src/forge/extract/models.py:38-43`). Sessions serialize `RemediationState` to JSON and restore it (`src/forge/sessions.py:279`, `496`, `669-677`), so independently verified list-item spans disappear after persistence. Requirement candidates and deep-review list claims can therefore differ before and after restart. | Make verifier output a first-class serializable evidence record, separated from raw model payload rather than excluded from the domain model. Add round-trip tests. |
| P1 | Deep review becomes stale after checkpoints. | `begin_remediation()` computes `deep_review` once (`src/forge/remediation.py:254-281`). `_snapshot()` rescales assessment/report/queue/coverage but neither rebuilds nor invalidates deep review (`src/forge/remediation.py:169-222`), and `apply_checkpoint()` preserves the old field by omission (`src/forge/remediation.py:428-447`). | Recompute affected advisory evaluations from merged evidence or mark deep review with `as_of_revision` and stale components. Summary must never present pre-answer findings as current. |
| P1 | Dashboard edge coverage is a single-run semantic judgment. | `_classify_edge_case_coverage()` calls the provider once and returns its ledger (`src/forge_dashboard/runner.py:165-190`); MCP coverage requires three completions and consolidates them (`src/forge/mcp/server.py:2248-2252`, `2282-2323`). | Use one shared inference-plan contract with declared run count and consolidation in both adapters. If dashboard runs once for cost, expose lower confidence and prevent silent parity claims. |
| P1 | MCP revision tools bypass the session lifecycle. | The workflow advertises revision transitions (`src/forge/sessions.py:113-133`), but MCP preview/write tools accept arbitrary source paths, answers, plans, and actions without `review_session_id`, `session_version`, or `operation_id` (`src/forge/mcp/server.py:1216-1254`). | Add session-bound preview/approve/materialize/finalize operations. Keep low-level file functions internal or explicitly label stateless tools as unsafe compatibility APIs pending removal. |
| P2 | Deep-review source scanning treats line/sentence chunks as claims. | `mechanical_claim_occurrences()` splits on punctuation and every newline (`src/forge/deep_review.py:166-221`). This is the measured claim-granularity bottleneck and violates the intended “source semantic unit” representation. | Reconstruct source-semantic units before claim extraction; do not make arbitrary chunks the intellectual representation and never score chunks. |
| P2 | Absence, jobs, and source integrations are not implemented. | Core contains no Confluence/URL adapter, retrieval index, embeddings, pgvector, task/job system, modern `InputRequiredResult`, or source snapshot DTO; dependencies confirm this (`pyproject.toml:6-25`). | Document these as target capabilities or deferred options, not current architecture. Adopt peer-server composition for Confluence and wait on jobs until a real asynchronous requirement exists. |

Two subtler model-call issues follow. First, three repeated full extraction runs estimate consistency but multiply identical context and correlate on the same prompt; they are not independent human judgments. Preserve run agreement, but measure whether targeted second-pass adjudication beats blind triplication. Second, prompt batching currently repeats **all criterion schemas in every document batch** (`src/forge/extract/prompt.py:22-38`, `102-117`). This makes each batch ask about criteria whose likely evidence is elsewhere, then first-satisfied consolidation hides the resulting redundancy. Criterion-oriented context packing should reduce this, with an exhaustive backstop for any negative conclusion.

## External projects offer components, not a replacement architecture

The comparison below covers every project examined in the research notes. “Hierarchy/media” asks whether authorial hierarchy, images, tables, and links survive; “token posture” describes likely model-context effects, not vendor benchmark claims. Dispositions apply to Forge's current single-PRD scope.

| Project | Relevance and overlap | License; runtime/provider/deployment | Hierarchy, images, tables, links; token posture | Invasiveness | Decision |
|---|---|---|---|---|---|
| `multi-agent-prd-reviewer` | Sequential technical/UX/legal critique and Slack presentation overlap review breadth, not evidence authority. | BSD-3-Clause; Python; direct Anthropic SDK/key; hard-coded model. | Sends the full PRD to three agents and accumulates prior critiques; loose section references, opaque Markdown findings. | High provider/context coupling. | **BENCHMARK** breadth; **BORROW IDEAS** role navigation; architecture **NOT NEEDED**. ([orchestrator](https://github.com/dimospapadopoulos/multi-agent-prd-reviewer/blob/c0a076ddc07ea5bc4b1fc851f708a05de10b19d7/orchestrator.py#L52-L107)) |
| `claude-requirements-reviewer` | Minimal one-prompt weighted baseline and readable finding format. | README says MIT but no license file at inspected revision; Claude Code prompt only. | Host context supplies the document; no parser, hierarchy, media model, schema enforcement, persistence, or token accounting. | Low runtime, unacceptable score authority. | **BENCHMARK** minimal baseline; production **NOT NEEDED**; do not copy text until license is clear. ([skill](https://github.com/amodiahs/claude-requirements-reviewer/blob/6e5f4d05ac4cf80a98bb9d25a4d48097c1e820ca/SKILL.md#L31-L258)) |
| `prd-agents-framework` | Closest review-to-revision governance: matrices, root-cause deflation, dispositions, exact Q&A, ticketed revisions. | MIT; Claude Code skills, Python validators, files/git; host model. | Agents reread files; strong artifact lineage but model citations are not universally relocated; no dedicated multimodal parser. | Medium/high process adoption. | **BENCHMARK**; **BORROW IDEAS** dispositions, Q&A lineage, delta verification; model-owned PASS/FAIL **NOT NEEDED**. ([senior PM](https://github.com/vshidlovsky/prd-agents-framework/blob/36504811641d79c50a4caa1f76d223fc4caea797/agents/prd-senior-pm.md#L89-L218)) |
| NatPRD | Authoring interview, conditional probes, `[TBD]`, source-consent preview. | BSD-3-Clause; Claude skill plus Python validator; host model. | Template-driven Markdown; links/citations handled by prompt; no immutable ordinary-answer ledger; repeated revalidation. | Medium product-mode change. | **BENCHMARK** interview UX; **BORROW IDEAS** unknowns/consent/buttons; static authoring interview **NOT NEEDED** for review mode. ([workflow](https://github.com/anatasof/NatPRD/blob/66e8d534082763456ebc0925963d4d18e50c6698/SKILL.md#L250-L326)) |
| Docling | Best common PDF/DOCX structured-ingest candidate. | MIT library; Python; local PyTorch layout/table/OCR models; GPU optional; no provider required. | Typed tree, reading order, page/bbox/charspan provenance, table grids, pictures/captions; rich JSON is audit sidecar, not prompt text. | Medium/high if default; moderate as optional adapter. | **BENCHMARK**, then **ADOPT behind adapter only if gates pass**. ([Docling document model](https://docling-project.github.io/docling/concepts/docling_document/)) |
| Docling MCP | General MCP wrapper around Docling conversion/cache/generation/RAG. | MIT; Python/MCP; local models or Docling Serve URL/key; optional Milvus/LlamaIndex. | Same Docling parse; adds cache key and protocol boundary, not fidelity. | High and duplicative. | **NOT NEEDED**; embed library directly if selected. ([Docling MCP](https://github.com/docling-project/docling-mcp)) |
| Marker | PDF conversion accuracy challenger. | Apache-2.0 code; modified OpenRAIL model terms; Python/PyTorch; package includes provider SDKs; local VLM/container options. | Recursive blocks, polygons, tables as HTML, images/base64, section hierarchy; potentially very large context. | Very high runtime, licensing, provider surface. | **BENCHMARK** offline ceiling only. ([Marker](https://github.com/datalab-to/marker)) |
| Unstructured | Enterprise partition/ETL/RAG element model. | Apache-2.0; Python; local or remote hi-res models; Poppler/Tesseract/LibreOffice; telemetry default. | Typed elements, IDs, coordinates, parent/depth, links, table HTML, image crops; chunks can carry original elements. | High stack breadth. | **BORROW IDEAS** for provenance; full stack **NOT NEEDED**. ([document elements](https://docs.unstructured.io/open-source/concepts/document-elements)) |
| PyMuPDF4LLM | Least-invasive PDF layout control over Forge's current PyMuPDF path. | AGPL-3.0 or commercial; Python; packaged CPU GNN; no provider/GPU; Office support commercial. | PDF boxes/spans/words/bboxes, tables, links, images; no cross-format tree; JSON duplicates text. | Low/medium technically, material legal risk. | **BENCHMARK**. ([API](https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/api.html)) |
| MarkItDown | Compact generic Markdown conversion. | MIT; Python; provider-free base, optional Azure/LLM integrations. | Headings/lists/tables/links may survive, but no stable item IDs, bboxes, hierarchy, or evidence spans. Token-light because provenance is discarded. | Low package, high evidence regression. | **NOT NEEDED**. ([MarkItDown](https://github.com/microsoft/markitdown)) |
| semchunk | Current oversized-block splitter. | MIT; Python; provider-free base. | Exact text offsets and overlap; no document hierarchy, images, tables, or links. Token boundary tool only. | Low. | **ADOPT/KEEP** only as overflow projection, never core representation. ([semchunk](https://github.com/isaacus-dev/semchunk)) |
| Chonkie | Alternative recursive/table splitting. | MIT; Python/JS; local base, optional models/stores. | Flat offset chunks and header-preserving table chunks; no authorial tree at chunk API. | Low/medium but duplicates semchunk. | **BORROW IDEAS**; **NOT NEEDED** as dependency now. ([Chonkie](https://github.com/chonkie-inc/chonkie)) |
| PostgreSQL FTS | Future persistent lexical retrieval and typed storage. | PostgreSQL License; server process; no provider/model. | Stores Forge hierarchy/metadata; GIN lexical ranking; media remains sidecar; reduces context through criterion retrieval. | Higher than in-process/SQLite. | **BENCHMARK later**; adopt before vectors only when scale/concurrency/persistence justify it. ([PostgreSQL text search](https://www.postgresql.org/docs/current/textsearch-controls.html)) |
| pgvector | Additive semantic retrieval in PostgreSQL. | PostgreSQL License; C extension; requires Forge-owned embedding model/provider lifecycle. | No hierarchy/media semantics itself; exact search can preserve recall, ANN trades recall; can reduce prompt context. | Medium/high because embeddings/versioning enter architecture. | **DEFER/BENCHMARK** only after lexical baseline and labels. ([pgvector](https://github.com/pgvector/pgvector)) |
| LlamaIndex | Auto-merging/recursive retrieval and property-graph abstractions. | MIT; Python; core broad but provider-neutral; metapackage adds OpenAI/LlamaCloud. | Default hierarchy is token-window-derived; auto-merge cannot recover missed leaves; table routing must be application-built. | Medium/high translation and dependency cost. | **BORROW IDEAS** (parent/neighbour merge); framework **NOT NEEDED** now. ([AutoMergingRetriever](https://github.com/run-llama/llama_index/blob/v0.14.6/llama-index-core/llama_index/core/retrievers/auto_merging_retriever.py)) |
| Haystack | Production RAG pipelines, hybrid retrievers, stores, routing. | Apache-2.0; Python; base currently includes OpenAI SDK; local/self-host options and telemetry. | Size-based hierarchy, metadata filters, rank fusion, table/media only through converters; retrieval-oriented token packing. | High relative to one PRD. | **BORROW IDEAS**; core dependency **NOT NEEDED**. ([Haystack components](https://docs.haystack.deepset.ai/docs/intro)) |
| Microsoft GraphRAG | Corpus-level entity/relationship/community retrieval and synthesis. | MIT; Python; LiteLLM completion + embeddings; Parquet/LanceDB/Azure options. | Text units, LM-derived graph and summaries; media/table semantics not evidence-grade; expensive indexing/context artifacts. | Very high and wrong problem. | **NOT NEEDED** for single-PRD review. ([overview](https://microsoft.github.io/graphrag/)) |
| Neo4j GraphRAG | Neo4j vector/graph retrieval and KG construction. | Apache-2.0 package; Neo4j service/license choices; LLM/embedding extras; APOC for KG builder. | Can store hierarchy/relations after Forge creates them; does not create evidence authority or completeness semantics. | Very high service/credential/index surface. | **NOT NEEDED** until a shared cross-document graph is required. ([guide](https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html)) |
| LangGraph | Durable graph execution, interrupts, replay, parallel writes, background deployment. | MIT OSS; Python/LangChain Core; provider-neutral runtime; durable stores optional; managed deployment adds Postgres/Redis/licenses. | Workflow graph, not document hierarchy; no image/table/evidence semantics; checkpoints can duplicate large state. | Medium/high migration and dual-authority risk. | **BORROW IDEAS**; no production adoption until branching/background/multi-party approval exists. ([persistence](https://docs.langchain.com/oss/python/langgraph/persistence)) |
| DeepEval | Offline LLM-as-judge and DAG evaluation. | Apache-2.0; Python; base OpenAI/telemetry/testing dependencies; custom models possible. | No document hierarchy/media provenance; judge context adds tokens; scores remain model-produced. | High if core, acceptable isolated dev environment. | G-Eval **BENCHMARK** narrowly offline; DAGMetric **BORROW IDEAS**; runtime **NOT NEEDED**. ([G-Eval](https://deepeval.com/docs/metrics-llm-evals)) |
| Ragas | RAG/LLM application evaluation. | Apache-2.0; Python; OpenAI, LangChain, datasets, optional embeddings; analytics default. | Context/answer/reference schema, not source-node/criterion evidence; no native media hierarchy. | High conceptual/dependency mismatch. | **NOT NEEDED**; borrow single-aspect metric discipline. ([metrics](https://docs.ragas.io/en/stable/concepts/metrics/overview/)) |
| Promptfoo | External prompt/model matrix and CI runner. | MIT; Node 22; many provider SDKs; local CLI/cache/history, telemetry default. | Can test frozen structured outputs; no evidence hierarchy itself; exports can contain prompts/media. | High embedded, low as pinned external process. | **BENCHMARK** offline only; adopt only if it deletes harness work. ([CLI](https://www.promptfoo.dev/docs/usage/command-line/)) |
| Atlassian MCP | Host-mediated Confluence acquisition and publishing peer. | Apache-2.0 repository; Atlassian-hosted Cloud service; OAuth/API token; broad host support. | Returned page structure/version fidelity varies by tool/host; attachments and large payloads require tests. Does not need to enter Forge prompts verbatim. | Low in Forge, auth remains with host. | **ADOPT AS PEER** with Forge snapshot contract; do not embed/proxy. ([Atlassian MCP](https://github.com/atlassian/atlassian-mcp-server)) |
| Official MCP 2026-07-28 MRTR/Tasks | Portable host-owned inference and future async execution. | MIT Python SDK 2.2.x; provider remains host-owned; host capability varies. | Structured tool data, not document hierarchy. MRTR carries model requests; Tasks are not yet in Python SDK 2.2.0. | Low for optional wrapper, high if made mandatory. | **ADOPT** prepare/submit and structured tools; **BENCHMARK** MRTR/Tasks; legacy sampling **DO NOT EXTEND**. ([MRTR](https://py.sdk.modelcontextprotocol.io/handlers/multi-round-trip/)) |

The decision across these projects is consistent: Forge needs better **source representation and criterion semantics**, not more agents, graph storage, or a generic RAG platform. `prd-agents-framework` is the best governance benchmark, NatPRD the best interaction benchmark, Docling the best ingestion candidate, Promptfoo the best optional outer harness, and Atlassian MCP the correct Confluence acquisition peer. None should become scoring authority.

## A criterion ledger and source snapshot form the smallest target

### Target component and data flow

The target separates acquisition, canonical source representation, retrieval projections, semantic evaluation, deterministic scoring, question generation, and workflow state. Chunks are transport projections only. **No chunk receives a score, and arbitrary chunks are not the core intellectual representation.**

```text
local file | inline bytes/text | external snapshot from peer MCP
                         |
                         v
              SourceSnapshotAdapter
                         |
          immutable bytes + origin/version metadata
                         v
       ParserAdapter (current | optional Docling)
                         |
        Canonical SourceNode tree/ordered ledger
       paragraphs, lists, tables/cells, captions,
       pictures, links, headers; stable exact spans
              |                         |
              |                         +--> overflow/retrieval projections
              |                              (semchunk; never authority)
              v
       exhaustive source coverage ledger
              |
       criterion-specific context planner
       lexical/structure candidates + unseen-node fallback
              |
              v
     host LLM CriterionEvaluation runs
 evidence sets | claims | gaps | ambiguity | contradiction | confidence
              |
              v
 Python schema + exact-span + entailment checks
              |
        +-----+--------------------+
        |                          |
        v                          v
 deterministic readiness       advisory consistency/
 verdicts, weights, gates      deep-review projection
        |                          |
        +-------------+------------+
                      v
             deterministic gap priority
                      |
             host LLM QuestionPlan
             one gap, one answer contract
                      |
             SQLite session + answer event
                      |
        criterion-local answer reevaluation
```

### Smallest sensible domain schema

Do not begin with a normalized relational warehouse. Introduce versioned Pydantic contracts and persist compact JSON in the existing SQLite authority; normalize only identities needed for discovery, concurrency, and migration.

```text
SourceSnapshot v1
  snapshot_id, source_sha256, media_type, display_name
  origin_kind: local_file | inline_content | external_snapshot
  canonical_uri?, external_revision?, retrieved_at?, adapter_id/version
  parser_id/version/options_hash, normalized_sha256

SourceNode v1
  node_id, parent_id?, ordinal, kind
  content, section_path[], page?, bbox?, source_start?, source_end?
  table{row?, column?, rowspan?, colspan?, header?}?
  link_target?, asset_id?, provenance

EvidenceSpan v1
  span_id, node_id, start_char, end_char, exact_quote, normalized_quote
  provenance: source | supplemental_answer | ocr

CriterionEvaluation v1
  evaluation_id, criterion_id, criterion_contract_version, run_id
  applicability: applicable | not_applicable | unclear
  status: supported | partial | unsupported | contradictory | unclear
  evidence_sets[]: {role, span_ids[], support: supports|contradicts|unclear}
  claims[]: {claim_id, value, span_ids[]}
  gaps[]: {gap_id, kind, required_decision, affected_consumers[], answer_contract}
  ambiguities[]: {issue_id, span_ids[], alternatives[]}
  contradictions[]: {issue_id, left_span_ids[], right_span_ids[], relation}
  confidence: {agreement, run_count, basis}

QuestionPlan v1
  question_id, evaluation_revision, criterion_id, gap_id
  evidence_span_ids[], question_text, answer_contract
  generation: model_id?, prompt_version, fallback_used

AnswerEvent v1
  answer_id, question_id, criterion_id, gap_id, exact_text
  requirement_quote?, edge_case_id?, taxonomy_version?
  status: pending | credited | uncredited, created_at, checkpoint_id?

ReviewBaseline v1
  snapshot_id, rubric_id/version, plan_fingerprint
  extraction/evaluation run ids, source_coverage_ledger
  scored_assessment, deep_review, summary, revision
```

This schema deliberately does not include a vector, a graph database node, a model-assigned score, or a generic `chunk_score`. The existing bounded claim graph remains a projection from verified claims. `EvidenceSpan` fixes duplicate-text ambiguity by identifying the exact node and offset rather than relying on `locate_quote()`'s first match (`src/forge/ingest/models.py:89-110`). `CriterionEvaluation` supports multiple evidence sets and contradictory evidence without collapsing to one field witness. `QuestionPlan` decouples evaluation requirements from user-facing prose.

### Minimal SQLite migration

The current database stores session identity columns plus one opaque `state_json`, operations, and events (`src/forge/sessions.py:162-208`). Preserve that design initially:

| Migration | Data change | Existing-session behavior |
|---|---|---|
| M1 | Add `state_schema_version INTEGER NOT NULL DEFAULT 1`, `snapshot_id TEXT`, `parser_fingerprint TEXT`, and `evaluation_revision INTEGER NOT NULL DEFAULT 0` to `review_sessions`. | Existing rows deserialize as legacy v1; no silent reparse. Resume can finish under old parser/rubric or require explicit migration when semantics differ. |
| M2 | Add `document_snapshots(snapshot_id, source_sha256, origin_json, parser_fingerprint, normalized_sha256, snapshot_json, created_at)` with unique exact fingerprint. | New reviews reuse exact snapshots. Existing sessions retain path/hash and lazily materialize a snapshot only after byte hash verification. |
| M3 | Add `review_artifacts(review_session_id, artifact_type, artifact_version, artifact_revision, artifact_json, created_at)` for criterion ledgers, retrieval traces, summaries, and revision plans. | Keep `state_json` as the authoritative workflow head; artifacts are immutable revisions referenced by ID. Avoid immediately splitting every object into tables. |
| M4 | Add `question_id`, `gap_id`, and `evaluation_revision` to persisted pending/verified answer models. | Legacy answers map to deterministic IDs from criterion/field/taxonomy identity and are marked `legacy_field_question`. |
| M5, only if measured need appears | Move source nodes and lexical index into SQLite FTS5, or PostgreSQL tables for remote/multi-user operation. | This is an operational migration, not required for criterion evaluation. pgvector remains a later nullable projection. |

Parser version is part of identity because changing PDF reading order or table serialization can change source hashes, quote locations, claims, and scores. A review must never resume against a silently different parser projection. Persist raw source hash, parser fingerprint, normalized hash, rubric version, and evaluation-contract version separately.

### Separate target flows

**Ingest.** `SourceSnapshotAdapter.acquire()` accepts a trusted local path, inline content, or an externally fetched immutable snapshot. It hashes bytes/content, records origin and external revision metadata, and invokes a versioned parser adapter. The parser produces canonical typed `SourceNode`s and visual assets. Python verifies stable IDs/order and creates a source coverage ledger. Rich Docling JSON, if used, remains a sidecar; compact nodes feed prompts. Confluence follows a peer flow: host authenticates to Atlassian MCP, reads a page, creates a Forge external snapshot with page ID/version/retrieval metadata, then calls Forge. Forge never owns Atlassian credentials or automatically writes back.

**Initial review.** Build one baseline from the snapshot. For each criterion, the context planner chooses structure/lexical candidates and records a retrieval trace. The host LLM returns `CriterionEvaluation` records, not numeric scores. Positive support must cite exact span IDs; Python verifies spans and objective constraints. Before declaring a criterion unsupported/absent, Forge sends all canonical nodes not yet evaluated for that criterion through exhaustive fallback batches. Repeated runs operate over the same fingerprinted criterion plan. Python consolidates evidence/support conservatively, then derives current verdict credits, gates, bands, consumer gaps, and deep-review projections.

**Choose question.** Python ranks unresolved `gap_id`s by failed gate, expected band effect, affected consumers, contradiction/ambiguity type, and stable ID. It sends only the selected criterion contract, verified evidence sets, the selected gap, and tightly bounded neighbouring context to the host LLM. The model returns one `QuestionPlan` with a single sentence and an answer contract; it cannot select a score or a different gap. Python validates IDs, strips unsupported quotations, limits length, rejects extra claims, and falls back to a deterministic contract template. This is the crucial change from “choose one satisfied fact to decorate a preset sentence” to “formulate the smallest question that resolves this verified gap.”

**Answer.** Record the exact answer against `question_id`, `gap_id`, criterion, and optional taxonomy cell in the existing optimistic/idempotent session transaction. Do not eagerly queue sibling field questions. The next turn either asks a different already-independent gap or requests a checkpoint. A lightweight deterministic check can suppress exact duplicate questions, but semantic credit waits for reevaluation.

**Reevaluation.** Build a criterion-local delta containing pending answers, the relevant criterion contract, prior evidence sets, selected gaps, and no unchanged PRD body. The host returns patches to criterion claims/evidence/gaps only. Python verifies supplemental spans and merges them into every run without fabricating run agreement. Recompute affected criterion evaluations, score, deep review, summary, and question priority; stamp all projections with one `evaluation_revision`. If an answer resolves several gaps in the same criterion, all disappear together. Edge-case cells use the same gap identity instead of a synthetic mutation of a broad field question.

**Summary.** Generate two deterministic projections from the same current revision: primary deep-review decision blockers and supporting readiness audit. Include `as_of_evaluation_revision`, evidence links, unresolved decisions, contradictions/ambiguities, consumer effects, confidence basis, and next question. A model may improve wording only as a non-authoritative rendering layer after the structured summary exists; default output remains deterministic.

**MCP.** Make `prepare_* -> host inference -> apply_*` the normative flow. Add optional MCP 2026-07-28 multi-round-trip `InputRequiredResult(CreateMessageRequest)` only as a capability-detected convenience that invokes the same application service. Stop adding features to legacy `sampling/createMessage`; retain it temporarily for negotiated legacy clients. Use ordinary tool arguments for paths/snapshots and elicitation only for small choices or approvals. Keep SQLite review identity authoritative; benchmark MCP Tasks only after SDK and target-host support exist. Resources may expose immutable snapshots/artifacts by URI, but assessment must not depend on resources, prompts, or peer-server server-to-server calls. ([MCP specification](https://modelcontextprotocol.io/specification/2026-07-28))

## Five phases correct the model without rewriting Forge

### Phase 0 fixes correctness before changing semantics

**Files/components:** `src/forge/extract/batch.py`, `extract/models.py`, `remediation.py`, `sessions.py`, `forge_dashboard/runner.py`, `mcp/server.py`, and focused tests. Apply `_validate_fragment_schema()` to direct runs; serialize item-level evidence; rebuild or explicitly invalidate deep review at checkpoints; make coverage run-count/consolidation shared; replace edge-cell queue mutation with lazy cell selection; bind MCP revision operations to sessions; deduplicate/suppress sibling queued questions.

**Preserved:** current rubric, score/bands, parser, extraction payload, MCP fallback, dashboard, SQLite identity, answer-delta protocol. **New:** schema parity, durable list evidence, revision-consistent projections, adapter parity, lifecycle-safe revisions. **Data implications:** add state schema version and evaluation revision; migrate existing JSON with explicit defaults. **Tests:** direct-run missing/duplicate/unknown criteria and fields; session JSON round-trip of list `item_evidence`; answer satisfying two same-criterion fields does not ask the sibling; multiple edge cells advance correctly; deep review revision changes after checkpoint; dashboard three-run coverage parity; MCP revision rejects wrong session/version/answer set; stale and duplicate operations remain unchanged.

### Phase 1 freezes source snapshots and benchmarks parsing

**Files/components:** add `forge/ingest/snapshot.py`, `forge/ingest/adapters.py`, `forge/ingest/nodes.py`; adapt `ingest/document.py`, `ingest/batching.py`, `ingest/visuals.py`, service DTOs, and session fingerprints. Build a developer-only benchmark comparing current parser, direct Docling, and PyMuPDF4LLM PDF control. Do not add Docling to the default dependency yet.

**Preserved:** `NormalizedDocument` projection, exact quote verification, exhaustive batching, semchunk overflow, visual advisory boundary. **New:** source-neutral origin metadata, parser fingerprint, typed nodes/relationships, table cells, heading paths, links, image anchors, optional bbox, canonical snapshot cache. **Data implications:** immutable `document_snapshots`; old reviews remain bound to legacy parser fingerprints. **Tests:** repeated deterministic node hashes; full canonical-node batch coverage; duplicate quote resolves by node/span; DOCX body/table/header/footer order; PDF multiline requirement; table merged/empty cells; link targets; image-caption/section anchors; offline/no-network parsing; parser output does not inflate prompt tokens beyond a preregistered limit. Adoption requires the evidence, known-defect, structure, safety, token, operational, license, and complexity gates defined in the research notes. ([Docling chunking](https://docling-project.github.io/docling/concepts/chunking/))

### Phase 2 introduces criterion evaluation beside field extraction

**Files/components:** add `forge/evaluate/models.py`, `prompt.py`, `verify.py`, `consolidate.py`; extend rubric models/loader with criterion assertions, evidence roles, semantic statuses, hard negatives, and fallback question templates. Add an adapter that converts current field extraction into legacy `CriterionEvaluation` so scoring remains stable while new evaluations run in shadow mode.

**Preserved:** current weights, gates, bands, verdict credits, consumer views, quote verification, repeated-run confidence, no numeric LLM authority. **New:** multiple evidence sets, explicit support relation, gaps, ambiguities, contradictions, confidence, and exact evidence IDs. **Data implications:** immutable criterion-evaluation artifacts keyed by snapshot/rubric/plan/run; existing field extraction stays readable during migration. **Tests:** quote exists but does not entail value; one quote supports multiple compatible claims; conflicting spans remain both present; unsupported aspirations/examples; N/A evidence; cross-batch evidence sets; pessimistic run consolidation; score parity fixtures; no criterion can become present from unverified spans.

Exit only when shadow evaluations reproduce intended deterministic bands on the corpus and improve human/proxy evidence alignment without new hard-negative violations. Labels are needed to validate quality claims, not to enable runtime.

### Phase 3 replaces preset questions with gap-specific plans

**Files/components:** add `forge/questions/models.py`, `prepare.py`, `apply.py`; change `score/planner.py` to rank gap IDs; deprecate `FieldSpec.remediation_question` and `framing_questions` as primary behavior while retaining fallback templates for old/external rubrics. Replace contextualization advisory with a bounded question-generation advisory. Update remediation/session/dashboard/MCP DTOs to carry `question_id`, `gap_id`, evidence IDs, answer contract, generation metadata, and evaluation revision.

**Preserved:** one question per turn, deterministic priority, criterion/cell-bound answers, exact answer retention, checkpoints, safe fallback, no scoring effect from wording. **New:** smallest PRD-specific question, contradiction/ambiguity questions, same-answer multi-gap closure, question audit lineage. **Data implications:** migrate old field questions to `legacy_field_question` identities; events retain displayed question and selected gap. **Tests:** generated question references only allowed evidence/gap IDs; prompt injection cannot alter output contract; malformed output falls back; no unsupported quote reaches user; no duplicate question after answer; question stable across serialization; tests compare relevance/answerability against NatPRD and noise against `prd-agents-framework` using blinded human ratings.

### Phase 4 optimizes context and modernizes MCP only after measurement

**Files/components:** add an in-process criterion index/retrieval trace, likely over canonical nodes; optionally add SQLite FTS5. Refactor service operations to accept a loaded baseline rather than repeatedly calling `prepare_assessment_input()`. Implement optional MRTR wrappers over existing prepare/apply services. Add external snapshot input and document the Atlassian peer flow.

**Preserved:** every canonical node remains evidence-eligible; absence requires exhaustive fallback; exact spans and source coverage remain authoritative; host owns model/provider and peer credentials. **New:** criterion-sized prompts, deterministic parent/neighbour/table expansion, retrieval traces, snapshot reuse, optional MRTR. **Data implications:** indexes are disposable projections keyed by normalized hash and retrieval version; they never become evidence truth. **Tests:** retrieval recall at budget, all-node coverage, positive and absence cases, prompt/token reduction, no score drift under retrieval order, cross-client MRTR/fallback parity, large peer-result handoff, source revision mismatch, and no credential persistence.

PostgreSQL FTS is the next storage candidate only when SQLite/in-process operation fails measured persistence, concurrency, cross-document, or latency needs. pgvector comes after a lexical baseline and only as an additive exact-search recall channel; ANN cannot be an eligibility boundary. LlamaIndex and Haystack should not be adopted merely to implement parent/neighbor expansion or rank fusion, which are small Forge-owned algorithms. A custom “RAG” component should therefore mean a compact **context planner plus coverage ledger**, not a generic answer-generation stack.

### Phase 5 validates, then revisits optional infrastructure

Run blinded internal readiness and finding-label studies through existing `forge-calibration` and `forge-review-eval`. Add question usefulness, answerability, question-to-resolution count, unsupported assumption rate, revision application status, introduced-defect rate, token/latency by phase, and test/retest stability. Promptfoo may wrap frozen outputs and provider matrices in an isolated process if it reproduces Forge metrics exactly and reduces maintenance. DeepEval G-Eval may benchmark one subjective property, such as whether a frozen finding states an actionable decision, but never becomes ground truth. Ragas remains unnecessary.

Only then revisit LangGraph for a concrete requirement: durable fan-out with partial-failure recovery, process-independent background jobs, branch selection/merge, or multiple independent approvers. Any spike must retain `review_session_id`, external `session_version`, request-digest-bound `operation_id`, one authoritative head, source/rubric/parser fingerprints, semantic events, no-overwrite revisions, and existing crash/concurrency tests. Microsoft GraphRAG, Neo4j GraphRAG, and a graph database remain out until the product becomes cross-document corpus retrieval or the bounded in-process graph fails measured scale.

## Explicit decisions keep ownership and adoption unambiguous

| Decision | Position now | Revisit gate |
|---|---|---|
| Docling | **BENCHMARK; conditionally adopt as optional direct parser adapter.** Never feed full JSON to the LLM and do not embed Docling MCP. | PRD-specific benchmark passes exact-span, multiline, hierarchy, table, token, offline, model-license, and operational gates. |
| Chunking | **Keep semantic source nodes canonical and semchunk only for oversized projections.** Do not score chunks or use arbitrary token windows as requirements. | Change splitter only if offset fidelity or table overflow benchmark improves. |
| PostgreSQL/pgvector | **No immediate infrastructure.** In-process structures and SQLite first; PostgreSQL FTS before vectors; pgvector additive only. | Persistent multi-document search, remote concurrency, or measured local latency/size failure; embeddings must improve labelled recall. |
| Custom RAG vs LlamaIndex/Haystack | **Build the small Forge-owned context planner and exhaustive coverage ledger.** Borrow parent/neighbour expansion and rank fusion; do not adopt either framework. | Heterogeneous retriever/query objects or a multi-team configurable RAG platform becomes an actual product requirement and framework adoption deletes net code. |
| DeepEval | **Offline narrow benchmark only; no core dependency or runtime score.** | Independent human labels exist for the qualitative property being judged and repeated judge stability is acceptable. |
| Ragas | **Not needed.** | Forge becomes primarily a RAG answer-quality product, which is outside current scope. |
| Promptfoo | **Benchmark as external dev CLI.** | Exact parity with Forge evaluators, hermetic operation, useful CI reports, and less maintenance. |
| LangGraph | **Borrow ideas; do not adopt now.** | Durable branching, background execution, partial-failure fan-out, or multi-party approvals are specified and the spike preserves Forge identity/idempotency. |
| GraphRAG / Neo4j GraphRAG | **Not needed.** Keep bounded graph as advisory projection. | Cross-document portfolio graph, repeated corpus questions, shared graph persistence, Cypher product capability, or measured in-process failure. |
| Custom components | **Forge owns source snapshot, canonical nodes, evidence spans, criterion contract/evaluation, score, question priority, workflow identity, revision, and audit.** | Implementations may be replaced only behind these contracts. |
| Server ownership | **Forge server owns deterministic semantics and durable review state.** It validates input, parses/snapshots, verifies spans, scores, orders gaps, persists sessions, and materializes approved revisions. | A remote service adds authenticated subject/tenant ownership and OAuth resource-server behavior, not model credentials. |
| Host-LLM ownership | **Host owns model selection/execution, credentials, peer-server composition, user mediation, and data-egress decisions.** Dashboard BYOK remains the documented adapter exception. | MRTR may simplify calls but must converge on the same prepare/apply service operations. |
| Confluence | **Atlassian MCP peer plus source-neutral snapshot contract.** No Confluence credentials or API client in Forge core; no automatic write-back. | Benchmark a separately packaged direct adapter only for Data Center, unattended ingestion, or missing revision/structure metadata. |
| MCP sampling | **Freeze legacy path; make prepare/submit normative; benchmark optional MRTR.** | Remove legacy sampling after target hosts support the modern path and migration telemetry shows no required users. |
| Labelled data | **Not a runtime dependency.** Human labels gate calibration, accuracy, priority, and organization-validity claims only. | Never turn label scarcity into a reason to disable operation or invent proxy validity. |

## Conclusion

Forge's defensible advantage is not its current list of fields or its SQLite state machine in isolation. It is the chain from immutable source identity to exact evidence, bounded semantic judgment, deterministic score authority, and auditable human decisions. The current architecture weakens that chain at its most visible point by turning a rubric into a bank of preset questions and by collapsing richer evidence before evaluation. Correcting those two representations will improve question relevance, contradiction handling, and context efficiency without surrendering deterministic scoring.

The ordering matters. Fix schema/provenance/session defects first, improve canonical source units second, introduce criterion evaluations third, and only then generate gap-specific questions and optimize retrieval. That sequence makes Docling, lexical retrieval, MRTR, Promptfoo, and any future orchestration framework replaceable experiments rather than new authorities. It also keeps the product operational today without labelled data while making every future claim of quality depend on the independent evidence it actually requires.
