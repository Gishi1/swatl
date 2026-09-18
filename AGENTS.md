# AGENTS.md

## What this project is

swatl is an AI translation and proofreading studio for EPUB e-books. It reads an EPUB, extracts translatable text segments, translates them via a pluggable LLM backend, runs a proofreading pass, audits quality, and writes back an English EPUB — preserving all non-text elements (images, CSS, fonts) byte-for-byte. **MVP language pair: Chinese (zh) → English (en).** "Done" means a real Chinese EPUB (≥50 k words) can be translated end-to-end, proofread, and exported as an English EPUB that opens correctly in ≥2 readers (Calibre, Apple Books, or browser).

## Status

Repository initialized 2026-09-16. Translation core (Phase 1) through Web GUI redesign + Context DB (Phase 7) complete. 424 tests passing (incl. 9 browser e2e), ruff clean; CI green on Python 3.11 and 3.12. Context-aware embedding retrieval (Ollama + FAISS) wired into translation, and a full-featured web GUI with multi-panel layout.

## Commands

- Install: `uv sync` (requires a venv; use `nix-shell` below for a clean env)
- Test: `uv run pytest` (after `uv venv && uv pip install '.[dev]'`)
- Lint / format: `uv run ruff check . && uv run ruff format --check .`
- Run (MVP): `uv run swatl translate book.epub --target en --provider deepseek --state ./state`

### Development Shell (NixOS)

Because this is a NixOS system, Python environments are externally managed (PEP 668). Use `nix-shell` for an isolated dev shell:

```bash
# Clear stale Nix SQLite journal if you get "attempt to write a readonly database"
rm -f ~/.cache/nix/fetcher-cache-v3.sqlite-journal

# Enter dev shell (Python 3.12, uv, pytest, ruff)
nix-shell --pure -p uv python312 python312Packages.setuptools python312Packages.wheel --run "uv venv && source .venv/bin/activate && uv pip install '.[dev]' && uv run pytest -v && uv run ruff check src/swatl tests && uv run ruff format --check src/swatl tests"

# Or step-by-step:
nix-shell --pure -p uv python312 python312Packages.setuptools python312Packages.wheel
uv venv
source .venv/bin/activate
uv pip install '.[dev]'
uv run pytest -v
uv run ruff check .
uv run ruff format .
```

## Conventions

- **Language:** Python 3.11+ (development on 3.12)
- **Package manager:** `uv` (use `uv add` for deps, `uv run` for commands)
- **Build backend:** hatchling (`[tool.hatch.build.targets.wheel] packages = ["src/swatl"]`)
- **Module layout:** `src/swatl/` — flat package with submodules per feature
- **Linting / formatting:** `ruff` (line-length 100, target py311)
- **Testing:** `pytest` + `pytest-asyncio`; test path: `tests/`
- **Commit style:** short imperative subject; reference ADRs when relevant (e.g., `feat: implement segmenter per ADR-0002`)
- **Never commit:** user EPUB files, API keys, `.env` files, or `*.epub`
- **Never edit:** files under `~/.dsh` by hand — use the `dsh-plugin-ops` skill

## Environment

- Workspace root: the repository root (run `pwd` to confirm)
- Developed with DeepSeek Harness; harness home is `~/.dsh`
- Python 3.12.12, uv 0.10.4 available
- To add, verify, or remove harness plugins, use the `dsh-plugin-ops` skill rather than editing files under `~/.dsh` by hand
