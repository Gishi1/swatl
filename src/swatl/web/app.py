"""FastAPI app: API endpoints for the swatl web GUI."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from swatl.context_db.importer import ContextImporter, parse_csv_bilingual, parse_json_bilingual
from swatl.context_db.model import ContextEntry
from swatl.context_db.store import ContextEntryStore
from swatl.models import GlossaryEntry, SegmentStatus
from swatl.state import SegmentStore
from swatl.web.ui import html_page

app = FastAPI(title="swatl", version="0.1.0")


def _expand(state_dir: str) -> str:
    """Expand ``~`` and normalise a user-supplied state directory path."""
    return str(Path(state_dir).expanduser()) if state_dir else state_dir


def _read_store(state_dir: str) -> SegmentStore:
    """A SegmentStore that never creates directories (for GET endpoints)."""
    return SegmentStore(_expand(state_dir), create=False)


def _read_context_store(state_dir: str) -> ContextEntryStore:
    """A ContextEntryStore that never creates directories (for GET endpoints)."""
    return ContextEntryStore(_expand(state_dir), create=False)


# ---- Request/Response models ----


class ProviderConfigReq(BaseModel):
    name: str
    base_url: str
    model: str
    api_key_env: str


class SegmentUpdateReq(BaseModel):
    translated: str | None = None
    status: str | None = None


class ContextEntryReq(BaseModel):
    source_text: str
    translated_text: str | None = None
    entry_type: str = "manual"
    source_file: str | None = None
    section: str | None = None
    tags: list[str] = []


class ContextEditReq(BaseModel):
    source_text: str | None = None
    translated_text: str | None = None
    entry_type: str | None = None
    source_file: str | None = None
    section: str | None = None
    tags: list[str] | None = None


# ---- API endpoints ----


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the web GUI."""
    return html_page


@app.get("/api/run")
async def get_run(state_dir: str):
    """Get run metadata for a state directory."""
    store = _read_store(state_dir)
    run = store.load_run()
    if not run:
        raise HTTPException(status_code=404, detail="No run metadata found")
    return run.to_dict()


@app.get("/api/segments")
async def get_segments(
    state_dir: str,
    status: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 100,
):
    """Get segments with optional status/text filter and pagination.

    ``state_dir`` is a query parameter (not a path segment) so that nested and
    absolute state directories — e.g. ``./state`` or ``~/swatl-state`` — work.
    """
    try:
        status_enum = SegmentStatus(status) if status else None
    except ValueError as e:
        valid = ", ".join(s.value for s in SegmentStatus)
        raise HTTPException(
            status_code=400, detail=f"Unknown status '{status}'. Valid: {valid}"
        ) from e

    page = max(1, page)
    page_size = min(max(1, page_size), 1000)

    store = _read_store(state_dir)
    segments = list(store.load_segments().values())

    if status_enum is not None:
        segments = [s for s in segments if s.status == status_enum]

    if q:
        needle = q.strip().lower()
        if needle:
            segments = [
                s
                for s in segments
                if needle in s.id.lower()
                or needle in (s.source_text or "").lower()
                or needle in (s.translated or "").lower()
            ]

    segments.sort(key=lambda s: s.id)

    total = len(segments)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "segments": [s.model_dump(mode="json") for s in segments[start:end]],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
        "state_dir_exists": store.exists(),
    }


@app.get("/api/stats")
async def get_stats(state_dir: str):
    """Get segment counts by status."""
    store = _read_store(state_dir)
    counts = store.status_counts()
    return {"total": store.total_count(), "by_status": counts, "state_dir_exists": store.exists()}


@app.get("/api/segment/{segment_id}")
async def get_segment(segment_id: str, state_dir: str):
    """Get a single segment by id."""
    store = _read_store(state_dir)
    seg = store.get_segment(segment_id)
    if seg is None:
        raise HTTPException(status_code=404, detail=f"Segment {segment_id} not found")
    return seg.model_dump(mode="json")


