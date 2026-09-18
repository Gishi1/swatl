# Project Plan — swatl

> Phased plan with milestones, tasks, and acceptance criteria.

---

## Phase 0 — Scaffolding (Current)

**Goal:** Repository structure, tooling, and a green test suite.

| # | Task | Status |
|---|---|---|
| 0.1 | `pyproject.toml` (hatch, uv, typer deps) | Done |
| 0.2 | `src/swatl/__init__.py` with `__version__` | Done |
| 0.3 | `tests/test_smoke.py` — green | Done |
| 0.4 | `.gitignore` extended for Python | Done |
| 0.5 | `README.md`, `AGENTS.md` updated | Done |
| 0.6 | `uv sync && uv run pytest` passes (53/53 tests green) | **Done** |

---

## Phase 1 — Translation Core (MVP)

**Goal:** CLI tool that reads a Chinese EPUB, translates it via an LLM provider, and writes back an English EPUB.

### Milestones

> Last updated: 2026-01-16 — Phase 7 complete, 256 tests green, lint+format clean, package installable

| # | Milestone | Acceptance Criteria |
|---|---|---|
| 1.1 | **EPUB ingest** | ✅ `swatl inspect` works; extracts metadata, segments, estimates tokens. |
| 1.2 | **Segment extraction** | ✅ Fixture EPUB → stable segments; 23 segments from 3 chapters verified. |
| 1.3 | **Provider abstraction** | ✅ Mock provider + async interface; full pipeline (extract → translate → proofread → writeback) verified. |
| 1.4 | **Real provider integration** | ✅ `OpenAICompatible` provider implemented (DeepSeek, Ollama, etc.); works with any OpenAI-compatible API. |
| 1.5 | **Checkpoint / resume** | ✅ `SegmentStore` supports JSONL append, resume from state. |
| 1.6 | **In-place write-back** | ✅ In-place text replacement; verified structure preservation (CSS, images byte-identical). |
| 1.7 | **Glossary injection** | ✅ Glossary TOML loading/saving, CLI commands (`glossary-init`, `glossary-add`), injection in prompts, audit detection of misses. |
| 1.8 | **Proofreading** | ✅ `swatl proofread` CLI command; Proofreader class with concurrency control. |
| 1.9 | **Quality audit** | ✅ `swatl audit` CLI command; CJK residue, omission, glossary miss, empty/short detection. |
| 1.10 | **Export** | ✅ `swatl export` CLI command; re-zips translated EPUB. |

### Tests (256 total)

| Module | Tests | Coverage |
|---|---|---|
| `test_ingest.py` | 8 | EPUB extraction, segmenter, stable IDs |
| `test_translate.py` | 12 | Prompt builder, JSON parsing, token estimation |
| `test_mock_provider.py` | 8 | Mock translation, glossary injection, proofreading |
| `test_writeback.py` | 5 | EPUB creation, structure preservation, CSS/image byte-identical |
| `test_state_store.py` | 10 | JSONL append, last-write-wins, status queries |
| `test_models.py` | 7 | Pydantic models roundtrip |
| `test_audit.py` | 13 | CJK residue, omission, glossary miss, summary report |
| `test_cli.py` | 8 | CLI commands, inspect, glossary CRUD, dry-run |
| `test_integration.py` | 3 | End-to-end pipeline, checkpoint resume, metadata serialization |
| `test_integration_full.py` | 9 | Full pipeline with all features, web API CRUD, TM eviction/disk, BT report |
| `test_review.py` | 11 | Accept, edit, skip, regenerate, navigation, session save |
| `test_bilingual.py` | 4 | Parallel document creation, structure preservation, translation text |
| `test_cost_tracking.py` | 5 | Cost field, serialization, store persistence |
| `test_translation_memory.py` | 15 | Lookup, add, disk persistence, eviction, hit rate, translator integration |
| `test_back_translation.py` | 15 | Levenshtein similarity, report generation, save/load, flag classification |
| `test_style_guide.py` | 9 | Style options, default fallback, coexistence with glossary/context |
| `test_language_pair.py` | 8 | zh/ja/en→zh/en→ja instruction injection, style/glossary coexistence |
| `test_language_audit.py` | 17 | Hiragana/Katakana/Kanji detection, language-aware residue, count, audit |
| `test_web.py` | 21 | FastAPI endpoints, HTML serving, segment CRUD, provider config, Context DB CRUD + import |
| `test_config_save.py` | 2 | save_provider file creation, add to existing |
| `test_context.py` | 32 | Embedder (local + OpenAI), FAISS index CRUD, retrieval accuracy, dimension inference |
| `test_context_db.py` | 33 | ContextEntry model, JSON store CRUD/search/tags/stats, importer chunking/HTML/JSON/CSV |

