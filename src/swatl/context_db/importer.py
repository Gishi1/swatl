"""File, URL, and text import logic with chunking for ContextDB."""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass, field

from swatl.context_db.model import ContextEntry, ContextImportChunk

logger = logging.getLogger(__name__)


@dataclass
class ImportResult:
    """Result of an import operation."""

    entries_created: int = 0
    chunks_total: int = 0
    chunks_approved: int = 0
    chunks_skipped: int = 0
    errors: list[str] = field(default_factory=list)


def chunk_text(
    text: str,
    chunk_size: int = 500,
    overlap: int = 100,
) -> list[str]:
    """Split text into overlapping chunks by character count.

    ``chunk_size`` and ``overlap`` are normalised first: an overlap close to the
    chunk size would barely advance the window and turn a single paste into
    thousands of near-identical chunks, so overlap is capped at half the chunk
    size.
    """
    chunk_size = max(1, int(chunk_size))
    overlap = max(0, int(overlap))
    overlap = min(overlap, chunk_size // 2)

    chunks: list[str] = []
    start = 0
    text = text.strip()
    if not text:
        return chunks
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end]
        # Try to break at sentence boundary (only if there's more text ahead)
        if end < len(text):
            period = chunk.rfind(". ")
            if period > chunk_size * 0.5:
                end = start + period + 2
                chunk = text[start:end]
            else:
                newline = chunk.rfind("\n")
                if newline > chunk_size * 0.5:
                    end = start + newline + 1
                    chunk = text[start:end]
        chunks.append(chunk.strip())
        # Advance: next start is after current end minus overlap, always
        # moving forward by at least one character.
        next_start = end - overlap if end < len(text) else len(text)
        if next_start <= start:
            next_start = start + 1
        start = next_start
    return chunks