@app.patch("/api/segment/{segment_id}")
async def update_segment(
    segment_id: str,
    body: SegmentUpdateReq,
    state_dir: str,
):
    """Update a segment's translation or status."""
    store = SegmentStore(_expand(state_dir))
    seg = store.get_segment(segment_id)
    if seg is None:
        raise HTTPException(status_code=404, detail=f"Segment {segment_id} not found")
    if body.translated is not None:
        seg.translated = body.translated
    if body.status is not None:
        try:
            seg.status = SegmentStatus(body.status)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Unknown status '{body.status}'") from e
    store.append_segment(seg)
    return {"ok": True, "segment": seg.model_dump(mode="json")}


@app.post("/api/accept/{segment_id}")
async def accept_segment(
    segment_id: str,
    state_dir: str,
):
    """Accept a segment (mark as proofread)."""
    store = SegmentStore(_expand(state_dir))
    seg = store.get_segment(segment_id)
    if seg is None:
        raise HTTPException(status_code=404, detail=f"Segment {segment_id} not found")
    seg.status = SegmentStatus.PROOFREAD
    store.append_segment(seg)
    return {"ok": True, "status": "proofread"}


@app.post("/api/skip/{segment_id}")
async def skip_segment(
    segment_id: str,
    state_dir: str,
):
    """Skip a segment."""
    store = SegmentStore(_expand(state_dir))
    seg = store.get_segment(segment_id)
    if seg is None:
        raise HTTPException(status_code=404, detail=f"Segment {segment_id} not found")
    seg.status = SegmentStatus.SKIPPED
    store.append_segment(seg)
    return {"ok": True, "status": "skipped"}


@app.post("/api/regenerate/{segment_id}")
async def regenerate_segment(
    segment_id: str,
    state_dir: str,
):
    """Queue a segment for regeneration on the next translate run."""
    store = SegmentStore(_expand(state_dir))
    seg = store.get_segment(segment_id)
    if seg is None:
        raise HTTPException(status_code=404, detail=f"Segment {segment_id} not found")
    seg.status = SegmentStatus.PENDING
    seg.translated = None
    store.append_segment(seg)
    return {"ok": True, "message": "Segment queued for regeneration"}


@app.get("/api/config")
async def list_providers():
    """List configured providers."""
    from swatl.config import load_providers

    configs = load_providers()
    return [{"name": k, "model": v.model, "base_url": v.base_url} for k, v in configs.items()]


@app.post("/api/config")
async def add_provider(cfg: ProviderConfigReq):
    """Add a provider config (writes to environment-based config)."""
    from swatl.config import save_provider
    from swatl.models import ProviderConfig

    provider = ProviderConfig(
        type="openai-compatible",
        base_url=cfg.base_url,
        model=cfg.model,
        api_key_env=cfg.api_key_env,
    )
    save_provider(cfg.name, provider)
    return {"ok": True, "name": cfg.name}


# ============================================================
# Glossary CRUD endpoints
# ============================================================


class GlossaryTermReq(BaseModel):
    source: str
    target: str
    domain: str = ""


@app.get("/api/glossary")
async def list_glossary(state_dir: str):
    """Load glossary from state directory."""
    from pathlib import Path

    from swatl.glossary import load_glossary

    glossary_path = Path(_expand(state_dir)) / "glossary.toml"
    try:
        glossary = load_glossary(glossary_path)
        return {
            "name": glossary.name,
            "pair": glossary.pair,
            "entries": [e.model_dump() for e in glossary.entries],
        }
    except FileNotFoundError:
        return {"name": "", "pair": ["zh", "en"], "entries": []}


@app.post("/api/glossary")
async def add_glossary_term(state_dir: str, term: GlossaryTermReq):
    """Add a term to the glossary file."""
    from pathlib import Path

    from swatl.glossary import load_glossary, save_glossary

    glossary_path = Path(_expand(state_dir)) / "glossary.toml"
    try:
        glossary = load_glossary(glossary_path)
    except FileNotFoundError:
        from swatl.glossary import create_default_glossary

        glossary = create_default_glossary()
    glossary.entries.append(
        GlossaryEntry(source=term.source, target=term.target, domain=term.domain)
    )
    save_glossary(glossary, glossary_path)
    return {"ok": True, "entries": len(glossary.entries)}


