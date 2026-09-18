# ADR-0007 — Context Database with Embedding-Based Retrieval

| Field        | Value                              |
|--------------|------------------------------------|
| Status       | Proposed                           |
| Date         | 2026-01-17                         |

## Context

swatl currently provides two mechanisms for maintaining translation consistency beyond glossary terms:

1. **Translation Memory (TM)** — an exact-match cache keyed by SHA-256 hash of source text. It saves cost and ensures consistency for identical segments but is blind to semantic similarity.
2. **Context window** — the last N (`n_previous=3`) translated segments are prepended to the prompt. This provides *proximity-based* context (neighboring segments) but cannot retrieve semantically relevant content from earlier in the document.

This approach has three gaps:

- **Non-local semantic relevance**: A segment about "三体" on page 200 may need context from a definition on page 5. The proximity window cannot reach that far.
- **Cross-chapter consistency**: Character names, technical terms, and world-building details established in Chapter 1 may need reinforcement in Chapter 10. Hash-based TM only helps on re-runs; it does not proactively feed relevant context during a first pass.
- **Proofreading blind spots**: The proofreader has no visibility into terminology decisions or stylistic patterns established earlier in the translation.

In professional MT (e.g., Phrase Next-GenMT), retrieval-augmented approaches retrieve fuzzy matches from translation memory and inject them as in-context examples. Academic research (RAGtrans, Tencent 2024) demonstrates that retrieval-augmented MT improves BLEU by 1.6–3.1 and COMET by 1.0–2.7 points over non-retrieved baselines.

## Decision

Add a **Context Database (ContextDB)** submodule that:

1. **Embeds** each translated segment (source + translated pair) into a vector space using a multilingual embedding model.
2. **Stores** embeddings with rich metadata (document, anchor, glossary terms, language) in a persistent vector index.
3. **Retrieves** the K most semantically similar segments at translation time by embedding the current source text and performing nearest-neighbor search.
4. **Injects** retrieved context into the translation prompt alongside the existing proximity window and glossary.

### Model Selection

| Option | Size | Dims | Multilingual | Context | License | VRAM | Best For |
|--------|------|------|--------------|---------|---------|------|----------|
| **nomic-embed-text-v2-moe** | 305M active / 475M total | 768 (→256) | ~100 langs | 512 tokens | Apache-2.0 | ~1.2 GB | **Recommended default** — fast, multilingual, efficient MoE |
| BGE-M3 | ~568M | 1024 | 100+ langs | 8,192 | Apache-2.0 | ~2 GB | Heavy-hitter; dense + lexical + multi-vector |
| **OpenAI text-embedding-3-small** | proprietary | 1536 (→256) | English-focused | 8,191 | proprietary | 0 GB (cloud) | **Fallback cloud option** — zero infra |
| embeddinggemma-300m | 300M | 768 (→128) | 100+ langs | 2,048 | Google ToS | <1 GB | On-device / offline; smaller context |

**Recommended default: `nomic-embed-text-v2-moe`** via `sentence-transformers`. It is:
- Apache-2.0 licensed (commercial-friendly, no vendor lock-in)
- Multilingual with strong zh→en performance
- ~305M active parameters (MoE), loads in ~1.2 GB VRAM or runs on CPU with acceptable latency (~10–30 ms per segment on modern CPU)
- Compact 768-dim output, reducible to 256 via MRL (67% storage savings)
- Compatible with `sentence-transformers` API, which swatl can use directly without an external vector DB server

**Cloud fallback: OpenAI `text-embedding-3-small`** — for users who prefer not to run local models or have no GPU. Costs ~$0.02/1M tokens; a 100k-word EPUB generates ~10k embeddings at ~$0.20 total.

### Vector Store Selection

| Option | Type | Persistence | Filtering | Overhead |
|--------|------|-------------|-----------|----------|
| **FAISS** (IVF/PQ) | Pure index | Manual save/load | Manual metadata | Minimal — no server |
| **Chroma** (persistent) | Embedded DB | SQLite-backed | Built-in metadata | Moderate — Python lib |
| Qdrant | Server / client | On-disk | Rich filters | Heavy — Docker/process |

**Recommended: FAISS as the default index backend**, with optional Chroma integration.

Rationale:
- FAISS has zero external dependencies beyond NumPy — no Docker, no server process.
- For a typical EPUB (5k–50k segments), FAISS `IndexFlatIP` (exact inner-product search) is instantaneous (<1 ms for 10k vectors on CPU).
- FAISS indices save/load as binary files — trivial persistence in `.swatl-state/`.
- Chroma integration is a practical second path for users who want built-in metadata filtering (e.g., "retrieve only from same chapter") without writing custom filter logic.

### Architecture

```
src/swatl/
├── context/                     # NEW submodule
│   ├── __init__.py
│   ├── embedder.py              # Wraps sentence-transformers / OpenAI embedding
│   ├── index.py                 # FAISS index management (add, query, save, load)
│   ├── retriever.py             # High-level retrieve(segments, k, doc_filter)
│   └── store.py                 # Persistence (save/load index + metadata)
```

### Data Model

Each ContextDB entry stores:

```python
@pydantic.dataclasses.dataclass
class ContextEntry:
    segment_id: str          # e.g., "p-0041"
    doc: str                 # e.g., "text/ch01.xhtml"
    anchor: str              # e.g., ".//p[4]"
    source_lang: str         # e.g., "zh"
    source_text: str         # original text
    translated_text: str     # translated text
    embedding: list[float]   # embedding vector (dim=768 or 256)
    glossary_terms: list[str] # matched glossary terms for keyword boost
    stage: str               # "translated" or "proofread"
```

