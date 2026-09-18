# swatl — AI Translation & Proofreading Studio for EPUB Books

> Translate e-books with LLM-powered accuracy, terminology control, and proofreading — then export an EPUB that opens in any reader.

**MVP language pair:** Chinese (zh) → English (en)

---

## What It Does

swatl reads an EPUB e-book, extracts translatable text segments (paragraphs, headings, captions), translates them using a pluggable LLM backend, runs a proofreading pass, audits the output for quality, and writes back a new EPUB with the translation — preserving all images, CSS, fonts, and structure byte-for-byte.

Key features:

- **Segment-level translation** with per-segment checkpoints (resume from where you left off).
- **Pluggable AI backend**: cloud (OpenAI, DeepSeek, Anthropic, DashScope) or local (Ollama).
- **Glossary-driven terminology**: inject your own term list for consistent translation.
- **Proofreading pass**: a separate LLM call to improve grammar, style, and naturalness.
- **Quality audit**: CJK-residue detection, omission heuristics, glossary compliance.
- **Interactive review**: edit, accept, skip, or regenerate individual segments.
- **Cost tracking**: see token counts and estimated USD before you spend.
- **Bilingual export**: parallel source+target EPUB for side-by-side reading.
- **Translation Memory**: disk-backed cache reused across runs.
- **Back-translation verification**: sample-based quality check by re-translating to Chinese.
- **Style guide**: control translation tone (formal, casual, literary, technical).
- **Multi-language support**: Japanese (ja↔en), Chinese (zh↔en), plus extensible pairs.
- **Language-aware audit**: Hiragana/Katakana/Kanji detection for Japanese, CJK for Chinese.
- **Web GUI**: browser-based segment review, search, glossary/context management, and provider config (`swatl web`).

## Requirements

