# Architecture — swatl

> Module layout, data flow, concurrency model, and key design decisions.

---

## 1. Module Layout

```
src/swatl/
├── __init__.py              # version, package entry
├── cli.py                   # CLI entry point (typer), subcommand router
├── config.py                # provider config loader (TOML + pydantic-settings)
├── models.py                # Pydantic data models (Segment, Run, GlossaryEntry)
│
├── ingest/
│   ├── __init__.py
│   ├── epub_reader.py       # unzip + parse content.opf + spine order
│   └── segmenter.py         # walk XHTML, extract translatable segments + anchors
│
├── providers/
│   ├── __init__.py
│   ├── base.py              # Provider abstract protocol
│   ├── openai_compat.py     # OpenAI-compatible (covers OpenAI, DeepSeek, Ollama, DashScope, vLLM)
│   ├── anthropic.py         # Anthropic Claude adapter
│   ├── deepl.py             # DeepL NMT adapter
│   └── mock.py              # Test stub (returns fixed translation)
│
├── translate/
│   ├── __init__.py
│   ├── translator.py        # orchestrate provider calls, batching, retries, concurrency
│   └── prompt_builder.py    # system prompt + glossary + context assembly
│
├── proofread/
│   ├── __init__.py
│   └── proofreader.py       # second-pass LLM calls for grammar/style
│
├── audit/
│   ├── __init__.py
│   └── auditor.py           # CJK residue, omission heuristic, glossary miss checks
│
├── review/
│   ├── __init__.py
│   └── cli.py               # interactive review TUI
│
├── writeback/
│   ├── __init__.py
│   └── writer.py            # in-place text-node replacement, re-zip
│
└── state/
    ├── __init__.py
    ├── store.py             # JSONL read/write with last-write-wins
    ├── lock.py              # file-based lock for concurrent-run safety
    └── cost.py              # token count → USD estimation

└── context/                 # PHASE 6 — embedding-based context retrieval
    ├── __init__.py
    ├── embedder.py          # sentence-transformers wrapper + OpenAI fallback
    ├── index.py             # FAISS index management (add/query/save/load)
    ├── retriever.py         # retrieve + deduplicate + format for prompt
    └── store.py             # persistence (save/load index + metadata)

└── context_db/              # PHASE 7 — Context DB storage and management
    ├── __init__.py
    ├── model.py             # ContextEntry Pydantic model
    ├── store.py             # JSON/JSONL store for context entries
    └── importer.py          # File/URL/text import and chunking logic
```

---

## 2. Data Flow

```
                     ┌─────────────────────────────────────────────────────┐
                     │                    .swatl-state/                    │
                     │  segments.jsonl  run.json  tmp/                     │
                     └──────────────┬──────────────────────────────────────┘
                                    │
   book.epub ──▶ ┌─────┐  ┌──────┴──────┐  ┌────────┐  ┌───────────┐  ┌────────┐
                 │ Ingest│──▶│  Extract   │──▶│Translate │──▶│Proofread │──▶│Write-back│
                 │ (lxml)│  │  + State   │  │  (LLM)  │  │  (LLM)  │  │(in-place)│
                 └─────┘  └─────────────┘  └────────┘  └───────────┘  └────────┘
                                                    │                    │
                                                    ▼                    ▼
                                              segments.jsonl       output.epub
                                              (per-segment)        (structure-preserving)
```

---

## 3. Concurrency Model

- **Async I/O** via `asyncio` + `httpx.AsyncClient`.
- **Bounded semaphore** (default 4 workers) limits concurrent LLM calls.
- **Batching**: segments grouped by document (chapter), up to 8 k chars per batch.
- **Backoff**: exponential retry with jitter on HTTP errors (429 → wait 2^n * 1.5s).
- **State persistence**: after every 10 segments (or on signal), segments are flushed to JSONL.

---

## 4. Key Design Decisions (Summary)

See `docs/adr/` for full ADRs.

