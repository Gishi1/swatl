# Specification — swatl

> Functional and technical requirements for the swatl EPUB translation and proofreading studio.

---

## 1. Overview

swatl is a CLI-first (later web) application that:

1. **Reads** an EPUB e-book.
2. **Extracts** translatable text segments from the XHTML spine.
3. **Translates** each segment using a pluggable LLM backend.
4. **Proofreads** the translation for grammar, style, and consistency.
5. **Audits** the output for quality (omissions, CJK residue, glossary compliance).
6. **Writes back** the translated text in-place to a new EPUB.

**MVP language pair:** Chinese (`zh`) → English (`en`). The architecture supports adding pairs (e.g., Swahili `swa`) later.

**"Done" (MVP):** A real Chinese EPUB can be translated end-to-end, proofread, audited, and exported as an English EPUB that opens correctly in Calibre / Apple Books / Kobo.

---

## 2. Personas & User Stories

| Persona | Story | Priority |
|---|---|---|
| **Self-publisher** | As a self-publisher, I want to translate my Chinese e-book into English so I can reach a wider audience. | P0 |
| **Language learner** | As a language learner, I want a bilingual EPUB with side-by-side paragraphs so I can read while learning. | P1 |
| **Translator** | As a professional translator, I want a glossary and proofreading pass so the output is production-ready. | P1 |
| **Privacy-conscious** | As a privacy-conscious user, I want to run translation entirely offline using a local model. | P1 |
| **Power user** | As a power user, I want the ability to review and edit individual segments before writing back. | P2 |

---

## 3. Scope

### In scope (MVP, Phase 1-2)

- EPUB2 & EPUB3 read (XHTML spine, CSS, images, fonts, TOC).
- Segment extraction: `<p>`, `<h1>`–`<h6>`, `<blockquote>`, `<li>`, `<figcaption>`.
- LLM translation via provider abstraction.
- Per-segment checkpoint (resumable).
- Proofreading pass (separate LLM call).
- Glossary injection.
- Quality audit (CJK residue, omission heuristic, structure check).
- In-place write-back → new EPUB.
- CLI commands: `inspect`, `translate`, `proofread`, `audit`, `export`.
- Provider config via TOML.
- Cost tracking (tokens, USD).

### Out of scope (later)

- Non-XHTML spine (HTML, EPUB2 NCX-only).
- Formatted EPUBs with complex layouts (fixed-layout, comic EPUBs).
- PDF, MOBI, DOCX input.
- Web GUI.
- Translation Memory (TM) — planned for Phase 2.
- Automated back-translation verification — planned for Phase 3.

---

## 4. Functional Requirements

### 4.1 `swatl inspect <epub>`

Show a summary of the EPUB:

```
File:       book.epub
Title:      The Three-Body Problem
Author:     Liu Cixin
Version:    EPUB 3.0
Language:   zh
Chapters:   12
Spine:      15 documents
Segments:   1 247 estimated
Estimated tokens: ~48 000 (zh → en)
Estimated cost:   ~$0.24 @ DeepSeek / ~$1.80 @ GPT-4o
```

### 4.2 `swatl translate <epub> [options]`

```
swatl translate book.epub --target en --provider deepseek --state ./state --resume
```

| Flag | Description |
|---|---|
| `--target <lang>` | Target language (ISO 639-1/3, e.g. `en`, `zh`) |
| `--provider <name>` | Provider name from config (e.g. `deepseek`, `ollama-zh`, `openai`) |
| `--state <path>` | State directory for checkpoints (default: `./.swatl-state/`) |
| `--resume` | Resume from last checkpoint (default: `true`) |
| `--concurrency <N>` | Max parallel LLM calls (default: `4`) |
| `--dry-run` | Estimate cost without making API calls |
| `--glossary <file>` | TOML glossary file |

Pipeline stages (run sequentially unless `--stage` is specified):

1. **Extract** — read EPUB, produce segments + anchors.
2. **Translate** — send segments to LLM, save results.
3. **Write-back** — replace text nodes in-place, re-zip.

### 4.3 `swatl proofread --state <path> [options]`

Second-pass LLM call per segment: receives `[source, translated_text, glossary]` and returns improved translation.

| Flag | Description |
|---|---|
| `--provider <name>` | Provider for proofreading (can differ from translate provider) |
| `--concurrency <N>` | Max parallel calls |

### 4.4 `swatl audit --state <path>`

Produce a quality report:

```
═══ Quality Audit ═══

Segments:  1 247 (1 247 translated, 0 proofread)

Issues:
  CJK residue:      3 segments  (h1-007, p-041, p-199)
  Omission flags:   12 segments (length_ratio < 0.4)
  Glossary miss:    1 term      ("三体" expected "Three-Body", got "Three-Bodies")

OK:
  Structure: All 15 documents intact
  Images:    8 images preserved
  CSS:       2 stylesheets preserved
  TOC:       Present
```

### 4.5 `swatl review --state <path>`

Interactive TUI / CLI review. Walks each segment showing source and target, lets the user:
- `Accept` (keep as-is)
- `Edit` (open in `$EDITOR`, then accept)
- `Skip` (leave untranslated)
- `Regenerate` (re-call LLM with same context)

### 4.6 `swatl export --state <path> -o <output.epub> [--bilingual]`

Finalize and write the output EPUB. `--bilingual` interleaves source and translated paragraphs.

### 4.7 `swatl config test`

Test provider connectivity with a small translation request.

---

## 5. Data Model

### 5.1 Segment

```
Segment {
  id:           string       // "h1-007", "p-0041", ...
  doc:          string       // relative path in EPUB, e.g. "text/ch01.xhtml"
  anchor:       string       // XPath/CSS selector, e.g. ".//p[4]"
  tag:          string       // "p", "h1", "blockquote", ...
  source_text:  string
  translated:   string | null
  status:       SegmentStatus
  context:      string | null // previous N segments for context
  tokens_in:    int | null
  tokens_out:   int | null
  provider:     string       // which provider was used
}

SegmentStatus = pending | translating | translated | proofread | edited | skipped | failed
```

### 5.2 State Store

Located in `--state <dir>`:

```
.swatl-state/
├── segments.jsonl        // one JSON object per line
├── run.json              // run metadata (book, pair, provider, timestamps, total tokens/cost)
├── segments.lock         // file lock (prevents concurrent runs)
└── tmp/                  // temp files (re-zipped epub fragments)
```

- `segments.jsonl` is append-only: each segment gets one line.
- On resume, the loader reads the last value per `id` (last-write-wins).
- `run.json` tracks global state: book metadata, pair, provider, cost totals, stages completed.

### 5.3 Glossary

TOML file:

```toml
[meta]
name = "Three Body Problem Glossary"
pair = ["zh", "en"]

[[entries]]
source = "三体"
target = "Three-Body"
domain = "sci-fi"

[[entries]]
source = "叶文洁"
target = "Ye Wenjie"
domain = "character"
```

### 5.4 Provider Config

TOML file (`~/.config/swatl/providers.toml` or `--config`):

```toml
[deepseek]
type = "openai-compatible"
base_url = "https://api.deepseek.com"
model = "deepseek-chat"
api_key_env = "DEEPSEEK_API_KEY"

[ollama-zh]
type = "openai-compatible"
base_url = "http://localhost:11434/v1"
model = "qwen2.5:32b"
api_key_env = "OLLAMA_API_KEY"  # optional for local

[anthropic]
type = "anthropic"
model = "claude-sonnet-4-20250514"
api_key_env = "ANTHROPIC_API_KEY"
```

---

## 6. Pipeline Architecture

```
EPUB (zip)
   │
   ▼
┌──────────┐    ┌───────────┐    ┌──────────┐
│ Extract   │───▶│ Segments  │───▶│ Translate │───▶ [state store]
│ (lxml)    │    │ (in memory│    │ (LLM API) │    (segments.jsonl)
│           │    │  + JSONL) │    └──────────┘
└──────────┘    └───────────┘           │
                                        ▼
┌──────────┐    ┌───────────┐    ┌──────────────┐
│ Write-back│◀───│Proofread  │◀───│ Audit / Review│
│ (in-place)│    │ (LLM API) │    │ (heuristics) │
└──────────┘    └───────────┘    └──────────────┘
   │
   ▼
 Output EPUB
```

### 6.1 Extract (Phase 1)

1. Unzip EPUB to a temp directory.
2. Parse `content.opf` to determine spine order.
3. For each spine item, parse XHTML with `lxml`.
4. Walk elements matching translatable tags.
5. Extract text content + element tag + XPath anchor.
6. Skip: `<script>`, `<style>`, `<meta>`, images, SVG.
7. Produce `Segment[]` list.

### 6.2 Translate (Phase 1-2)