### Retrieval Strategy

When translating segment S:

1. **Embed S's source text** using the configured embedder.
2. **Query the FAISS index** for K (default 5) nearest neighbors by cosine similarity (inner product on normalized vectors).
3. **Apply document filter** — optionally restrict retrieval to the same document (chapter), controlled by a `--context-cross-doc` flag.
4. **Deduplicate** against the existing proximity window (last N segments) to avoid redundancy.
5. **Format retrieved segments** as "source → target" pairs and inject into the prompt under a "Related context from earlier in the document:" section.

Prompt injection format:

```
Related context (semantically similar, from earlier in the document):
[p-0012] 这个概念来自爱因斯坦的相对论。 → This concept comes from Einstein's theory of relativity.
[p-0047] 爱因斯坦提出了这一理论。 → Einstein proposed this theory.

Translate the following segment:
{source_text}
```

### Configuration

New CLI flags:

```
--context-enabled          Enable embedding-based context retrieval (default: false)
--context-k INT            Number of retrieved segments to inject (default: 5)
--context-cross-doc        Allow cross-document retrieval (default: same-document only)
--context-model NAME       Embedding model name (default: nomic-embed-text-v2-moe)
                           Accepts: local model ID or "openai" for text-embedding-3-small
--context-dim INT          Embedding dimension (default: 256 for nomic; 1536 for openai)
```

### Lifecycle

1. **Build phase** (after translation or proofreading completes): all segments with a translation are embedded and added to the index.
2. **Translate phase** (when `--context-enabled`): the index is loaded *before* translation starts. As each segment is translated, it is immediately added to the in-memory index so subsequent segments can retrieve it.
3. **Proofread phase**: the index is loaded; proofread segments can optionally update entries (if proofread version differs).
4. **Persistence**: the index and metadata are saved to `.swatl-state/context_db/` after each batch of N segments or on completion.

### Trade-offs and Risks

| Concern | Mitigation |
|---------|------------|
| **Added latency during translation** | Embedding a single segment takes ~10–30 ms on CPU. For K=5, retrieval is <1 ms. Total overhead per segment: ~35 ms. For 10k segments: ~6 minutes total — acceptable for offline batch translation. |
| **Model download size** | `nomic-embed-text-v2-moe` is ~1.2 GB. First run downloads and caches. Provide a `--context-light` flag that uses a smaller model (e.g., `all-MiniLM-L6-v2` at 90 MB, English-only, for EN→EN context). |
| **Chinese embedding quality** | `nomic-embed-text-v2-moe` was trained on 1.6B pairs across ~100 languages including Chinese. BGE-M3 is a stronger alternative for zh→en if quality is critical. |
| **Context noise** | If retrieved segments are semantically tangential, they add prompt bloat without value. Mitigation: use a minimum similarity threshold (e.g., cosine ≥ 0.35) and cap injected context at 2000 tokens. |
| **State size growth** | 10k segments × 768 dims × 4 bytes (float32) = ~30 MB for FAISS vectors + metadata JSON. Manageable; add a prune command to rebuild index from only proofread segments. |

### Alternative Designs Considered

| Alternative | Why Not Chosen |
|-------------|----------------|
| **Enhance TM with fuzzy matching** (Levenshtein/RB2 on source text) | Already partially done via back-translation similarity. Doesn't capture cross-topic semantic links. Embeddings generalize better across paraphrase and terminology variation. |
| **Full RAG server (Qdrant + embedding API)** | Adds Docker dependency and operational complexity for an offline-first EPUB tool. FAISS + sentence-transformers achieves 95% of the value with zero external services. |
| **Prompt the LLM to generate its own context** (no retrieval) | Wastes tokens and produces hallucinated context. Retrieval is deterministic and verifiable. |
| **Document-level embedding** (embed whole chapters, not segments) | Too coarse for segment-level translation. Segments need segment-level embeddings for precise retrieval. |

### Implementation Plan

| Step | Task | Module | Effort |
|------|------|--------|--------|
| 7.1 | `context/embedder.py` — wrapper for sentence-transformers + OpenAI fallback | New | 1–2 days |
| 7.2 | `context/index.py` — FAISS index wrapper (add/query/save/load) | New | 1 day |
| 7.3 | `context/retriever.py` — retrieve + deduplicate + format | New | 0.5–1 day |
| 7.4 | Integrate retriever into `prompt_builder.py` — inject retrieved context | Existing | 0.5 day |
| 7.5 | Integrate context loading into `translator.py` — warm index before translate | Existing | 0.5 day |
| 7.6 | CLI flags + TOML config support | Existing (`cli.py`, `config.py`) | 0.5 day |
| 7.7 | Tests (embedder unit, index CRUD, retrieval accuracy) | New (`tests/test_context.py`) | 1–2 days |
| 7.8 | Documentation update | `docs/` | 0.5 day |

**Total estimated effort: 5–8 days**

### References

- **RAGtrans** (Tencent, 2024) — Retrieval-augmented MT with unstructured knowledge, improving BLEU by 1.6–3.1. https://arxiv.org/abs/2412.04342
- **MTEB Leaderboard** — Multilingual embedding model benchmarks. https://huggingface.co/spaces/mteb/leaderboard
- **Phrase Next-GenMT** — Uses RAG to retrieve fuzzy TM matches as in-context examples. https://support.phrase.com/hc/en-us/articles/14299433827996
- **BGE-M3** — Multi-function multilingual embedding model. https://huggingface.co/BAAI/bge-m3
- **Nomic Embed Text v2 MoE** — Multilingual embedding with MoE efficiency. https://huggingface.co/nomic-ai/nomic-embed-text-v2
