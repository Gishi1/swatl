# ADR-0001 — Python 3.11+ with uv Package Management

| Field        | Value                          |
|--------------|--------------------------------|
| Status       | Accepted                       |
| Date         | 2025-07-20                     |
| Supersedes   | —                              |

## Context

We need a language and toolchain for EPUB parsing, LLM integration, and a CLI interface.

## Decision

Use **Python 3.11+** with **uv** as the package manager and build tool.

## Rationale

- **ebooklib**, the mature EPUB2/3 round-trip library, is Python-only.
- All significant open-source AI EPUB translators (oomol-lab/epub-translator, bilingual_book_maker, lexora-ai) are Python.
- Python has the richest LLM SDK ecosystem (`openai`, `anthropic`, `httpx`, `deepl`).
- **uv** (v0.10.4+ on this machine) provides sub-second environment setup, faster than pip + venv.
- hatchling is the chosen build backend: simple, well-maintained, no TypeScript transpilation overhead.

## Consequences

- Dependencies must be Python-compatible.
- Web GUI (Phase 4) will use FastAPI (Python) rather than Node.js, keeping a single language in the monorepo.
- Users who prefer Node/TypeScript may need to use the CLI or wait for the web wrapper.