| Decision | Rationale |
|---|---|
| Python + uv | ebooklib ecosystem; all major AI EPUB translators are Python; uv for fast dev. |
| Segment-level translation | Better quality/cost trade-off; resumable; fits LLM context windows. |
| In-place write-back | Byte-identical preservation of images, CSS, fonts; no structure regeneration. |
| OpenAI-compatible provider core | Covers 4+ providers with one adapter; easy to add more. |
| Glossary + TM for consistency | Deterministic terminology; cost savings on repeated runs. |
| ContextDB (Phase 6) | Semantic retrieval for cross-chapter consistency; embedding + FAISS. |
| GUI Redesign + Context DB Mgmt (Phase 7) | Multi-panel layout, Context DB CRUD, keyboard shortcuts, import. |

---

## 5. State Format Details

### 5.1 `segments.jsonl`

One JSON object per line, one segment per file. Append-only:

```json
{"id":"p-0041","doc":"text/ch01.xhtml","anchor":".//p[4]","tag":"p","source_text":"三体是一个宏大的概念。","translated":"Three-Body is a grand concept.","status":"proofread","provider":"deepseek","tokens_in":18,"tokens_out":12,"context":null,"glossary_hits":["三体"]}
```

### 5.2 `run.json`

```json
{
  "book": {"title":"三体","author":"刘慈欣","lang":"zh","version":"EPUB 3.0"},
  "pair": ["zh", "en"],
  "provider": "deepseek",
  "created_at": "2025-07-20T14:30:00Z",
  "updated_at": "2025-07-20T15:12:00Z",
  "total_segments": 1247,
  "stages_completed": ["extract", "translate", "proofread", "audit", "writeback"],
  "total_tokens_in": 48320,
  "total_tokens_out": 39210,
  "estimated_cost_usd": 0.24
}
```

---

## 6. EPUB Handling Detail

### 6.1 Extraction

1. `zipfile.ZipFile` → extract to temp dir.
2. Find `META-INF/container.xml` → locate `content.opf`.
3. Parse `content.opf` → extract `<spine>` order (document sequence).
4. For each `.xhtml` in spine order:
   - Parse with `lxml.html.fromstring()`.
   - Walk `<body>` for translatable tags (`<p>`, `<h1>`–`<h6>`, `<blockquote>`, `<li>`, `<figcaption>`).
   - Build XPath anchor: relative path from `<body>` root, e.g., `.//p[4]`.
   - Extract `text_content()` or first text node for mixed-content elements.
   - Record element tag and language attributes.

### 6.2 Write-back

1. Re-parse each XHTML file from temp dir (original, untouched).
2. For each segment: find element via `lxml.xpath(anchor)`.
3. Handle mixed content:
   - Pure text: replace `elem.text` directly.
   - Mixed (e.g., `<p>前 <b>三体</b> 是一个...</p>`): wrap translated text in `<span xml:lang="en">...</span>` or replace `elem.text` and handle `elem.tail` for trailing content.
4. Set `lang="en"` and `xml:lang="en"` on the root `<html>` element.
5. Preserve all non-text elements (images, `<style>`, `<script>`) exactly as-is.
6. Re-zip from temp dir using `zipfile.ZipFile` with `ZIP_DEFLATED`.

---

## 7. Prompt Design

### 7.1 Translation System Prompt (Template)

```
You are a professional Chinese → English translator. Translate the following text accurately
and naturally. Preserve all HTML tags and formatting. Do NOT add commentary.

Glossary (use these exact translations):
- 三体 → Three-Body
- 叶文洁 → Ye Wenjie
- ...

Previous context (for continuity):
{context}

Related context (semantically similar, from earlier in the document):
{retrieved_context}

Translate the following segment:
{source_text}

Return JSON: {"translated": "..."}
```

### 7.2 Proofreading System Prompt (Template)

```
You are an English language proofreader. Review and improve the following translation
for grammar, style, and naturalness. Preserve the meaning and any glossary terms.

Glossary:
- 三体 → Three-Body

Original: {source_text}
Translation: {translated}

Return JSON: {"translated": "improved version"}
```