@app.delete("/api/glossary/{index}")
async def delete_glossary_term(index: int, state_dir: str):
    """Remove a term from the glossary by index."""
    from pathlib import Path

    from swatl.glossary import load_glossary, save_glossary

    glossary_path = Path(_expand(state_dir)) / "glossary.toml"
    try:
        glossary = load_glossary(glossary_path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="Glossary not found") from e
    if index < 0 or index >= len(glossary.entries):
        raise HTTPException(status_code=404, detail="Term index out of range")
    glossary.entries.pop(index)
    save_glossary(glossary, glossary_path)
    return {"ok": True, "entries": len(glossary.entries)}


# ============================================================
# Context DB CRUD endpoints
# ============================================================


@app.get("/api/context")
async def list_context_entries(state_dir: str, entry_type: str | None = None):
    """List all context entries for a state directory, optionally filtered by type."""
    store = _read_context_store(state_dir)
    entries = list(store.iter_entries())
    if entry_type:
        entries = [e for e in entries if e.entry_type == entry_type]
    return [e.model_dump() for e in entries]


@app.post("/api/context")
async def create_context_entry(state_dir: str, entry: ContextEntryReq):
    """Create a single context entry."""
    store = ContextEntryStore(_expand(state_dir))
    ctx_entry = ContextEntry(
        source_text=entry.source_text,
        translated_text=entry.translated_text,
        entry_type=entry.entry_type,
        source_file=entry.source_file,
        section=entry.section,
        tags=entry.tags,
    )
    store.create(ctx_entry)
    return {"ok": True, "entry": ctx_entry.model_dump()}


@app.patch("/api/context/{entry_id}")
async def update_context_entry(
    entry_id: str,
    state_dir: str,
    body: ContextEditReq,
):
    """Edit a context entry (partial update — only supplied fields change)."""
    store = ContextEntryStore(_expand(state_dir))
    result = store.update(entry_id, **body.model_dump(exclude_unset=True))
    if result is None:
        raise HTTPException(status_code=404, detail=f"Context entry {entry_id} not found")
    return {"ok": True, "entry": result.model_dump(mode="json")}


@app.delete("/api/context/{entry_id}")
async def delete_context_entry(
    entry_id: str,
    state_dir: str,
):
    """Delete a context entry."""
    store = ContextEntryStore(_expand(state_dir))
    if not store.delete(entry_id):
        raise HTTPException(status_code=404, detail=f"Context entry {entry_id} not found")
    return {"ok": True}


@app.get("/api/context/search")
async def search_context_entries(
    state_dir: str,
    q: str,
    entry_type: str | None = None,
):
    """Search context entries by text or tags."""
    store = _read_context_store(state_dir)
    results = store.search(q, entry_type=entry_type)
    return [e.model_dump() for e in results]


@app.get("/api/context/stats")
async def context_stats(state_dir: str):
    """Get context entry statistics."""
    store = _read_context_store(state_dir)
    return store.stats()


@app.post("/api/context/import/text")
async def import_text(
    state_dir: str,
    text: str = Form(...),
    source_name: str = Form("text"),
    chunk_size: int = Form(500),
    overlap: int = Form(100),
):
    """Import raw text as chunked context entries."""
    store = ContextEntryStore(_expand(state_dir))
    # Re-chunk and create entries
    from swatl.context_db.importer import chunk_text

    chunks = chunk_text(text, chunk_size, overlap)
    entries = [
        ContextEntry(
            source_text=chunk,
            entry_type="prefill",
            source_file=source_name,
            section=f"chunk-{i + 1}",
            tags=["imported", source_name],
        )
        for i, chunk in enumerate(chunks)
    ]
    added = store.create_many(entries)
    return {"ok": True, "entries_created": added, "chunks_total": len(chunks)}


@app.post("/api/context/import/json")
async def import_json_entries(
    state_dir: str,
    content: str = Form(...),
    source_name: str = Form("import.json"),
):
    """Import JSON bilingual pairs as context entries."""
    store = ContextEntryStore(_expand(state_dir))
    pairs = parse_json_bilingual(content)
    entries = [
        ContextEntry(
            source_text=src,
            translated_text=tgt if tgt else None,
            entry_type="prefill",
            source_file=source_name,
            tags=["imported", "json"],
        )
        for src, tgt in pairs
    ]
    added = store.create_many(entries)
    return {"ok": True, "entries_created": added}