def extract_text_from_html(content: str) -> str:
    """Extract readable text from HTML/XHTML content (simple parser)."""
    # Remove scripts and styles
    content = re.sub(r"<script[^>]*>.*?</script>", "", content, flags=re.DOTALL | re.IGNORECASE)
    content = re.sub(r"<style[^>]*>.*?</style>", "", content, flags=re.DOTALL | re.IGNORECASE)
    # Remove tags
    text = re.sub(r"<[^>]+>", " ", content)
    # Decode HTML entities
    text = html.unescape(text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_json_entries(content: str) -> list[ContextEntry]:
    """Parse JSON as full context entries, preserving id/type/tags when present.

    Accepts either a swatl database export (objects with ``source_text``) or a
    plain bilingual list (objects with ``source``/``target``). Importing an
    exported database is therefore lossless and idempotent: entry ids are kept,
    and the store skips ids that already exist.
    """
    import json

    data = json.loads(content)
    if not isinstance(data, list):
        return []

    entries: list[ContextEntry] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if "source_text" in item:
            entries.append(ContextEntry(**item))
            continue
        source = str(item.get("source", item.get("source_text", "")))
        if not source:
            continue
        target = item.get("target", item.get("translated"))
        entries.append(
            ContextEntry(
                source_text=source,
                translated_text=str(target) if target else None,
                entry_type=str(item.get("entry_type", "prefill")),
                source_file=item.get("source_file"),
                section=item.get("section"),
                tags=[str(t) for t in item.get("tags", [])],
            )
        )
    return entries


def parse_json_bilingual(content: str) -> list[tuple[str, str]]:
    """Parse JSON content as a list of (source, target) pairs."""
    return [(e.source_text, e.translated_text or "") for e in parse_json_entries(content)]


def parse_csv_entries(content: str, delimiter: str = ",") -> list[ContextEntry]:
    """Parse CSV into context entries.

    Columns are ``source, target, entry_type, tags``; only the first two are
    required and tags are separated by ``|``. A leading header row is skipped.
    """
    import csv
    from io import StringIO

    reader = csv.reader(StringIO(content), delimiter=delimiter)
    entries: list[ContextEntry] = []
    for index, row in enumerate(reader):
        if not row or not row[0].strip():
            continue
        if index == 0 and row[0].strip().lower() in ("source", "source_text"):
            continue  # header
        source = row[0].strip()
        target = row[1].strip() if len(row) > 1 else ""
        entry_type = row[2].strip() if len(row) > 2 and row[2].strip() else "prefill"
        tags = [t.strip() for t in row[3].split("|") if t.strip()] if len(row) > 3 else []
        entries.append(
            ContextEntry(
                source_text=source,
                translated_text=target or None,
                entry_type=entry_type,
                tags=tags,
            )
        )
    return entries


def parse_csv_bilingual(content: str, delimiter: str = ",") -> list[tuple[str, str]]:
    """Parse CSV content as two-column bilingual data (source, target)."""
    return [(e.source_text, e.translated_text or "") for e in parse_csv_entries(content, delimiter)]


class ContextImporter:
    """Handles importing context entries from various sources."""

    def __init__(
        self,
        chunk_size: int = 500,
        overlap: int = 100,
    ) -> None:
        self.chunk_size = chunk_size
        self.overlap = overlap

    # These mirror the module-level helpers so callers holding a ContextImporter
    # (the web import endpoint, for instance) do not have to import both.
    def chunk_text(
        self,
        text: str,
        chunk_size: int | None = None,
        overlap: int | None = None,
    ) -> list[str]:
        """Chunk *text* using the importer's defaults unless overridden."""
        return chunk_text(
            text,
            chunk_size if chunk_size is not None else self.chunk_size,
            overlap if overlap is not None else self.overlap,
        )

    @staticmethod
    def extract_text_from_html(content: str) -> str:
        """Extract readable text from an HTML/XHTML document."""
        return extract_text_from_html(content)

    def import_text(
        self,
        text: str,
        source_name: str = "text",
        entry_type: str = "prefill",
    ) -> ImportResult:
        """Import plain text as chunked context entries."""
        chunks = chunk_text(text, self.chunk_size, self.overlap)
        entries: list[ContextEntry] = []
        for i, chunk in enumerate(chunks):
            entries.append(
                ContextEntry(
                    source_text=chunk,
                    entry_type=entry_type,
                    source_file=source_name,
                    section=f"chunk-{i + 1}",
                    tags=["imported", source_name],
                )
            )
        return ImportResult(
            entries_created=len(entries),
            chunks_total=len(entries),
            chunks_approved=len(entries),
        )

    def import_html(
        self,
        html_content: str,
        source_name: str = "page",
        entry_type: str = "prefill",
    ) -> ImportResult:
        """Import HTML content, extracting text and chunking."""
        text = extract_text_from_html(html_content)
        return self.import_text(text, source_name, entry_type)

    def import_json(
        self,
        json_content: str,
        source_name: str = "file.json",
    ) -> ImportResult:
        """Import JSON bilingual pairs as context entries."""
        pairs = parse_json_bilingual(json_content)
        entries: list[ContextEntry] = []
        for source, target in pairs:
            entries.append(
                ContextEntry(
                    source_text=source,
                    translated_text=target if target else None,
                    entry_type="prefill",
                    source_file=source_name,
                    tags=["imported", "json"],
                )
            )
        return ImportResult(
            entries_created=len(entries),
            chunks_total=len(entries),
            chunks_approved=len(entries),
        )

    def import_csv(
        self,
        csv_content: str,
        source_name: str = "file.csv",
        delimiter: str = ",",
    ) -> ImportResult:
        """Import CSV bilingual pairs as context entries."""
        pairs = parse_csv_bilingual(csv_content, delimiter)
        entries: list[ContextEntry] = []
        for source, target in pairs:
            entries.append(
                ContextEntry(
                    source_text=source,
                    translated_text=target if target else None,
                    entry_type="prefill",
                    source_file=source_name,
                    tags=["imported", "csv"],
                )
            )
        return ImportResult(
            entries_created=len(entries),
            chunks_total=len(entries),
            chunks_approved=len(entries),
        )

    def preview_chunks(
        self,
        text: str,
        chunk_size: int | None = None,
        overlap: int | None = None,
    ) -> list[ContextImportChunk]:
        """Preview how text would be chunked without committing."""
        cs = chunk_size or self.chunk_size
        ov = overlap or self.overlap
        chunks = chunk_text(text, cs, ov)
        return [
            ContextImportChunk(index=i, text=chunk, approved=True) for i, chunk in enumerate(chunks)
        ]

    @staticmethod
    def detect_format(content: str, filename: str | None = None) -> str:
        """Auto-detect the format of imported content.

        Returns: "json", "csv", "html", "xhtml", or "text"
        """
        filename = (filename or "").lower()
        if filename.endswith((".json",)):
            return "json"
        if filename.endswith((".csv",)):
            return "csv"
        if filename.endswith((".xhtml", ".html", ".htm")):
            return "html"
        # Try to detect by content
        content_stripped = content.strip()
        if content_stripped.startswith(("{", "[")):
            return "json"
        if "<html" in content_stripped.lower() or "<!doctype" in content_stripped.lower():
            return "html"
        return "text"