- Python 3.11 or newer
- [`uv`](https://docs.astral.sh/uv/) for installation
- An API key for a cloud provider, **or** a local model server (Ollama), **or** nothing at all if you just want to try the pipeline with `--provider mock`

## Quick Start

```bash
# 1. Install
uv sync

# 2. Configure a provider (only needed for real translation)
mkdir -p ~/.config/swatl
cp config/providers.example.toml ~/.config/swatl/providers.toml
export DEEPSEEK_API_KEY=sk-...        # the name comes from api_key_env in the config

# 3. Try the whole pipeline offline (no API key, deterministic output)
swatl translate book.epub --provider mock --state ./state

# 4. Or translate for real
swatl translate book.epub --target en --provider deepseek --state ./state

# 5. Proofread, audit, review
swatl proofread --state ./state --provider deepseek
swatl audit --state ./state
swatl review --state ./state

# 6. Export the translated EPUB
swatl export --state ./state -o translated.epub

# 7. Launch the web GUI
swatl web --port 8080
```

`--provider mock` is the offline provider used by the test suite: it translates
CJK deterministically and needs no network or credentials, which makes it the
fastest way to verify an installation end-to-end.

### Advanced Usage

```bash
# Bilingual export (source + target side-by-side)
swatl export --state ./state --bilingual -o bilingual.epub

# Translation Memory (cache translations for reuse)
swatl translate book.epub --translation-memory ./tm.json --state ./state

# Style guide (formal, casual, literary, technical)
swatl translate book.epub --style literary --state ./state

# Back-translation quality check (requires a real LLM)
swatl back-translate --state ./state --provider deepseek --sample 20

# Language-aware audit (detect Hiragana/Katakana for Japanese)
swatl audit --state ./state --source-lang ja
```

See [docs/PLAN.md](docs/PLAN.md) for the phased roadmap, [docs/SPEC.md](docs/SPEC.md) for the specification, and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the module map.

## Web GUI

`swatl web` serves a single-page studio on `http://127.0.0.1:8080` with four tabs:

| Tab | What it does |
|---|---|
| **Segments** | Search/filter segments (server-side), paginate, open the detail panel, edit the translation, accept, skip, or regenerate |
| **Context DB** | Curate context entries — add, edit, delete, search, import text/JSON/CSV, or prefill from translated segments |
| **Glossary** | Add and remove term→translation pairs stored in the state directory |
| **Settings** | Inspect configured providers, add a provider, and switch the active state directory |

The active state directory is remembered in `localStorage` and reloaded
automatically. State directories are passed as query parameters, so nested and
absolute paths (`./state`, `~/books/三国-state`) work too. Read-only endpoints
never create directories on disk.

### HTTP API

The GUI is a thin client over a small JSON API (all endpoints take `state_dir`
as a query parameter):

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/run` | Run metadata (`run.json`) |
| `GET` | `/api/segments` | Paginated segments (`status`, `q`, `page`, `page_size`) |
| `GET` | `/api/segment/{id}` | Single segment |
| `GET` | `/api/stats` | Per-status counts |
| `PATCH` | `/api/segment/{id}` | Update translation/status |
| `POST` | `/api/accept/{id}` · `/api/skip/{id}` · `/api/regenerate/{id}` | Review actions |
| `GET`/`POST`/`PATCH`/`DELETE` | `/api/context…` | Context DB CRUD, search, stats, import, prefill |
| `GET`/`POST`/`DELETE` | `/api/glossary…` | Glossary CRUD |
| `GET`/`POST` | `/api/config` | List/add providers |

## CLI Reference

| Command | Description |
|---|---|
| `swatl inspect <epub>` | Show EPUB metadata, segment count, token estimates |
| `swatl translate <epub>` | Translate with LLM (supports TM, style, glossary, `--dry-run`) |
| `swatl proofread` | Run proofreading pass on translated segments |
| `swatl review` | Interactive segment review (`-y` to auto-accept) |
| `swatl audit` | Quality audit (CJK residue, omission, glossary miss) |
| `swatl export` | Export translated EPUB (with `--bilingual` option) |
| `swatl back-translate` | Back-translation quality verification |
| `swatl config <name>` | Show provider settings |
| `swatl glossary-init` | Initialize a glossary file |
| `swatl glossary-add <file>` | Add a term to a glossary |
| `swatl web` | Launch the web GUI |

## Supported Providers

| Provider | Type | Notes |
|---|---|---|
| **DeepSeek** | Cloud (OpenAI-compatible) | Cheap, strong Chinese, `deepseek-chat` |
| **OpenAI** | Cloud (OpenAI-compatible) | `gpt-4o`, highest quality |
| **Anthropic** | Cloud (OpenAI-compatible) | `claude-sonnet-4`, strong tone control |
| **Ollama** | Local | `qwen2.5:32b` recommended for Chinese |
| **DashScope** | Cloud (OpenAI-compatible) | `qwen3-mt` translation-specific model |

## Architecture

```
EPUB → (ingest) → segments → (translate) → translations → (proofread) → review → (audit) → export → EPUB
                                    ↕                              ↕
                              Translation Memory              Review Session
                              Style Guide                     Cost Tracking
                              Back-Translation
```

```
src/swatl/
├── ingest/       EPUB unzip, OPF parsing, XHTML segmentation + anchors
├── translate/    provider orchestration, prompting, translation memory
├── providers/    openai-compatible client + offline mock provider
├── proofread/    second-pass refinement
├── review/       interactive review session
├── audit/        quality checks (CJK residue, omissions, glossary)
├── quality/      back-translation sampling
├── context/      embedding index + retrieval (FAISS, sentence-transformers)
├── context_db/   curated context entries (CRUD, import)
├── state/        append-only JSONL checkpoints (last-write-wins)
├── writeback/    in-place text replacement + EPUB re-zip
└── web/          FastAPI app + single-page GUI
```

## Development

```bash
# Install with dev dependencies
uv sync --extra dev

# Tests
uv run pytest -q

# Lint + format
uv run ruff check .
uv run ruff format --check .

# Apply formatting
uv run ruff format .
```

### Browser (end-to-end) tests

`tests/e2e/` drives a real Chromium against a real server. It is optional and
skips itself when Playwright is absent:

```bash
uv sync --extra e2e
uv run playwright install chromium
uv run pytest tests/e2e -q
```

### Validating an export

```bash
# Read the exported EPUB with Calibre (if installed)
ebook-meta translated.epub        # should report the target language
ebook-convert translated.epub out.txt
```

On NixOS (externally managed Python), use the `nix-shell` recipe in
[AGENTS.md](AGENTS.md) instead of a bare `uv venv`.

### Project Stats

| Metric | Value |
|---|---|
| Source files | 39 Python files, ~6.5k lines (13 modules) |
| Test files | 27 (incl. browser e2e) |
| Tests | 337 (all passing) |
| Lint | `ruff check` — 0 errors |
| Format | `ruff format --check` — clean |
| Language pairs | zh↔en, ja↔en (extensible) |
| CLI commands | 11 |
| Web GUI | Built-in (`swatl web`) |

## Known Limitations

- The quality audit is heuristic: it flags likely problems, it does not prove correctness.
- Back-translation similarity is lexical overlap, not a learned metric.
- Context-aware embedding retrieval downloads a sentence-transformers model on first use.
- The web GUI targets a single local user: it binds to `127.0.0.1` and has no authentication.
- EPUB2 NCX (`toc.ncx`) navigation labels are not translated; EPUB3 nav documents are.

### What gets translated

Spine documents, the EPUB3 navigation document, and `<head><title>` elements are
translated. Within a document, text is handled per text node: an element's own
text, the text of common inline elements (`em`, `strong`, `a`, `span`, `b`, `i`,
`sup`, …), and the text that follows them. Images, CSS, fonts and all other
markup are copied through unchanged.

## License

MIT — see [LICENSE](LICENSE).
