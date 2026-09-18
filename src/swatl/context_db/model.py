"""Context DB — storage and management for manually curated context entries.

Separate from context/ (which handles the embedding/retrieval pipeline),
this module manages the user-facing CRUD operations for context entries
that can be imported, created, edited, and curated via the web UI.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field


class ContextEntry(BaseModel):
    """A single context entry for translation consistency."""

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    source_text: str
    translated_text: str | None = None
    entry_type: str = Field(default="manual")  # "segment" | "prefill" | "manual" | "curated"
    source_file: str | None = None  # filename or URL for prefill entries
    section: str | None = None  # paragraph/section reference
    tags: list[str] = Field(default_factory=list)  # user-defined categories
    similarity_score: float | None = None  # from last retrieval (analytics)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    def update_timestamp(self) -> None:
        self.updated_at = datetime.now(UTC).isoformat()


class ContextImportChunk(BaseModel):
    """A chunk produced during import, awaiting user approval."""

    index: int
    text: str
    translation: str | None = None
    approved: bool = True
    merged_with_next: bool = False
    skipped: bool = False