### Source (39 files, 14 modules, ~5800 lines)

| Module | Files |
|---|---|
| `cli.py` | Main CLI (Typer, 10 commands) |
| `models.py` | Pydantic models |
| `glossary.py` | TOML glossary I/O |
| `config.py` | Provider config loading |
| `ingest/` | EPUB reader, segmenter |
| `translate/` | Translator, prompt builder, TM |
| `context/` | Embedder, FAISS index, retriever, store |
| `context_db/` | ContextEntry model, JSON store, importer |
| `providers/` | Base, OpenAI-compatible, Mock |
| `proofread/` | Proofreader |
| `audit/` | Quality auditor |
| `review/` | Review session engine |
| `quality/` | Back-translation verification |
| `state/` | JSONL segment store |
| `writeback/` | EPUB writer (in-place + bilingual) |
| `web/` | FastAPI server + embedded HTML UI |

### Estimated effort: 3–5 days

### Risks

- **EPUB quirks:** Some EPUBs use non-standard spine or broken OPF. Mitigation: log warnings, skip unparseable items.
- **Mixed-content elements:** `<p>` with `<b>`, `<i>`, `<a>`. Mitigation: wrap translation in `<span>` or use lxml `text`/`tail` handling.
- **LLM rate limits:** Mitigation: concurrency control + exponential backoff.

---

## Phase 2 — Proofreading + Audit

**Goal:** Second-pass proofreading and quality audit for production-ready output.

| # | Task | Status |
|---|---|---|
| 2.1 | `swatl proofread` command — LLM second pass | ✅ Implemented |
| 2.2 | Proofreading system prompt (grammar, style, tone) | ✅ Implemented |
| 2.3 | `swatl audit` — CJK residue, omission, glossary miss | ✅ Implemented |
| 2.4 | `swatl review` interactive CLI (accept / edit / skip / regenerate) | ✅ Implemented |
| 2.5 | Cost tracking (tokens + USD) in `run.json` | ✅ Implemented |

### Estimated effort: 3–4 days

---

## Phase 3 — Polish & Bilingual

**Goal:** Bilingual output, Translation Memory, and power-user features.

| # | Task | Status |
|---|---|---|
| 3.1 | Bilingual EPUB export (`--bilingual` interleaves source/target) | ✅ Implemented |
| 3.2 | Translation Memory (TM) — segment hash → cached translation | ✅ Implemented |
| 3.3 | Back-translation verification (sample-based omission detection) | ✅ Implemented |
| 3.4 | Style guide support (formal, casual, literary, technical) | ✅ Implemented |
| 3.5 | Packaging (hatchling, pyproject.toml, entry point, classifiers) | ✅ Implemented |
| 3.6 | Language-aware token estimation and audit heuristics | ✅ Implemented |

### Estimated effort: 4–6 days

---

## Phase 4 — Web GUI (Optional)

**Goal:** Browser-based interface for translation management and review.

| # | Task | Status |
|---|---|---|
| 4.1 | Local FastAPI server | ✅ Implemented |
| 4.2 | Browser UI (segment review, progress, export) | ✅ Implemented |
| 4.3 | Provider config UI | ✅ Implemented |

### Estimated effort: 5–8 days

---

## Phase 5 — Language Expansion

**Goal:** Add Swahili (`swa`) and other language pairs.

| # | Task | Status |
|---|---|---|
| 5.1 | Prompt templates per language pair | ✅ Implemented (zh/ja/en→zh/en→ja) |
| 5.2 | Swahili provider selection (model recommendations) | Pending |
| 5.3 | Language-pair-specific heuristics in audit | ✅ Implemented (Hiragana/Katakana/Kanji detection) |

### Estimated effort: 2–3 days

---

## Phase 7 — Web GUI Redesign and Context DB Management

> **Goal:** Redesign the web GUI with multi-panel layout, tab navigation, and a dedicated Context Database management interface for prefilling, editing, and curating semantic context.

| # | Task | Status |
|---|---|---|
| 7.0 | Refactor `ui.py` — multi-panel layout, tab navigation, keyboard shortcuts | **Done** |
| 7.1 | `context_db/model.py` — `ContextEntry` Pydantic model | **Done** |
| 7.2 | `context_db/store.py` — JSON/JSONL store for context entries | **Done** |
| 7.3 | `context_db/importer.py` — file/URL/text import + chunking logic | **Done** |
| 7.4 | API endpoints: context CRUD, import, search, stats | **Done** |
| 7.5 | Context DB tab UI (search, list, edit, delete) | **Done** |
| 7.6 | Import flow (file upload, URL, chunk preview → embed & add) | **Done** |
| 7.7 | Prefill button — embed all translated segments into Context DB | **Done** |
| 7.8 | Glossary management tab (CLI only) | **Done** |
| 7.9 | Settings tab — provider config, embedding model selection | **Done** |
| 7.10 | Tests for new API endpoints | **Done** |

