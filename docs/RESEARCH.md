# Research Findings

> What we looked into, what we found, and why those findings drive the design.

---

## 1. Competitive Landscape — Existing AI EPUB Translators

| Project | Language | Approach | Bilingual | Glossary | Resume |
|---|---|---|---|---|---|
| [oomol-lab/epub-translator](https://github.com/oomol-lab/epub-translator) | Any (LLM) | Segment → LLM API; side-by-side | Yes | ❌ | ❌ |
| [haydentamch/epub-translator](https://github.com/haydentamch/epub-translator) | Any (LLM) | Segment → LLM API | Yes | ❌ | ❌ |
| [yihong0618/bilingual_book_maker](https://github.com/yihong0618/bilingual_book_maker) | zh→en (NMT) | DeepL / Google / Tencent / Codex | Yes | ❌ | Partial |
| [Lexora-Labs/lexora-ai](https://github.com/Lexora-Labs/lexora-ai) | Any (LLM) | Segment → LLM API | Yes | ❌ | ❌ |

**Gaps we identified:**

- No existing tool offers a dedicated **proofreading pass** (grammar + style in the target language).
- **Terminology consistency** via glossary injection into prompts is not standard.
- **Resumable per-segment checkpoints** are missing (a power failure or API outage can lose hours of work).
- No built-in **quality audit** (CJK-residue detection, omission heuristics, structure-preserving verification).
- **Provider flexibility** is limited: most lock you into one provider (OpenAI, DeepL, etc.).

---

## 2. EPUB Round-Trip Options

| Approach | Pros | Cons |
|---|---|---|
| **ebooklib** (Python, `pip install ebooklib`) | Mature; handles EPUB2 & EPUB3; metadata, spine, TOC, images, CSS | Regeneration can strip or reorder elements; known Unicode edge cases; EPUB3 nav quirks |
| **Raw `zipfile` + `lxml`** | Full byte-level control; only text nodes changed; untouched parts preserved | More boilerplate; must implement spine/TOC navigation manually |
| **epub.js** (JS, browser) | Great for rendering | Not suited for EPUB creation / round-tripping |

**Decision:** Use raw `zipfile` + `lxml` for the core read/write pipeline. ebooklib may be added later for convenience metadata queries. In-place text-node replacement guarantees structure is never re-generated, preserving images, CSS, fonts, and custom markup exactly as-is.

See also: [EbookLib docs](https://docs.sourcefabric.org/projects/ebooklib/en/latest/tutorial.html)

---

## 3. LLMs for Chinese → English Translation

### Cloud providers

| Provider | Model | zh → en quality | Notes |
|---|---|---|---|
| **Qwen3-MT** (Alibaba / DashScope) | Qwen3-MT | ★★★★★ — translation-specific, leads WMT24 zh-en BLEU, beats GPT-4.1-mini & Gemini 2.5 Flash | OpenAI-compatible API |
| **OpenAI** | GPT-4o | ★★★★☆ | Excellent nuance, higher cost |
| **Anthropic** | Claude 4 / Sonnet | ★★★★☆ | Strong tone control, long context |
| **DeepSeek** | deepseek-chat | ★★★★☆ | Very cost-effective, OpenAI-compatible, strong Chinese |

### Local models (via Ollama / vLLM)

| Model | Size | zh → en quality | Notes |
|---|---|---|---|
| **Qwen2.5-32B** | ~19 GB GGUF | ★★★★☆ — best local for Chinese web novels | Ollama tag `qwen2.5:32b` |
| **Qwen2.5-14B** | ~9 GB GGUF | ★★★☆☆ | Good trade-off for mid-range GPUs |
| **Qwen3 27B** | ~17 GB GGUF | ★★★★☆ | 2025 release, strong across tasks |
| **Gemma** | varies | ★★★☆☆ | Good but weaker at Chinese |

Source: [Qwen vs Claude for translation (2026)](https://www.machinetranslation.com/blog/claude-ai-vs-qwen), [Reddit r/LocalLLaMA](https://www.reddit.com/r/LocalLLaMA/comments/1k8601g/qwen_ai_my_most_used_llm/)

**Decision:** Ship with OpenAI-compatible core (covers OpenAI, DeepSeek, Ollama, DashScope) + Anthropic adapter. Recommend Qwen3-MT as default cloud, Qwen2.5-32B as default local.

---

## 4. AI Translation Best Practices (Glossary, Segmentation, Consistency)

- **Segment-level translation** (paragraph / `<p>` level) gives a better quality/cost/context trade-off than whole-chapter. Context is provided by injecting the previous N segments as background.
- **Glossary injection** — include a list of `{source_term → target_term}` entries in the system prompt so the model uses deterministic terminology.
- **Translation Memory (TM)** — cache segment hashes → translations. On a second run, reused segments get the cached translation instead of a new API call (cost savings + consistency).
- **Back-translation check** — translate target → source and flag segments where the back-translation diverges significantly (omission detection).
- **CJK residue detection** — if the English output still contains Chinese characters, flag it.
- **Low temperature** (`0.2–0.4`) for translation; higher (`0.6–0.8`) only for creative prose.
- **Structured output** (JSON) is preferred over raw text for reliable post-processing.

Sources: [Lokalise — AI translation with glossary](https://lokalise.com/blog/ai-translation-glossary/), [Crowdin — Best LLMs for translation](https://crowdin.com/blog/best-llms-for-translation)

---

## 5. Tooling & Stack

| Component | Choice | Rationale |
|---|---|---|
| Language | **Python 3.11+** | ebooklib is Python; all major AI EPUB translators are Python |
| Package mgr | **uv** | Fast, modern; available locally (0.10.4) |
| CLI | **typer** | Click-compatible, auto-docs, fast |
| HTTP / LLM SDK | **openai** (for OpenAI-compatible) + **httpx** (for Anthropic/DeepL) | Broadest provider coverage |
| HTML/XML parsing | **lxml** | Fast, reliable, XPath + CSS selectors |
| Config | **TOML** (`pydantic-settings`) | Clean, well-supported in Python |
| Linting / formatting | **ruff** | Single tool, fast |
| Testing | **pytest + pytest-asyncio** | Mature ecosystem |
| Progress display | **rich** | Beautiful CLI progress bars |

---

## 6. Key References

- [oomol-lab/epub-translator](https://github.com/oomol-lab/epub-translator) — bilingual LLM EPUB translator (Python)
- [aerkalov/ebooklib](https://github.com/aerkalov/ebooklib) — Python EPUB2/3 library
- [Qwen3-MT](https://www.alibabacloud.com/help/en/model-studio/what-is-qwen-llm) — Alibaba translation-specific model
- [Lokalise — AI translation with glossary](https://lokalise.com/blog/ai-translation-glossary/)
- [Crowdin — Best LLMs for translation](https://crowdin.com/blog/best-llms-for-translation)
- [Machinetranslation.com — Claude vs Qwen for translation](https://www.machinetranslation.com/blog/claude-ai-vs-qwen)