1. Load segments from state (or extract fresh).
2. Filter to `pending` segments.
3. Build context window: inject previous N translated segments.
4. Build system prompt: instructions + glossary + target language.
5. Send batched segments (up to 8 k chars total per request) to provider.
6. Parse JSON response → extract translated text.
7. Save each segment (id + translated text + tokens) to JSONL.
8. Retry failed segments (exponential backoff, max 3 retries).

### 6.3 Proofread (Phase 2)

1. Load segments with `translated` but not `proofread`.
2. For each segment, send `[source, translated, glossary]` to provider with a proofreading system prompt.
3. Replace `translated` with proofread version if improved.
4. Save to state.

### 6.4 Audit (Phase 2)

Heuristic checks:

- **CJK residue:** regex `[\\u4e00-\\u9fff\\u3400-\\u4dbf]` in translated text → flag.
- **Omission heuristic:** `len(translated) / len(source)` ratio < 0.3 (language-adjusted) → flag.
- **Glossary miss:** search translated text for source glossary terms without matching target → flag.
- **Empty / short segments:** translated text is empty or < 3 chars → flag.
- **Structure integrity:** count of elements per document matches original.

### 6.5 Write-back (Phase 1)

1. Re-parse all spine XHTML files from the temp directory.
2. For each segment with a translated value, find the element via XPath anchor.
3. Replace text content (and handle mixed content: only modify the first text node or wrap in `<span>`).
4. Update XML `lang` and `xml:lang` attributes.
5. Re-zip from temp directory → output EPUB.

---

## 7. Provider Abstraction

### 7.1 Protocol

```python
class Provider(Protocol):
    async def translate(self, segments: list[Segment], glossary: Glossary,
                        target_lang: str, system_prompt: str) -> list[TranslatedSegment]: ...
    async def proofread(self, segments: list[Segment], glossary: Glossary) -> list[ProofreadSegment]: ...
    async def test(self) -> ProviderHealth: ...

class ProviderHealth(TypedDict):
    ok: bool
    latency_ms: int
    error: str | None
```

### 7.2 Built-in Providers

| Provider | Class | Base |
|---|---|---|
| OpenAI-compatible | `OpenAICompatible` | `openai` SDK |
| Anthropic | `AnthropicProvider` | `anthropic` SDK |
| DeepL | `DeepLProvider` | `deepl` SDK |

### 7.3 OpenAI-Compatible Endpoints

Any server implementing the OpenAI chat completions API works out of the box:

- OpenAI (`https://api.openai.com/v1`)
- DeepSeek (`https://api.deepseek.com`)
- Ollama (`http://localhost:11434/v1`)
- vLLM (`http://<host>:8000/v1`)
- DashScope / Qwen (`https://dashscope.aliyuncs.com/compatible-mode/v1`)

---

## 8. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-01 | **Resumable** — A interrupted translation can be resumed from the last checkpoint. |
| NFR-02 | **Privacy** — Local providers (Ollama) send zero bytes off-machine. |
| NFR-03 | **Cost visibility** — Token count and estimated cost shown before and after each run. |
| NFR-04 | **Structure preservation** — Non-translated elements (images, CSS, fonts, scripts) are byte-identical in output EPUB. |
| NFR-05 | **Graceful degradation** — Failed segments are skipped, not crashed; user can retry. |
| NFR-06 | **Idempotent** — Re-running `translate` on already-translated segments is a no-op. |
| NFR-07 | **Extensible** — New providers, new tags, new language pairs added via config or plugin. |

---

## 9. Testing Strategy

| Layer | Tools | What |
|---|---|---|
| Unit | `pytest` | Segmenter (fixture XHTML), tokenization, glossary matching, chunker |
| Integration | `pytest` + mock LLM | Full extract → translate → write-back on a fixture EPUB |
| Provider contract | `pytest` + VCR | Record fixture responses; replay for each adapter |
| Golden | `pytest` | Small zh chapter → verify output EPUB opens and structure is intact |
| Smoke | `pytest` | Package imports, version string, CLI entry point |

---

## 10. Success Criteria (MVP)

- [ ] A Chinese EPUB (≥ 50 k words) translates end-to-end with `swatl translate`.
- [ ] A proofreading pass (`swatl proofread`) improves readability (subjective, but CJK residue drops to 0).
- [ ] The output EPUB opens in ≥ 2 readers (Calibre, Apple Books, or browser).
- [ ] Image/CSS/fonts are byte-identical (verified by hash comparison).
- [ ] A run can be interrupted and resumed within < 5 min of lost work.
- [ ] `swatl audit` reports are actionable (flags → identifiable segments).