@app.post("/api/context/import/batch")
async def import_csv_entries(
    state_dir: str,
    content: str = Form(...),
    source_name: str = Form("import.csv"),
    delimiter: str = Form(","),
):
    """Import CSV bilingual pairs as context entries."""
    store = ContextEntryStore(_expand(state_dir))
    pairs = parse_csv_bilingual(content, delimiter)
    entries = [
        ContextEntry(
            source_text=src,
            translated_text=tgt if tgt else None,
            entry_type="prefill",
            source_file=source_name,
            tags=["imported", "csv"],
        )
        for src, tgt in pairs
    ]
    added = store.create_many(entries)
    return {"ok": True, "entries_created": added}


@app.post("/api/context/prefill")
async def prefill_from_segments(state_dir: str):
    """Embed all translated segments into the Context DB.

    Copies all proofread/translated segments into the context entries store
    as prefill entries, so they can be curated and edited.
    """
    store = SegmentStore(_expand(state_dir))
    segments = store.load_segments()
    ctx_store = ContextEntryStore(_expand(state_dir))
    entries = []
    for seg in segments.values():
        if not seg.translated:
            continue
        entries.append(
            ContextEntry(
                source_text=seg.source_text,
                translated_text=seg.translated,
                entry_type="segment",
                source_file=seg.doc,
                section=seg.anchor,
                tags=["auto", seg.status],
            )
        )
    added = ctx_store.create_many(entries)
    return {"ok": True, "entries_created": added, "total_from_segments": len(entries)}


@app.post("/api/context/import/file")
async def import_file(
    state_dir: str,
    file: Annotated[UploadFile, File()],
    chunk_size: Annotated[int, Form()] = 500,
    overlap: Annotated[int, Form()] = 100,
):
    """Import an uploaded file as context entries."""
    content = await file.read()
    text = content.decode("utf-8", errors="replace")
    importer = ContextImporter(chunk_size=chunk_size, overlap=overlap)
    fmt = importer.detect_format(text, file.filename)
    store = ContextEntryStore(_expand(state_dir))

    if fmt == "json":
        pairs = parse_json_bilingual(text)
        entries = [
            ContextEntry(
                source_text=src,
                translated_text=tgt if tgt else None,
                entry_type="prefill",
                source_file=file.filename or "file.json",
                tags=["imported", "json"],
            )
            for src, tgt in pairs
        ]
    elif fmt == "csv":
        pairs = parse_csv_bilingual(text)
        entries = [
            ContextEntry(
                source_text=src,
                translated_text=tgt if tgt else None,
                entry_type="prefill",
                source_file=file.filename or "file.csv",
                tags=["imported", "csv"],
            )
            for src, tgt in pairs
        ]
    elif fmt in ("html", "xhtml"):
        text_extracted = importer.extract_text_from_html(text)
        chunks = importer.chunk_text(text_extracted, chunk_size, overlap)
        entries = [
            ContextEntry(
                source_text=chunk,
                entry_type="prefill",
                source_file=file.filename or "page.html",
                section=f"chunk-{i + 1}",
                tags=["imported", "html"],
            )
            for i, chunk in enumerate(chunks)
        ]
    else:
        chunks = importer.chunk_text(text, chunk_size, overlap)
        entries = [
            ContextEntry(
                source_text=chunk,
                entry_type="prefill",
                source_file=file.filename or "text",
                section=f"chunk-{i + 1}",
                tags=["imported", "text"],
            )
            for i, chunk in enumerate(chunks)
        ]

    added = store.create_many(entries)
    return {"ok": True, "format": fmt, "entries_created": added, "chunks_total": len(entries)}


# ---- CLI launcher ----


def run_server(host: str = "127.0.0.1", port: int = 8080) -> None:
    """Run the web server (convenience function for CLI)."""
    import uvicorn

    uvicorn.run("swatl.web:app", host=host, port=port, reload=False)