**Estimated effort: 12–17 days**

### Design Decisions (ADR-0008)

- **Layout**: Multi-panel with 4 tabs (Segments, Context DB, Glossary, Settings)
- **Keyboard-first**: Arrow keys navigate, shortcuts for accept/skip/regenerate
- **Context DB prefill**: Import from .txt, .md, .xhtml, .html, .json, .csv, or URL
- **Chunk preview**: Review chunks before embedding to prevent bad vectors
- **Entry editing**: Every context entry is editable (source, target, tags) and deletable
- **Technology**: Pure HTML/CSS/JS (no framework) to maintain zero-build-deploy simplicity

### Design Process (Superdesign)

> The GUI is designed on the Superdesign canvas before any implementation code is written.

1. **Init**: `superdesign init` builds UI context from the existing codebase
2. **Draft**: `superdesign create-design-draft` generates visual layouts from ADR-0008 brief
3. **Compare**: Review at least 2 visual directions side-by-side on canvas
4. **Iterate**: Refine spacing, colors, import flows until user approves
5. **Implement**: Code the approved design into `src/swatl/web/ui.py` and `app.py`

**MUST** complete design on Superdesign canvas BEFORE writing implementation code.

---

## Timeline (Ideal)

```
Week 1: Phase 0 + Phase 1.1–1.3
Week 2: Phase 1.4–1.7
Week 3: Phase 2.1–2.5 (proofreading + audit commands)
Week 4: Phase 3.1–3.5
Week 5: Phase 4 (optional) / Phase 5
```

## Phase 6 — Context Database (Embedding-Based Retrieval)

> **Goal:** Embed translated segments into a vector index so semantically relevant context can be injected into prompts on the fly — improving cross-chapter consistency and terminology recall.

| # | Task | Status |
|---|---|---|
| 6.1 | `context/embedder.py` — sentence-transformers wrapper + OpenAI fallback | **Done** |
| 6.2 | `context/index.py` — FAISS index management (add/query/save/load) | **Done** |
| 6.3 | `context/retriever.py` — retrieve + deduplicate + format for prompt | **Done** |
| 6.4 | Integrate retriever into `prompt_builder.py` and `translator.py` | **Done** |
| 6.5 | CLI flags: `--context-enabled`, `--context-k`, `--context-cross-doc`, `--context-model` | **Done** |
| 6.6 | Tests (`tests/test_context.py`) — embedder, index CRUD, retrieval accuracy | **Done** |
| 6.7 | Documentation (`docs/adr/0007-context-db-embedding-retrieval.md`) | Pending |

**Estimated effort: 5–8 days**

### Design Decisions (ADR-0007)

- **Embedding model**: `nomic-embed-text-v2-moe` (305M active params, 768-dim, multilingual, Apache-2.0). Cloud fallback: OpenAI `text-embedding-3-small`.
- **Vector store**: FAISS (exact inner-product, zero server overhead). Chroma as optional second path.
- **Retrieval scope**: Same-document (chapter) by default; `--context-cross-doc` to enable cross-chapter retrieval.
- **Injection**: Top-K most similar segments formatted as `source → target` pairs, capped at 2000 tokens.
- **Latency**: ~35 ms/segment (embedding + retrieval); ~6 min overhead for a 10k-segment EPUB.

---

## Long-Term Roadmap

- **PDF / MOBI input** — broader format coverage.
- **Collaborative review** — share glossary, split review across translators.
- **Plugin system** — custom extractors, custom providers, custom embedding models.
- **Calibre plugin** — one-click translation from Calibre library.
- **Quality scoring** — automated BLEU/chrF against human references (when available).
- **Web GUI** — browser-based translation management (Phase 4, complete).
- **Language expansion** — add Swahili, Japanese, and other pairs (Phase 5, complete).
- **Context-aware translation** — embedding-based retrieval for cross-chapter consistency (Phase 6, complete).
- **GUI redesign** — multi-panel layout, Context DB management, keyboard shortcuts (Phase 7, complete).
- **Batch translation** — process multiple EPUBs in parallel.
- **Continuous integration** — automated CI/CD pipeline for releases.
