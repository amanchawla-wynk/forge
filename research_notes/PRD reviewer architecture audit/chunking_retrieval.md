# Chunking and Retrieval for a PRD Reviewer

Research cut-off and source access date: **2026-09-25**. This audit evaluates
Docling `HierarchicalChunker` and `HybridChunker`, Chonkie, PostgreSQL full-text
search with pgvector, LlamaIndex `AutoMergingRetriever` and recursive retrieval,
and Haystack against Forge's evidence and scoring constraints.

## What hierarchy, provenance, and content relationships survive?

### Takeaway

Docling is the only candidate in this set whose primary representation is a
typed document tree rather than a hierarchy manufactured from fixed-size text
windows. It is the strongest ingestion candidate, but Forge must retain its own
stable block identities and exact offsets because Docling's token-level splits
preserve item metadata without supplying a unique source-character span for
each resulting segment. Chonkie is useful text-splitting infrastructure, while
LlamaIndex and Haystack hierarchies are retrieval structures unless Forge
constructs them from authorial sections itself.

### Cited Findings

#### Forge baseline and non-negotiable behavior

- Forge currently normalizes PDF pages, DOCX paragraphs and table rows, and text
  files into `SourceBlock`s. A block carries an id, optional page and section,
  provenance, optional parent id, and optional start/end offsets. PDF parsing is
  page-level; DOCX parsing tracks the active heading and emits each table row as
  a separate pipe-delimited block. Images are separate `VisualAsset`s rather
  than part of the text corpus. — [Forge ingestion models](https://github.com/amanchawla-wynk/forge/blob/9f03fb206a98204bdbdc97ee54d7739647aed128/src/forge/ingest/models.py), [Forge document ingestion](https://github.com/amanchawla-wynk/forge/blob/9f03fb206a98204bdbdc97ee54d7739647aed128/src/forge/ingest/document.py) (accessed 2026-09-25)
- Forge greedily packs complete source blocks into exhaustive batches capped at
  120,000 rendered characters. Only an individually oversized block is split;
  that split uses semchunk with 256-character overlap and records the original
  block as `parent_id` plus source offsets. — [Forge batching](https://github.com/amanchawla-wynk/forge/blob/9f03fb206a98204bdbdc97ee54d7739647aed128/src/forge/ingest/batching.py) (accessed 2026-09-25)
- A submitted extraction run must include every prepared batch. Forge rejects
  missing or unknown fragments, verifies every quote against its batch, records
  source block and quote-local offsets, and keeps supplemental evidence bound to
  its named criterion. This is the existing recall safeguard that retrieval must
  not replace. — [Forge extraction verification](https://github.com/amanchawla-wynk/forge/blob/9f03fb206a98204bdbdc97ee54d7739647aed128/src/forge/extract/batch.py) (accessed 2026-09-25)
- semchunk is a text splitter, not a document model. It recursively chooses
  structural delimiters, can return exact `(start, end)` offsets such that each
  chunk equals the corresponding source slice, and supports overlap. Its base
  mode has no model or provider dependency. — [semchunk README](https://github.com/isaacus-dev/semchunk) (accessed 2026-09-25)

#### Docling `HierarchicalChunker`

- `DoclingDocument` has typed text, table, picture, and key-value items; body and
  furniture trees; groups; parent/child JSON pointers; ordered children for
  reading order; available bounding boxes; and provenance. This is genuine
  parsed-document structure, including a distinction between body content and
  headers/footers. — [Docling document model](https://docling-project.github.io/docling/concepts/docling_document/) (accessed 2026-09-25)
- `HierarchicalChunker` traverses that structure and produces chunks from
  detected document elements. It attaches the heading path and retains the
  contributing typed `DocItem` objects and document origin in `DocMeta`.
  Serialized captions are included with their associated item; tables are
  serialized as structured content rather than first being flattened into an
  undifferentiated whole-document string. — [Docling chunking concepts](https://docling-project.github.io/docling/concepts/chunking/), [HierarchicalChunker source](https://github.com/docling-project/docling-core/blob/main/docling_core/transforms/chunker/hierarchical_chunker.py), [DocMeta source](https://github.com/docling-project/docling-core/blob/main/docling_core/transforms/chunker/doc_chunk.py) (accessed 2026-09-25)
- The default chunking serializer uses picture placeholders with an empty
  placeholder string. The underlying `DoclingDocument` retains `PictureItem`s,
  hierarchy, annotations, and provenance, but ordinary chunk text must not be
  treated as preserving image bytes or inferred diagram semantics. — [HierarchicalChunker source](https://github.com/docling-project/docling-core/blob/main/docling_core/transforms/chunker/hierarchical_chunker.py), [Docling document model](https://docling-project.github.io/docling/concepts/docling_document/) (accessed 2026-09-25)
- Docling's `TreeChunkExpander` can expand a split chunk back to its containing
  document item, including a complete table. This supports a representation in
  which a compact retrieval unit points back to an intact source semantic unit.
  — [Advanced chunking and serialization example](https://docling-project.github.io/docling/_generated/examples/advanced_chunking_and_serialization/) (accessed 2026-09-25)

#### Docling `HybridChunker`

- `HybridChunker` starts with hierarchical chunks, splits only chunks that are
  too large for the selected tokenizer, and optionally merges adjacent small
  chunks only when headings and captions match. Large tables are split on lines,
  with table headers repeated by default. Non-table overflow splitting delegates
  to semchunk. — [Docling chunking concepts](https://docling-project.github.io/docling/concepts/chunking/), [HybridChunker source](https://github.com/docling-project/docling-core/blob/main/docling_core/transforms/chunker/hybrid_chunker.py) (accessed 2026-09-25)
- When `HybridChunker` splits one oversized `DocChunk` using semchunk, each
  segment receives the same `DocMeta`; the source records the contributing
  `DocItem`s but does not emit a distinct source-character range for each split
  segment. When peers merge, their `doc_items` are combined. Forge therefore
  still needs deterministic offset relocation and stable child ids if it adopts
  this path. — [HybridChunker source](https://github.com/docling-project/docling-core/blob/main/docling_core/transforms/chunker/hybrid_chunker.py) (accessed 2026-09-25)

#### Chonkie

- Chonkie's `RecursiveChunker` recursively applies configured delimiter levels,
  but its public output is a flat list of chunks with text, token count, and
  exact start/end indexes. The recursive splitting tree is not the authorial
  section hierarchy and is not retained in the shown chunk contract. Python and
  JavaScript implementations are documented. — [Chonkie RecursiveChunker](https://docs.chonkie.ai/oss/chunkers/recursive-chunker) (accessed 2026-09-25)
- `TableChunker` accepts Markdown or HTML tables, splits by rows or tokens, and
  repeats/preserves headers in every chunk. It operates on already serialized
  table text; it does not itself preserve the source parser's picture, caption,
  bounding-box, or section relationships. — [Chonkie TableChunker](https://docs.chonkie.ai/oss/chunkers/table-chunker) (accessed 2026-09-25)
- Chonkie offers token, sentence, recursive, semantic, late, code, neural, LLM,
  and table chunkers plus embedding and vector-store integrations. That breadth
  is useful for a generic RAG ingestion product, but most of it is outside
  Forge's requirement for source-semantic blocks as the primary representation.
  — [Chonkie repository](https://github.com/chonkie-inc/chonkie) (accessed 2026-09-25)

#### LlamaIndex hierarchical, auto-merging, and recursive retrieval

- LlamaIndex `HierarchicalNodeParser` defaults to overlapping sentence splits at
  2,048, 512, and 128 tokens. It returns all hierarchy levels in one flat list
  and records parent/child relationships; this is a coarse-to-fine window
  hierarchy, not a source section tree. Custom node parsers can be supplied, but
  the default directly conflicts with "no arbitrary fixed chunks as primary
  representation." — [HierarchicalNodeParser source at v0.14.6](https://github.com/run-llama/llama_index/blob/v0.14.6/llama-index-core/llama_index/core/node_parser/relational/hierarchical.py), [Auto-merging example](https://docs.llamaindex.ai/en/stable/examples/retrievers/auto_merging_retriever/) (accessed 2026-09-25)
- `AutoMergingRetriever` first retrieves leaf nodes through a vector retriever.
  It fills a missing intervening neighbour when retrieved nodes bracket that
  neighbour, then replaces retrieved children with their parent when the number
  of retrieved children divided by all parent children is greater than the
  threshold (default `0.5`), repeating recursively. Parent nodes must be present
  in the docstore. — [AutoMergingRetriever source at v0.14.6](https://github.com/run-llama/llama_index/blob/v0.14.6/llama-index-core/llama_index/core/retrievers/auto_merging_retriever.py) (accessed 2026-09-25)
- Because auto-merging operates only on the leaf set returned by its base vector
  retriever, it expands context around hits but does not recover unrelated
  relevant leaves that initial retrieval missed. The official example indexes
  only leaf nodes in the vector index and loads all hierarchy levels into a
  docstore. — [LlamaIndex auto-merging example](https://docs.llamaindex.ai/en/stable/examples/retrievers/auto_merging_retriever/) (accessed 2026-09-25)
- `RecursiveRetriever` is a different abstraction: an `IndexNode` can point to
  another retriever or query engine, and retrieval recursively invokes the
  linked object. The official table example manually extracts tables, stores
  summary nodes in a vector index, and links each summary to a Pandas query
  engine. Table relationships therefore survive only if the application creates
  those links; they are not inferred from ordinary text nodes. — [RecursiveRetriever source at v0.14.6](https://github.com/run-llama/llama_index/blob/v0.14.6/llama-index-core/llama_index/core/retrievers/recursive_retriever.py), [recursive table retrieval example](https://docs.llamaindex.ai/en/stable/examples/query_engine/pdf_tables/recursive_retriever/) (accessed 2026-09-25)
- The official recursive-table example warns that its Pandas query engine gives
  the LLM access to Python `eval` and is not recommended for production without
  heavy sandboxing or virtual machines. — [recursive table retrieval example](https://docs.llamaindex.ai/en/stable/examples/query_engine/pdf_tables/recursive_retriever/) (accessed 2026-09-25)

#### Haystack

- Haystack's `HierarchicalDocumentSplitter` constructs a tree by repeatedly
  splitting into configured word, sentence, page, or passage block sizes. It
  records level, block size, parent id, child ids, source id, page number, split
  id, and split start. Like LlamaIndex's default parser, this is a hierarchy of
  size-based retrieval windows rather than author-defined sections. — [Haystack HierarchicalDocumentSplitter source](https://github.com/deepset-ai/haystack/blob/main/haystack/components/preprocessors/hierarchical_document_splitter.py) (accessed 2026-09-25)
- Haystack `AutoMergingRetriever` accepts matched leaves from an upstream
  retriever and recursively substitutes a parent when the fraction of matched
  children is greater than a threshold. It requires parent documents in a
  supported document store; current stable documentation lists AstraDB,
  Elasticsearch, OpenSearch, Pgvector, and Qdrant. — [Haystack 3.2 AutoMergingRetriever documentation](https://docs.haystack.deepset.ai/docs/automergingretriever), [source](https://github.com/deepset-ai/haystack/blob/main/haystack/components/retrievers/auto_merging_retriever.py) (accessed 2026-09-25)
- Haystack can combine keyword and embedding retrievers using
  `DocumentJoiner`, including reciprocal-rank fusion and distribution-based
  rank fusion, and its metadata-filter syntax supports nested comparison and
  Boolean conditions subject to each store's capabilities. — [DocumentJoiner](https://docs.haystack.deepset.ai/docs/documentjoiner), [metadata filtering](https://docs.haystack.deepset.ai/docs/metadata-filtering) (accessed 2026-09-25)

### Inferences

- Forge should treat a **source semantic unit** and a **retrieval projection**
  as separate records. A section, paragraph, list, table, table row, picture,
  caption, or header/footer remains the canonical evidence object; token-limited
  children are projections with parent id and exact offsets. This follows
  Docling's typed tree while preserving Forge's stronger quote-location contract.
- Docling's hierarchy directly addresses Forge's measured PDF line-fragmentation
  problem: statements can remain attached to one typed item and heading path
  instead of being broken merely because PDF text contains line breaks. This is
  a hypothesis to benchmark, not evidence that Docling will parse every internal
  PDF correctly.
- Neither auto-merging implementation is a recall mechanism. It should be used
  after candidates are found, to add parent and neighbour context, never to
  decide which blocks may contain scoreable evidence.
- For tables, the best Forge representation is dual: preserve an intact typed
  table and caption as the parent, plus row/cell-addressable children for exact
  evidence and structured conflict checks. Header repetition is a retrieval
  serialization feature, not a substitute for the canonical table relationship.
- Pictures and diagrams should remain first-class sibling assets linked to
  source items, captions, section path, page, and bounding box. Their text or
  visual interpretation should enter scoring only through Forge's existing
  separately provenanced evidence rules.

### Gaps

- Official interfaces establish what metadata can survive, but not whether
  Docling recovers correct headings, reading order, tables, captions, and picture
  links on Forge's representative PRDs. A fixture-level comparison is required.
- Docling's current split chunks do not expose the exact child source offsets
  Forge needs. The benchmark must test deterministic relocation, especially when
  the same text appears more than once in a table, header, or repeated template.
- No source reviewed provides an independent benchmark for PRD evidence recall
  or cross-section contradiction recall. Vendor RAG benchmarks are not a proxy
  for Forge's evaluation units.

## What are the runtime, deployment, and storage trade-offs, and is direct PostgreSQL simpler?

### Takeaway

Direct PostgreSQL full-text search plus pgvector is simpler than adopting
LlamaIndex or Haystack if Forge eventually needs persistent hybrid retrieval:
one schema can store canonical blocks, hierarchy, order, metadata, lexical
indexes, and vectors, while small SQL/Python functions perform rank fusion and
parent/neighbour expansion. It is not simpler than Forge's current in-process,
single-document exhaustive path, so PostgreSQL should be deferred until there is
a measured persistence, cross-document, concurrency, or latency requirement.

### Cited Findings

#### Language, license, self-hosting, and provider dependencies

| Component | Runtime and language | License | Deployment/provider boundary |
|---|---|---|---|
| Docling | Python 3.10-3.14 is declared on current `main`; the standard local parsing stack can include PyTorch, Docling IBM models, OCR engines, and format-specific packages. A modular `docling-slim` package and extras separate lighter parsing capabilities from local models. | MIT | Runs locally on macOS, Linux, and Windows; CPU and accelerator distributions are supported. Model/OCR assets and their transitive packages are operational dependencies, but a hosted LLM is not required for core parsing. [Manifest](https://github.com/docling-project/docling/blob/main/pyproject.toml), [installation](https://docling-project.github.io/docling/getting_started/installation/), [license](https://github.com/docling-project/docling/blob/main/LICENSE) (accessed 2026-09-25) |
| Chonkie 1.7.0 | Python >=3.10; `RecursiveChunker` and `TableChunker` also have JavaScript APIs through `@chonkiejs/core`. | MIT | Base recursive/table chunking is local. Embedding, semantic/neural, vector-store, API-server, and provider clients are optional extras. It also offers a self-hosted FastAPI/Docker API. [Manifest](https://github.com/chonkie-inc/chonkie/blob/main/pyproject.toml), [repository](https://github.com/chonkie-inc/chonkie), [license](https://github.com/chonkie-inc/chonkie/blob/main/LICENSE) (accessed 2026-09-25) |
| semchunk 4.1.1 | Python >=3.10; base dependencies are small and it accepts a tokenizer or token-counting callable. | MIT | Base splitting is local and provider-free. Its optional AI-powered mode requires the Isaacus SDK and API key, which Forge does not need and should not adopt. [Manifest](https://github.com/isaacus-dev/semchunk/blob/main/pyproject.toml), [README](https://github.com/isaacus-dev/semchunk) (accessed 2026-09-25) |
| PostgreSQL 18 + pgvector 0.8.6 | PostgreSQL server plus a C extension; usable from any language with a PostgreSQL client. pgvector supports PostgreSQL 13+ and publishes packages/images for common platforms. | PostgreSQL License for both PostgreSQL and pgvector | Fully self-hostable or available from hosted PostgreSQL providers. pgvector stores and searches vectors but does not create embeddings; Forge must supply a local or external embedding function if semantic search is enabled. [pgvector README](https://github.com/pgvector/pgvector/blob/master/README.md), [pgvector license](https://github.com/pgvector/pgvector/blob/master/LICENSE), [PostgreSQL license](https://www.postgresql.org/about/licence/) (accessed 2026-09-25) |
| LlamaIndex 0.14.6 components assessed | Python >=3.9. `llama-index-core` brings SQLAlchemy, HTTP clients, NLTK, NumPy, tiktoken, NetworkX, Pillow, workflow, and storage dependencies. | MIT | `llama-index-core` itself does not declare an OpenAI SDK dependency, so retrieval can be self-hosted with explicit local components. The convenience `llama-index` metapackage directly depends on OpenAI LLM/embedding integrations and a managed LlamaCloud index integration, so it is incompatible with Forge's core dependency boundary. [Core manifest](https://github.com/run-llama/llama_index/blob/v0.14.6/llama-index-core/pyproject.toml), [metapackage manifest](https://github.com/run-llama/llama_index/blob/v0.14.6/pyproject.toml), [license](https://github.com/run-llama/llama_index/blob/v0.14.6/LICENSE) (accessed 2026-09-25) |
| Haystack stable docs 3.2 (`main` is 3.3.0-rc0) | Python >=3.10. Current `haystack-ai` includes pipeline, schema, HTTP, NumPy, NetworkX, telemetry, and other framework dependencies. | Apache-2.0 | Pipelines can use local models and self-hosted stores, but the base package currently declares `openai>=1.99.2` rather than isolating it to an optional integration. Pgvector support is a separate `pgvector-haystack` package. [Manifest](https://github.com/deepset-ai/haystack/blob/main/pyproject.toml), [version](https://github.com/deepset-ai/haystack/blob/main/VERSION.txt), [pgvector integration](https://docs.haystack.deepset.ai/docs/pgvectordocumentstore), [license](https://github.com/deepset-ai/haystack/blob/main/LICENSE) (accessed 2026-09-25) |

#### What PostgreSQL and pgvector provide directly

- PostgreSQL full-text search converts text to positional, normalized lexemes in
  `tsvector`, supports language-specific configurations, weights lexemes from
  fields such as title versus body, offers forgiving `websearch_to_tsquery`, and
  ranks with term frequency or cover density/proximity. GIN is the preferred
  full-text index type. — [PostgreSQL text-search controls](https://www.postgresql.org/docs/current/textsearch-controls.html), [preferred text-search indexes](https://www.postgresql.org/docs/current/textsearch-indexes.html) (accessed 2026-09-25)
- pgvector supports exact nearest-neighbour search and approximate HNSW and
  IVFFlat indexes. Exact search has perfect recall; approximate indexes trade
  recall for speed. With approximate indexes, metadata filtering is applied
  after the vector index scan, so filtered queries can return too few rows;
  iterative scans can search farther but still stop at configured limits.
  — [pgvector README: indexing, filtering, and iterative scans](https://github.com/pgvector/pgvector/blob/master/README.md) (accessed 2026-09-25)
- pgvector explicitly documents hybrid search with PostgreSQL full-text search
  and recommends reciprocal-rank fusion or a cross-encoder to combine rankings.
  Its official Python example implements full-text and semantic candidate CTEs
  followed by reciprocal-rank fusion in one SQL query. — [pgvector README: hybrid search](https://github.com/pgvector/pgvector/blob/master/README.md), [official RRF example](https://github.com/pgvector/pgvector-python/blob/master/examples/hybrid_search/rrf.py) (accessed 2026-09-25)
- Haystack's Pgvector store confirms that the same backend can expose both
  keyword and embedding retrievers plus metadata filtering, but those features
  are wrappers over PostgreSQL/pgvector capabilities rather than a new storage
  primitive. — [Haystack PgvectorDocumentStore](https://docs.haystack.deepset.ai/docs/pgvectordocumentstore) (accessed 2026-09-25)

#### Minimal direct schema for Forge

The following is a proposed design, not an upstream fact:

```sql
document(
  id, source_sha256, source_type, parser_version, created_at
)

source_node(
  id, document_id, parent_id, ordinal, node_type,
  section_path, page, bbox, source_start, source_end,
  content, provenance_json, metadata_json,
  search_vector tsvector, embedding vector(N)
)

node_relation(
  document_id, from_id, relation_type, to_id
  -- parent, previous, next, caption_of, picture_of, table_row_of
)

criterion_query(
  rubric_version, criterion_id, query_kind, query_text
)
```

The query path would be:

1. Apply hard metadata filters only for document identity, provenance class, or
   an explicitly requested node type; do not infer section exclusions.
2. Retrieve lexical candidates using weighted PostgreSQL FTS, preserving exact
   identifier and phrase queries for machine fields, event names, and rules.
3. Optionally retrieve semantic candidates using **exact** pgvector search at
   PRD scale; use ANN only after scale measurements justify it.
4. Fuse ranks with reciprocal-rank fusion rather than attempting to normalize
   incomparable FTS and vector scores.
5. Expand each hit by its canonical parent, previous/next siblings, caption,
   and table parent/rows under a deterministic context budget.
6. Keep the selected nodes as prompt-packing candidates only. Maintain a
   coverage ledger over every canonical source node and run an exhaustive
   fallback pass for all nodes not processed for the scoring extraction.

### Inferences

- **Yes, PostgreSQL FTS + pgvector can implement the stated retrieval
  requirement more simply than either framework.** Parent and neighbour context
  are ordinary ids/ordinals and joins; metadata is typed columns/JSONB; keyword
  and vector ranks are two CTEs; RRF is a short SQL expression. Forge would keep
  its domain model rather than translating it into a framework's `Node` or
  `Document` lifecycle.
- **No, PostgreSQL is not the simplest next step for current Forge.** One PRD's
  nodes fit comfortably in memory, Forge already persists review workflow in
  SQLite, and scoring remains exhaustive. An in-process lexical candidate index
  plus deterministic parent/neighbour expansion should be the first retrieval
  prototype. PostgreSQL becomes justified for persistent corpora, concurrent
  users, cross-document search, or measured query latency that the local path
  cannot meet.
- Embeddings introduce a new inference lifecycle: model selection, dimensions,
  download or provider access, versioned re-embedding, resource use, and
  cross-language quality. PostgreSQL removes the need for a separate vector
  database but does not remove that lifecycle.
- PostgreSQL FTS is likely more important than embeddings for PRD review's exact
  identifiers, requirement language, named states, dates, and table keys.
  Embeddings should be an additive recall channel, not the sole candidate source.
- At current scale, exact vector search avoids ANN's recall trade-off. Even at
  larger scale, an approximate result set cannot be the eligibility boundary for
  scored evidence; iterative scans improve retrieval but do not prove coverage.

### Gaps

- No representative corpus size, concurrent-user target, or latency budget has
  been supplied, so a PostgreSQL adoption threshold cannot yet be quantified.
- No embedding model has been selected or evaluated for PRD terminology,
  multilingual documents, tables, short identifiers, or Forge's no-provider-key
  MCP path.
- PostgreSQL FTS configurations vary by language. Mixed-language PRDs and
  product-specific acronyms need benchmark cases before stemming and stop-word
  behavior can be trusted.
- The license summary is technical research, not legal advice; transitive model,
  tokenizer, OCR, and integration licenses require review before distribution.

## What should Forge adopt, benchmark, borrow, or reject?

### Takeaway

Adopt a benchmark-gated Docling parser adapter and preserve semchunk only as an
overflow splitter. Borrow small retrieval algorithms and metadata conventions,
not LlamaIndex or Haystack as production dependencies. Benchmark direct
lexical/hybrid retrieval as a context optimizer with an explicit exhaustive
coverage backstop; reject any design where top-k retrieval determines evidence
eligibility.

### Cited Findings

#### Decision matrix

| Candidate | Decision | Reason |
|---|---|---|
| Docling `DoclingDocument` + `HierarchicalChunker` | **Adopt behind an adapter if benchmarks pass** | It preserves typed items, hierarchy, reading order, provenance, headings, captions, tables, and pictures in the source model, which directly targets Forge's current structural loss. It is MIT and local-first. [Document model](https://docling-project.github.io/docling/concepts/docling_document/), [chunking](https://docling-project.github.io/docling/concepts/chunking/), [license](https://github.com/docling-project/docling/blob/main/LICENSE) (accessed 2026-09-25) |
| Docling `HybridChunker` | **Benchmark as overflow/context projection, not canonical representation** | It retains Docling metadata, uses table-aware splitting with repeated headers, and delegates ordinary overflow to semchunk, but split segments lack Forge-grade exact source spans. [Hybrid source](https://github.com/docling-project/docling-core/blob/main/docling_core/transforms/chunker/hybrid_chunker.py) (accessed 2026-09-25) |
| Existing semchunk integration | **Keep** | It is already narrowly scoped to oversized blocks and returns exact offsets; this is compatible with exhaustive processing and avoids arbitrary fixed chunks as the primary representation. [Forge batching](https://github.com/amanchawla-wynk/forge/blob/9f03fb206a98204bdbdc97ee54d7739647aed128/src/forge/ingest/batching.py), [semchunk README](https://github.com/isaacus-dev/semchunk) (accessed 2026-09-25) |
| Chonkie | **Do not adopt as primary; borrow/test isolated table and offset ideas only** | Its useful output contracts are flat text chunks with offsets and header-preserving table chunks. Forge already has semchunk offsets, while Docling offers the richer source hierarchy Chonkie lacks at the chunk API boundary. [RecursiveChunker](https://docs.chonkie.ai/oss/chunkers/recursive-chunker), [TableChunker](https://docs.chonkie.ai/oss/chunkers/table-chunker) (accessed 2026-09-25) |
| Direct PostgreSQL FTS | **Benchmark first; adopt before vectors if persistent retrieval is needed** | It supplies weighted lexical search, phrase/proximity behavior, metadata joins, and a preferred GIN index without an embedding model. [PostgreSQL text search](https://www.postgresql.org/docs/current/textsearch-controls.html), [indexes](https://www.postgresql.org/docs/current/textsearch-indexes.html) (accessed 2026-09-25) |
| pgvector | **Benchmark as an additive channel; defer production adoption until it improves recall/packing** | It supports exact search and SQL-native hybrid fusion, but embeddings add a model lifecycle and ANN can reduce recall. [pgvector README](https://github.com/pgvector/pgvector/blob/master/README.md) (accessed 2026-09-25) |
| LlamaIndex `AutoMergingRetriever` | **Borrow the algorithm; reject the framework dependency now** | The useful behavior is small: fill bracketed neighbours and replace sufficiently represented siblings with a parent. Its default hierarchy is fixed-size, initial vector retrieval remains the recall bottleneck, and core brings a broad dependency set. [Auto-merging source](https://github.com/run-llama/llama_index/blob/v0.14.6/llama-index-core/llama_index/core/retrievers/auto_merging_retriever.py), [core manifest](https://github.com/run-llama/llama_index/blob/v0.14.6/llama-index-core/pyproject.toml) (accessed 2026-09-25) |
| LlamaIndex `RecursiveRetriever` | **Reject for scoring; reconsider only for heterogeneous advisory tools** | It is valuable when a retrieved node must dispatch to another retriever or query engine, such as a table-specific engine. Forge's scoring needs exact source evidence, not generated table answers, and the official Pandas path carries an `eval` warning. [RecursiveRetriever source](https://github.com/run-llama/llama_index/blob/v0.14.6/llama-index-core/llama_index/core/retrievers/recursive_retriever.py), [table example](https://docs.llamaindex.ai/en/stable/examples/query_engine/pdf_tables/recursive_retriever/) (accessed 2026-09-25) |
| Haystack | **Borrow pipeline patterns; reject as a Forge core dependency now** | It offers strong ready-made metadata filters, hybrid joiners, retrievers, async pipelines, and document-store integrations. Forge needs only a small subset, and the base package currently installs the OpenAI SDK, violating Forge's core dependency boundary. [DocumentJoiner](https://docs.haystack.deepset.ai/docs/documentjoiner), [metadata filters](https://docs.haystack.deepset.ai/docs/metadata-filtering), [manifest](https://github.com/deepset-ai/haystack/blob/main/pyproject.toml) (accessed 2026-09-25) |
| Retrieval-gated scoring | **Reject** | pgvector documents that approximate indexes trade recall for speed, and both auto-merging systems operate only on leaves returned upstream. None can establish exhaustive evidence eligibility. [pgvector README](https://github.com/pgvector/pgvector/blob/master/README.md), [LlamaIndex source](https://github.com/run-llama/llama_index/blob/v0.14.6/llama-index-core/llama_index/core/retrievers/auto_merging_retriever.py), [Haystack source](https://github.com/deepset-ai/haystack/blob/main/haystack/components/retrievers/auto_merging_retriever.py) (accessed 2026-09-25) |

#### When framework cost would become justified

- **LlamaIndex becomes defensible** when Forge needs a graph of heterogeneous
  retrieval/query objects, not merely source parents and neighbours: for example,
  independently secured deterministic SQL tools for structured tables, several
  vector stores, retriever routing, and response synthesis already standardized
  on LlamaIndex. `RecursiveRetriever` is designed for exactly that linked-object
  dispatch. — [RecursiveRetriever source](https://github.com/run-llama/llama_index/blob/v0.14.6/llama-index-core/llama_index/core/retrievers/recursive_retriever.py) (accessed 2026-09-25)
- **LlamaIndex AutoMerging alone does not justify adoption.** The implementation
  is a small parent/child ratio loop plus neighbour fill over an existing
  docstore, so Forge can implement the domain-specific equivalent without taking
  the framework's node, storage, callback, workflow, and dependency surface.
  — [AutoMergingRetriever source](https://github.com/run-llama/llama_index/blob/v0.14.6/llama-index-core/llama_index/core/retrievers/auto_merging_retriever.py) (accessed 2026-09-25)
- **Haystack becomes defensible** when Forge needs a configurable production RAG
  platform across several backends and teams: serializable component pipelines,
  many converters/retrievers/embedders, metadata-routing conventions, async
  execution, rank fusion, and interchangeable document stores. Its current
  catalog and pipeline components cover those needs. — [Haystack component documentation](https://docs.haystack.deepset.ai/docs/intro), [DocumentJoiner](https://docs.haystack.deepset.ai/docs/documentjoiner), [AutoMergingRetriever](https://docs.haystack.deepset.ai/docs/automergingretriever) (accessed 2026-09-25)
- **Haystack does not justify adoption for one local PRD and one PostgreSQL
  backend.** Its Pgvector integration exposes keyword and embedding retrievers,
  but direct PostgreSQL already supplies both search primitives, and parent
  expansion is straightforward over Forge-owned ids. — [Haystack PgvectorDocumentStore](https://docs.haystack.deepset.ai/docs/pgvectordocumentstore), [pgvector hybrid search](https://github.com/pgvector/pgvector/blob/master/README.md) (accessed 2026-09-25)

#### Required benchmark before changing architecture

Use representative PDF and DOCX PRDs, including the known multi-line PDF,
tables, repeated headers/footers, pictures with captions, duplicate text,
cross-section conflicts, and documents above 120,000 characters.

Benchmark these ingestion variants:

1. Current PyMuPDF/python-docx normalization plus semchunk overflow.
2. Docling conversion mapped directly from typed source items, without chunking.
3. Docling `HierarchicalChunker` mapped to Forge canonical blocks.
4. Docling hierarchy plus `HybridChunker` only for oversized-item projections.
5. Chonkie `TableChunker` only as a table-overflow ablation, not as the document
   representation.

Measure:

- canonical source-node coverage and reading-order agreement;
- heading/section path, page, bounding-box, table/caption, picture/caption, and
  parent/child relationship preservation;
- exact quote relocation success, including duplicate and whitespace-normalized
  quotes;
- table row/header integrity and the existing structured-conflict detector's
  recall;
- multi-line claim reconstruction and deep-review candidate/finding recall;
- extraction tokens, wall time, peak memory, model downloads, cold-start time,
  and install size;
- deterministic repeatability across runs and supported platforms.

Benchmark these retrieval variants over the same canonical blocks:

1. Current exhaustive batching.
2. Exhaustive batching reordered by rubric criterion and section, with no search.
3. PostgreSQL FTS or an equivalent in-process lexical baseline.
4. Exact-vector retrieval alone.
5. FTS + exact-vector RRF.
6. Hybrid retrieval plus deterministic parent and immediate-neighbour expansion.
7. A small Forge-owned auto-merge rule over authorial sections.
8. ANN only as a later scale test, always paired with the exhaustive safeguard.

For each rubric field and each labelled deep-review defect, record retrieval
recall at candidate budget, source-block coverage, evidence quote survival,
cross-section pair coverage, prompt characters/tokens, latency, and false
candidate volume. The release condition must be **no loss of scoreable evidence
eligibility**: every canonical block is either processed in the optimized pass or
sent through an exhaustive fallback batch. Retrieval quality may change order
and context, never eligibility.

### Inferences

- The highest-value near-term work is a Docling adapter spike against the known
  PDF fragmentation failure, not a vector database or RAG framework. Better
  source units improve exhaustive extraction and every later retrieval method.
- Rubric criteria should be query/evaluation units, not nodes in the source
  hierarchy. A criterion may issue several lexical and semantic queries, but
  cited evidence must resolve back to canonical source nodes and remain eligible
  regardless of retrieval rank.
- Forge should implement two explicit ledgers: a canonical **source coverage
  ledger** proving every block was processed for scoring, and a separate
  **retrieval trace** recording query, channel, rank, expansion reason, and final
  prompt placement. This makes token optimization auditable without confusing
  retrieval score with evidence credit.
- Parent and neighbour expansion should be deterministic and budgeted by source
  relationships, not embedding similarity. Tables should expand to caption,
  header, and relevant rows; ordinary text should expand to section parent and
  adjacent siblings; pictures should expand to caption and containing section.
- The appropriate adoption sequence is: **Docling parser benchmark -> canonical
  hierarchy/offset model -> in-process lexical retrieval benchmark -> optional
  direct PostgreSQL FTS -> optional exact pgvector channel -> only then reassess
  framework need**.

### Gaps

- Forge still needs blinded human labels for deep-review defects and scoreable
  evidence spans. Without them, retrieval comparisons can measure mechanical
  source coverage and known proxy cases but not validated review quality.
- The benchmark needs a declared prompt/token budget per model and client;
  120,000 characters is a transport heuristic, not a model-independent token
  budget.
- If cross-document retrieval becomes a product requirement, retention,
  tenancy, deletion, encryption, and source-hash migration rules need a separate
  architecture decision before PostgreSQL adoption.
- Haystack was in a fast-moving transition at the cut-off: stable documentation
  identified 3.2 while repository `main` identified 3.3.0-rc0. Any future spike
  should pin an exact released version rather than target `main`. — [Haystack documentation](https://docs.haystack.deepset.ai/docs/intro), [VERSION.txt](https://github.com/deepset-ai/haystack/blob/main/VERSION.txt) (accessed 2026-09-25)
