# swatl

**An AI translation and proofreading studio for EPUB e-books.**

[![CI](https://github.com/Gishi1/swatl/actions/workflows/ci.yml/badge.svg)](https://github.com/Gishi1/swatl/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-Buy%20me%20a%20coffee-ff5e5b?logo=ko-fi&logoColor=white)](https://ko-fi.com/gishi)

swatl reads an EPUB, extracts its translatable text, translates it with a
pluggable LLM backend, runs a proofreading pass, audits the result, and writes a
new EPUB — preserving every image, stylesheet, font and other non-text asset
byte-for-byte. The MVP language pair is **Chinese → English**; Japanese → English
is supported, and new pairs are a configuration change rather than a code change.

![swatl translation studio](docs/images/studio.png)

## Table of contents

- [Features](#features)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Web GUI](#web-gui)
- [CLI reference](#cli-reference)
- [How it works](#how-it-works)
- [Configuration](#configuration)
- [Supported providers](#supported-providers)
- [Development](#development)
- [Validating an export](#validating-an-export)
- [Known limitations](#known-limitations)
- [Support](#support)
- [License](#license)

## Features

| | |
|---|---|
| **Segment-level translation** | Per-segment checkpoints; interrupted runs resume where they stopped. |
| **Pluggable backends** | OpenAI, DeepSeek, Anthropic, DashScope or a local Ollama server — plus an offline `mock` provider for testing. |
| **Glossary control** | Pin terminology once and apply it consistently across the whole book. |
| **Proofreading pass** | A second LLM pass for grammar, style and naturalness. |
| **Quality audit** | CJK-residue, omission and glossary-compliance heuristics. |
| **Interactive review** | Search, filter, edit, accept, skip or requeue individual segments in the browser. |
| **Translation memory** | Disk-backed cache, reused across runs and books. |
| **Style guides** | Formal, casual, literary or technical register. |
| **Bilingual export** | Parallel source/target EPUB for side-by-side reading. |
| **Back-translation QA** | Sample-based verification that re-translates to the source language and scores similarity. |
| **Cost visibility** | Token estimates and USD projections before you spend anything. |

## Installation

Requires **Python 3.11+** and [`uv`](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/Gishi1/swatl.git
cd swatl
uv sync
```

To try the pipeline without any API key or network access, use the bundled
offline provider:

```bash
uv run swatl translate book.epub --provider mock --state ./state
```

## Quick start

```bash
# 1. Configure a provider (only needed for real translation)
mkdir -p ~/.config/swatl
cp config/providers.example.toml ~/.config/swatl/providers.toml
export DEEPSEEK_API_KEY=sk-...      # the variable named by api_key_env

# 2. Translate a book
uv run swatl translate book.epub --target en --provider deepseek --state ./state

# 3. Proofread, then audit
uv run swatl proofread --state ./state --provider deepseek
uv run swatl audit --state ./state

# 4. Review and edit in the browser
uv run swatl web --port 8080

# 5. Export the translated EPUB
uv run swatl export --state ./state -o translated.epub
```

`mock` is the offline provider used by the test suite. It translates CJK
deterministically and needs no credentials, which makes it the fastest way to
verify an installation end-to-end.

### Advanced usage

```bash
# Bilingual export (source and target side by side)
uv run swatl export --state ./state --bilingual -o bilingual.epub

# Reuse translations across runs
uv run swatl translate book.epub --translation-memory ./tm.json --state ./state

# Literary register, with a glossary
uv run swatl translate book.epub --style literary --glossary ./glossary.toml --state ./state

# Back-translation quality check (requires a real LLM)
uv run swatl back-translate --state ./state --provider deepseek --sample 20

# Language-aware audit for a Japanese source
uv run swatl audit --state ./state --source-lang ja
```

## Web GUI

`uv run swatl web` serves a single-page studio on `http://127.0.0.1:8080`.

| Tab | Purpose |
|---|---|
| **Segments** | Server-side search and status filtering, pagination, and a detail panel for editing, accepting, skipping or requeueing a segment |
| **Context DB** | Curate reusable context entries — add, edit, delete, import text/JSON/CSV/HTML, or prefill from translated segments |
| **Glossary** | Manage term → translation pairs stored with the book's state |
| **Settings** | Inspect configured providers, add one, and switch the active state directory |

![Segment review](docs/images/review.png)

![Context DB](docs/images/context-db.png)

The active state directory is remembered in `localStorage` and reloaded
automatically. State directories travel as query parameters, so nested and
absolute paths work. Read-only endpoints never create directories on disk, and
the layout adapts to narrow viewports.

### HTTP API

The GUI is a thin client over a small JSON API. Every endpoint takes
`state_dir` as a query parameter.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/run` | Run metadata (`run.json`) |
| `GET` | `/api/segments` | Paginated segments (`status`, `q`, `page`, `page_size`) |
| `GET` | `/api/segment/{id}` | A single segment |
| `GET` | `/api/stats` | Per-status counts |
| `PATCH` | `/api/segment/{id}` | Update a translation or status |
| `POST` | `/api/accept/{id}`, `/api/skip/{id}`, `/api/regenerate/{id}` | Review actions |
| `GET`/`POST`/`PATCH`/`DELETE` | `/api/context…` | Context DB CRUD, search, stats, import, prefill |
| `GET`/`POST`/`DELETE` | `/api/glossary…` | Glossary CRUD |
| `GET`/`POST` | `/api/config` | List or add providers |

## CLI reference

| Command | Description |
|---|---|
| `swatl inspect <epub>` | EPUB metadata, segment count and token/cost estimates |
| `swatl translate <epub>` | Translate a book (glossary, TM, style, `--dry-run`) |
| `swatl proofread` | Second-pass refinement of translated segments |
| `swatl review` | Interactive review (`-y` to auto-accept) |
| `swatl audit` | Quality audit |
| `swatl export` | Write the translated EPUB (`--bilingual` for a parallel edition) |
| `swatl back-translate` | Back-translation quality verification |
| `swatl config <name>` | Show a provider's settings |
| `swatl glossary-init` | Create a glossary file |
| `swatl glossary-add <file>` | Add a term to a glossary |
| `swatl web` | Launch the web GUI |

## How it works

```
EPUB ─▶ ingest ─▶ segments ─▶ translate ─▶ proofread ─▶ review ─▶ audit ─▶ export ─▶ EPUB
                                   │            │
                          translation memory   glossary · style guide · cost tracking
```

```
src/swatl/
├── ingest/       EPUB unzip, OPF parsing, segmentation and XPath anchors
├── providers/    OpenAI-compatible client + offline mock provider
├── translate/    batching, concurrency, retries, prompting, translation memory
├── proofread/    second-pass refinement
├── review/       interactive review session
├── audit/        quality heuristics
├── quality/      back-translation sampling
├── context/      embedding index and retrieval (FAISS + sentence-transformers)
├── context_db/   curated context entries (CRUD and import)
├── state/        append-only JSONL checkpoints with last-write-wins semantics
├── writeback/    in-place text replacement and EPUB re-zip
└── web/          FastAPI application and single-page UI
```

Translation is deliberately non-destructive. Segments carry an XPath anchor to
the exact text node they came from, and export rewrites only that node — images,
CSS, fonts and markup structure are copied through untouched. Export also
updates `lang`/`xml:lang` and the package document's `<dc:language>`, and writes
a spec-compliant `mimetype` entry so the result opens in Calibre, Apple Books
and browsers alike.

## Configuration

Provider configs are read from the first of:

1. `~/.config/swatl/providers.toml`
2. `./config/providers.toml`
3. `./providers.toml`

API keys are never stored in these files — only the name of the environment
variable that holds them. See [`config/providers.example.toml`](config/providers.example.toml).

## Supported providers

| Provider | Type | Notes |
|---|---|---|
| **DeepSeek** | Cloud (OpenAI-compatible) | `deepseek-chat` — inexpensive and strong at Chinese |
| **OpenAI** | Cloud (OpenAI-compatible) | `gpt-4o` |
| **Anthropic** | Cloud (OpenAI-compatible) | `claude-sonnet-4` via Anthropic's compatibility endpoint |
| **Ollama** | Local | `qwen2.5:32b` recommended for Chinese |
| **DashScope** | Cloud (OpenAI-compatible) | `qwen3-mt`, a translation-specific model |
| **mock** | Offline | Deterministic, credential-free; used by the test suite |

Any other endpoint that speaks the OpenAI chat-completions API works by adding
a provider entry.

## Development

```bash
uv sync --extra dev

uv run pytest -q                 # test suite
uv run ruff check .              # lint
uv run ruff format --check .     # format check
```

The suite includes browser-driven end-to-end tests under `tests/e2e/`. They are
optional and skip themselves when Playwright is not installed:

```bash
uv sync --extra e2e
uv run playwright install chromium
uv run pytest tests/e2e -q
```

### Validating an export

```bash
ebook-meta translated.epub              # should report the target language
ebook-convert translated.epub out.txt   # full parse by Calibre
```

### Project stats

| Metric | Value |
|---|---|
| Source | 39 Python files, ~6.5k lines across 13 modules |
| Tests | 345, including 8 browser end-to-end tests |
| Lint / format | `ruff check` and `ruff format --check` clean |
| Language pairs | zh↔en, ja↔en (extensible) |
| CLI commands | 11 |

## Known limitations

- The quality audit is heuristic: it flags likely problems, it does not prove correctness.
- Back-translation similarity is lexical overlap, not a learned metric.
- EPUB2 NCX (`toc.ncx`) navigation labels are not translated; EPUB3 navigation documents are.
- Context-aware retrieval downloads a sentence-transformers model on first use.
- The web GUI targets a single local user: it binds to `127.0.0.1` and has no authentication.

### What gets translated

Spine documents, the EPUB3 navigation document, and `<head><title>` elements.
Within a document, text is handled per text node: an element's own text, the
text of common inline elements (`em`, `strong`, `a`, `span`, `b`, `i`, `sup`, …),
and the text that follows them. Everything else is copied through unchanged.

## Support

swatl is built and maintained in my own time and is free to use under the MIT
licence. If it saved you some work, you can buy me a coffee — it is appreciated
and it funds the model credits I use to test new language pairs.

[![Buy me a coffee at ko-fi.com](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/gishi)

## License

MIT — see [LICENSE](LICENSE).
