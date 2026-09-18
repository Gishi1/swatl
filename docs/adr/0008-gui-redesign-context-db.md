# ADR-0008 — Web GUI Redesign and Context Database Management

| Field        | Value                              |
|--------------|------------------------------------|
| Status       | Proposed                           |
| Date         | 2026-01-17                         |

## Context

The current web GUI (`src/swatl/web/ui.py`) is a single-file (~315 lines), inline-CSS/JS application that provides:

- A segment list with status badges and text preview
- A slide-in detail panel for editing individual segments
- A provider configuration modal
- Basic stats and filtering

This works for MVP but has several limitations for power users:

1. **No navigation structure** — no tabs, sidebar, or hierarchical view (book → chapter → segment)
2. **No context DB management** — users cannot prefill, edit, search, or delete context entries
3. **No glossary management UI** — glossary is managed via CLI commands only
4. **Single-file architecture** — difficult to extend with new features
5. **No keyboard shortcuts** — translation work is repetitive; keyboard navigation is essential
6. **No project/workspace concept** — only one state directory at a time

Industry-standard CAT tools (Trados, memoQ, Phrase TMS) and modern translation platforms (Lokalise, Crowdin) share common UI patterns:

- **Left sidebar** for project/navigator navigation
- **Three-pane editor** (source | target | suggestions/context)
- **Dedicated panels** for glossary, translation memory, and terminology
- **Keyboard-first interaction** (arrow keys to navigate, Enter to accept, shortcuts for actions)

## Decision

Redesign the web GUI with a **multi-panel layout** and add a **Context Database management tab** for prefilling, editing, and curating context entries.

### Design Principles

1. **Keyboard-first**: Arrow keys navigate segments, shortcuts execute common actions (Accept=Ctrl+Enter, Skip=Ctrl+Shift+Enter, Regenerate=R)
2. **Progressive disclosure**: Simple view for casual users, advanced panels for power users
3. **Context is a first-class citizen**: The Context tab is as prominent as the Segment Editor
4. **Prefill by import**: Users can populate the Context DB from text files, web pages, or manually
5. **Edit/delete/curate**: Every context entry is editable and deletable

### Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│  swatl  │  Segments  │  Context DB  │  Glossary  │  Settings  │  [▶ Run] │
├──────────┼─────────────────────────────┼─────────────────────────────────┤
│ NAV      │  SEGMENT EDITOR TAB         │  CONTEXT DB TAB                │
│ PANEL    │                             │                                │
│          │  ┌─ Source ───────────────┐  │  ┌─ Search & Filter ────────┐│
│ 📁 EPUB  │  │ 这个概念来自...         │  │  │ 🔍 [Search context...   ]││
│ 📑 Ch01  │  ├─ Target ─────────────┤  │  │ [All] [Translated] [Prefill]││
│ 📑 Ch02  │  │  This concept comes   │  │  ├─────────────────────────┤│
│ 📑 Ch03  │  │  from Einstein's...   │  │  │ [1] 这个概念来自...       ││
│ ...      │  ├─ Context Panel ──────┤  │  │      This concept comes   ││
│          │  │  Related:             │  │  │      from Einstein's...   ││
│ 📖 Prev:  │  │  [p-0012] 爱因斯坦   │  │  │      from Einstein's...   ││
│  ...     │  │  [p-0047] 爱因斯坦    │  │  ├─────────────────────────┤│
│ 📖 Next:  │  │  [p-0055] 相对论     │  │  │ [2] 提出这一理论        ││
│          │  ├─ Actions ────────────┤  │  │      Proposed this...     ││
│          │  │ [Accept] [Skip] [↻]  │  │  │      from Einstein...     ││
│          │  │ [Save] [Regen]       │  │  ├─────────────────────────┤│
│          │  └─────────────────────┘  │  │ [Add Entry] [Import] [🗑] ││
│          │                            │  └─────────────────────────┘│
│ ──────── │                            │                                │
│ CONTEXT  │  ┌─ Progress ───────────┐  │  ┌─ Import Source ────────────┐│
│ DB (142) │  │ ████████████░░ 78%   │  │  │ File upload / URL input    ││
│          │  │                      │  │  │                            ││
│ 📊 Stats │  ┌─ Quality ──────────┐  │  │  ┌─ Chunk Preview ─────────┐│
│          │  │ CJK: 0  Omission: 1│  │  │  │ Chunk 1: ...             ││
│          │  └────────────────────┘  │  │  │ Chunk 2: ...             ││
│          │                            │  │  │ Chunk 3: ...             ││
│          │                            │  │  └────────────────────────┘││
│          │                            │  │  Chunk size: [500] overlap ││
│          │                            │  │  [Embed & Add All]         ││
│          │                            │  └────────────────────────────┘│
└──────────┴─────────────────────────────┴────────────────────────────────┘
```

### Tabs (Navigation Bar)

| Tab | Purpose | Key Features |
|-----|---------|--------------|
| **Segments** | Primary translation review | Three-pane editor, keyboard nav, context panel |
| **Context DB** | Curate semantic context | Search, add, edit, delete, import entries |
| **Glossary** | Manage terminology | CRUD glossary entries, domain tags |
| **Settings** | Provider config, embedding settings | Model selection, API keys, chunking params |

### Context DB Tab — Full Feature List

#### 1. Search & Filter

```
┌─ Search & Filter ──────────────────────────────┐
│ 🔍  [Search context entries...]                 │
│ [All] [Translated] [Prefill] [Custom]          │
└────────────────────────────────────────────────┘
```

- **Search**: Full-text search across source_text, translated_text, and metadata
- **Filter by source type**:
  - `All` — everything
  - `Translated` — auto-generated from translation pass (from segment list)
  - `Prefill` — manually imported (files, URLs, manual entries)
  - `Custom` — user-edited entries not matching the above

#### 2. Entry List

Each context entry card shows:

```
┌─ Entry ─────────────────────────────────────────┐
│ #142  ·  p-0041  ·  text/ch02.xhtml             │
│ Source: 三体是一个宏大的概念。                    │
│ Target:  Three-Body is a grand concept.         │
│ Tags:  [novel] [sci-fi] [terminology]           │
│                                         [✎] [🗑] │
└─────────────────────────────────────────────────┘
```

- **Edit button (✎)**: Opens inline editor
- **Delete button (🗑)**: Removes entry with confirmation
- **Tags**: User-defined tags for categorization (free-text, persisted with entry)

#### 3. Manual Entry Creation

```
┌─ Add Context Entry ─────────────────────────────┐
│ Source text:  [_______________________________]  │
│ Translation:  [_______________________________]  │
│ Document:     [text/ch01.xhtml          ]        │
│ Anchor:       [.//p[3]                  ]        │
│ Tags:         [sci-fi, terminology, ...   ]      │
│                                         [Save]  │
└──────────────────────────────────────────────────┘
```

#### 4. Import from File

Users can upload one or more text files. The system:

1. **Reads the file** (supports .txt, .md, .xhtml, .html, .json, .csv)
2. **Chunks it** using configurable chunk size/overlap
3. **Displays chunk preview** — user can review, merge, split chunks
4. **Embeds chunks** — generates embeddings for each approved chunk
5. **Stores as prefill entries** — tagged with source filename and line/section reference

```
┌─ Import from File ──────────────────────────────┐
│ Source:  [📎 Choose file...] or [Paste URL...]   │
│                                                  │
│ Chunk size: [500]  Overlap: [100]               │
│                                                  │
│ Preview:                                        │
│ ┌──────────────────────────────────────────────┐│
│ │ Chunk 1 (42 chars):                         ││
│ │ "三体是刘慈欣创作的科幻小说..."              ││
│ │ [✓] [✎ Edit] [✂ Split] [✕ Skip]            ││
│ ├──────────────────────────────────────────────┤│
│ │ Chunk 2 (38 chars):                         ││
│ │ "这个概念在物理学中也有..."                  ││
│ │ [✓] [✎ Edit] [✂ Split] [✕ Skip]            ││
│ └──────────────────────────────────────────────┘│
│                                                  │
│ [Embed & Add All (3 chunks)]                    │
└──────────────────────────────────────────────────┘
```

**Supported input formats**:

| Format | Behavior |
|--------|----------|
| `.txt` | Plain text, chunk by character count |
| `.md` | Markdown, chunk by headers or character count |
| `.xhtml`/`.html` | Extract text nodes, chunk by paragraph |
| `.json` | Parse as array of `{source, target}` pairs (bilingual) |
| `.csv` | Two-column: source_text, translated_text |
| URL | Fetch page, extract text content, chunk like `.txt` |

#### 5. Import from Webpage

```
┌─ Import from Webpage ───────────────────────────┐
│ URL:  [https://example.com/article...]          │
│                                                  │
│ Extracted text (first 2000 chars):              │
│ ┌──────────────────────────────────────────────┐│
│ │ Article title: "Understanding Quantum..."    ││
│ │ Body text: Quantum computing uses...        ││
│ └──────────────────────────────────────────────┘│
│                                                  │
│ [Chunk & Preview] → [Embed & Add All]           │
└──────────────────────────────────────────────────┘
```

#### 6. Bulk Edit

Users can edit multiple entries at once via a table view:

```
┌─ Bulk Edit ─────────────────────────────────────┐
│ ☑  #142  这个概念来自...  │  This concept...   │ [✎] │
│ ☐  #143  爱因斯坦提出...   │  Einstein proposed...│ [✎] │
│ ☑  #145  量子纠缠是...    │  Quantum entanglement...│ [✎]│
└──────────────────────────────────────────────────┘
```

### API Endpoints (New)

```python
# Context DB CRUD
@app.get("/api/context/{state_dir}")           # List all context entries (paginated)
@app.get("/api/context/{state_dir}/search?q=..") # Search context entries
@app.post("/api/context/{state_dir}")          # Create a single context entry
@app.patch("/api/context/{state_dir}/{entry_id}") # Edit a context entry
@app.delete("/api/context/{state_dir}/{entry_id}") # Delete a context entry

# Import
@app.post("/api/context/{state_dir}/import/text") # Import raw text (chunked)
@app.post("/api/context/{state_dir}/import/url")  # Import from URL
@app.post("/api/context/{state_dir}/import/batch") # Import bilingual pairs (JSON/CSV)

# Stats
@app.get("/api/context/{state_dir}/stats")       # Entry count by type, total embeddings

# Prefill from segments
@app.post("/api/context/{state_dir}/prefill")    # Embed all translated segments into context DB
```

### Data Model

```python
@pydantic.dataclasses.dataclass
class ContextEntry:
    id: str  # UUID v4
    source_text: str  # text to embed
    translated_text: str | None  # optional target translation
    entry_type: str  # "segment" | "prefill" | "manual" | "curated"
    source_file: str | None  # filename or URL for prefill entries
    section: str | None  # paragraph/section reference
    tags: list[str] = Field(default_factory=list)  # user-defined categories
    similarity_score: float | None  # from last retrieval (for analytics)
    created_at: str
    updated_at: str
```

### Architecture Changes

#### New Files

```
src/swatl/
├── context/                     # Phase 6 embedding module (from ADR-0007)
│   ├── __init__.py
│   ├── embedder.py              # Wraps Ollama / OpenAI-compatible embeddings
│   ├── index.py                 # FAISS index management
│   ├── retriever.py             # retrieve + deduplicate + format
│   └── store.py                 # Persistence for index + metadata
│
├── context_db/                  # NEW — Context DB management (separate from context/)
│   ├── __init__.py
│   ├── model.py                 # ContextEntry Pydantic model
│   ├── store.py                 # JSON/JSONL store for context entries
│   └── importer.py              # File/URL/text import and chunking logic
│
└── web/
    ├── ui.py                    # REFACTORED — new layout, tab navigation
    ├── app.py                   # NEW API endpoints for context DB + import
    └── components/              # NEW — reusable HTML component snippets
        ├── nav.html
        ├── segment_editor.html
        ├── context_db.html
        └── glossary.html
```

#### Refactored `ui.py`

The current monolithic `html_page` string (315 lines) is split into:

- **Component templates**: Each panel (nav, segment editor, context DB, glossary) is its own HTML template string
- **Shared JS module**: Common utilities (toast, api, format)
- **Tab state management**: Active tab, panel rendering, keyboard shortcuts

**Technology**: Pure HTML/CSS/JS (no framework) to maintain simplicity and single-file deployability. CSS variables and BEM-like class naming for theming.

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `↑` / `↓` | Navigate between segments |
| `Enter` | Accept current segment |
| `Ctrl+Enter` | Save edit in detail panel |
| `Ctrl+Shift+Enter` | Skip current segment |
| `R` | Regenerate current segment |
| `Escape` | Close detail panel / modal |
| `Ctrl+F` | Focus search/filter |
| `Ctrl+Tab 1-4` | Switch tabs |
| `/` | Global search (all context entries) |

### Styling Direction

Dark theme (matching current) with refinements:
- **Typography**: Use system font stack, improve line-height and letter-spacing
- **Color system**: Define semantic colors (success, warning, error, info) as CSS variables
- **Spacing**: 4px grid system (4, 8, 12, 16, 24, 32, 48)
- **Border radius**: 6px for inputs, 8px for cards, 12px for modals
- **Shadows**: Subtle elevation for panels and overlays
- **Focus states**: Visible ring on all interactive elements for keyboard users

### Implementation Plan

| Phase | Task | Effort | Dependencies |
|-------|------|--------|-------------|
| **8.0** | Refactor `ui.py` — extract components, add tab navigation | 1–2 days | — |
| **8.1** | Add `context_db/` module — model, store, importer | 2 days | — |
| **8.2** | Add API endpoints for context DB CRUD + import | 1–2 days | 8.1 |
| **8.3** | Implement Context DB tab UI (search, list, edit, delete) | 2 days | 8.2 |
| **8.4** | Implement import flow (file upload, URL, chunk preview) | 2 days | 8.2, 8.3 |
| **8.5** | Implement keyboard shortcuts | 0.5–1 day | 8.0 |
| **8.6** | Prefill button — embed all translated segments into Context DB | 1 day | Phase 6 (context/) |
| **8.7** | Glossary management tab (CRUD UI) | 1–2 days | — |
| **8.8** | Settings tab — provider config, embedding model selection | 1 day | 8.0 |
| **8.9** | Tests for new API endpoints | 1 day | 8.2 |

**Total estimated effort: 12–17 days**

### Implementation Note — Superdesign for GUI Design

This project uses **Superdesign** (via the `superdesign` CLI) to generate and iterate the GUI designs on a visual canvas before implementation. The Superdesign tool provides:

- A visual infinite canvas for designing UI layouts
- Multiple leading design models for different design tasks
- Side-by-side comparison of design variants
- Design system extraction and reusable component creation

### Workflow

The GUI design follows this sequence:

#### Step 1 — Initialize Superdesign Context

Run `superdesign init` from the project root. This builds reusable UI context files in `.superdesign/init/`:

- `components.md` — existing UI components with full source code
- `layouts.md` — shared layout components (current inline CSS app)
- `routes.md` — current single-page route (`/`)
- `theme.md` — existing CSS variables and dark theme tokens
- `pages.md` — dependency tree of the current UI
- `extractable-components.md` — reusable UI component catalog

#### Step 2 — Design Draft

Use Superdesign to create a visual draft of the redesigned GUI. The prompt should reference:

- The full ADR-0008 specification (layout, tabs, panels, keyboard shortcuts)
- Wireframe diagrams from this document
- The existing dark theme (`--bg: #0f1117`, `--accent: #3b82f6`, etc.)
- Three-panel layout: nav | editor | context DB

Run `superdesign create-design-draft` with the ADR as the brief. Generate at least **two visual directions** (e.g., conservative refinement vs. modern redesign) for comparison.

#### Step 3 — Review and Select

Review generated drafts on the Superdesign canvas. Evaluate:
- Does the layout match the ADR's multi-panel design?
- Is the Context DB tab clearly usable?
- Does the import flow UI look intuitive?
- Does the dark theme feel polished and professional?

Select one direction as baseline, or merge elements from both.

#### Step 4 — Iterate

Use `superdesign iterate-design-draft` to refine the selected design:
- Fix spacing, typography, color issues
- Adjust panel sizes, add missing elements
- Refine the import flow and chunk preview UI
- Ensure keyboard navigation cues are visible

#### Step 5 — Implement

Only **after user approval of the design on the canvas** do you implement the actual HTML/CSS/JS code. The approved design serves as the pixel-perfect reference for implementation.

### Hard Gates

- **MUST** produce design on Superdesign canvas BEFORE implementing any code
- **MUST NOT** generate implementation code until user explicitly approves the design draft
- **MUST** save the approved draft's ID and reference it during implementation

### Model Selection

When choosing a Superdesign model:
- **UI layout & panels**: Use a model strong at dashboard/admin panel design
- **Dark theme polish**: Use a model with good dark UI aesthetics
- **Form/flow design**: For import flows and chunk previews, use a model good at data forms

See `list-models` to choose the best model for each design task.

### Superdesign Commands Reference

```bash
# Initialize context from existing codebase
npx @superdesign/cli@latest init

# Create design draft (after init is complete)
npx @superdesign/cli@latest create-design-draft --brief "ADR-0008 specification"

# Iterate on selected draft
npx @superdesign/cli@latest iterate-design-draft --draft <draft-id> --changes "refine spacing, add import flow"

# List models
npx @superdesign/cli@latest list-models

# Extract website reference (if using an existing design as inspiration)
npx @superdesign/cli@latest extract-website <url>
```

### References

- **Superdesign Skill**: provided by the DeepSeek Harness environment
- **SUPERDESIGN.md**: Core workflow, SOP routing, command contract
- **INIT.md**: Repository initialization for design context
- **RESUME.md**: Resume saved targets for incremental iteration
- **WEBSITE.md**: Extract design from reference URLs (e.g., Lokalise, Trados screenshots)

---

## Trade-offs

| Decision | Rationale | Trade-off |
|----------|-----------|-----------|
| **Pure HTML/CSS/JS (no framework)** | Zero build step, single-file deploy, easy to maintain | Less type safety, manual DOM manipulation |
| **Separate `context_db/` module** | Clear separation: `context/` for embedding/retrieval, `context_db/` for storage/management | Slightly more modules |
| **FAISS + JSONL for Context DB** | No server, no Docker, fits offline-first philosophy | No full-text search without custom implementation |
| **Chunk preview before embedding** | Prevents bad embeddings from polluting the index | Extra step for users; could auto-chunk |
| **URL import via server-side fetch** | Keeps everything local; no CORS issues | Server must handle HTTP requests; rate limits apply |

### Alternative Designs Considered

| Alternative | Why Not Chosen |
|-------------|----------------|
| **React/Vue SPA** | Adds build complexity (Vite/webpack) for a tool that doesn't need reactivity at that scale |
| **Streamlit/FastAPI + HTMX** | Simpler than React but adds dependency; HTMX is a good candidate for future refinement |
| **Electron desktop app** | Adds packaging burden; web GUI is already sufficient for local use |
| **Single monolithic HTML file** | Current approach doesn't scale; component extraction is necessary for maintainability |
| **Full-text search via SQLite FTS** | Could be added later; for MVP, Python-side text search is adequate |

### References

- **Trados Editor Layout**: Three-pane editor with source/target/suggestions. https://docs.rws.com/en-US/sdl-trados-studio-783545/editor-window-components-340451
- **Lokalise**: Modern translation management with glossary, TM, and context panels. https://lokalise.com/blog/best-cat-tools/
- **Langflow Knowledge Bases**: Chunk preview, source type filtering, embed-and-add workflow. https://docs.langflow.org/knowledge
- **Phrase TMS**: Segment status workflow with accept/skip/regenerate. https://community.translatorswb.org/t/translating-a-segment-in-phrase-tms/32298
