"""JSON/JSONL store for ContextDB entries."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path

from pydantic import ValidationError

from swatl.context_db.model import ContextEntry

logger = logging.getLogger(__name__)

# Default filename for the context entries store.
ENTRIES_FILE = "entries.json"


def _is_nullable(field) -> bool:
    """Whether a Pydantic field's annotation permits ``None``."""
    return type(None) in getattr(field.annotation, "__args__", ())


class ContextEntryStore:
    """Persists context entries to a JSON file with CRUD operations."""

    def __init__(self, state_dir: str | Path, create: bool = True) -> None:
        """Open the context store.

        ``create=False`` is for read-only callers: it never writes to disk, so
        listing entries in a non-existent state directory is side-effect free.
        """
        self.state_dir = Path(state_dir)
        self._create = create
        self.entries_file = self.state_dir / "context_db" / ENTRIES_FILE

    def exists(self) -> bool:
        """Whether the backing entries file exists."""
        return self.entries_file.exists()

    def _ensure_file(self) -> None:
        if self.entries_file.exists():
            return
        if not self._create:
            return
        self.entries_file.parent.mkdir(parents=True, exist_ok=True)
        self.entries_file.write_text("[]", encoding="utf-8")

    # ── Load ────────────────────────────────────────────────────────────

    def load_all(self) -> dict[str, ContextEntry]:
        """Load all context entries. Returns id → entry mapping.

        Entries that fail validation are repaired where possible (an older GUI
        bug could persist ``entry_type: null``) and otherwise skipped with an
        error log, so one bad row can never take down the whole Context DB.
        """
        self._ensure_file()
        entries: dict[str, ContextEntry] = {}
        if not self.entries_file.exists():
            return entries
        with open(self.entries_file, encoding="utf-8") as f:
            data = json.load(f)
        for item in data:
            if item.get("entry_type") is None:
                logger.warning("Repairing context entry %s with a null entry_type", item.get("id"))
                item["entry_type"] = "manual"
            try:
                entry = ContextEntry(**item)
            except ValidationError:
                logger.error("Skipping malformed context entry: %r", item, exc_info=True)
                continue
            entries[entry.id] = entry
        return entries

    def iter_entries(self) -> Iterator[ContextEntry]:
        """Yield all context entries."""
        yield from self.load_all().values()

    def get_entry(self, entry_id: str) -> ContextEntry | None:
        """Get a single entry by ID."""
        return self.load_all().get(entry_id)

    # ── Create / Update ─────────────────────────────────────────────────

    def create(self, entry: ContextEntry) -> ContextEntry:
        """Create a new entry and persist."""
        self._ensure_file()
        with open(self.entries_file, encoding="utf-8") as f:
            data = json.load(f)
        data.append(entry.model_dump())
        with open(self.entries_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("Created context entry %s", entry.id)
        return entry

    def update(self, entry_id: str, **fields) -> ContextEntry | None:
        """Update an entry by ID. Returns the updated entry or None.

        Fields that are not nullable in the model are ignored when passed as
        ``None`` so a partial update can never corrupt a required field.
        """
        entries = self.load_all()
        entry = entries.get(entry_id)
        if entry is None:
            return None
        model_fields = type(entry).model_fields
        for key, value in fields.items():
            field = model_fields.get(key)
            if field is None:
                continue
            if value is None and not _is_nullable(field):
                continue
            setattr(entry, key, value)
        entry.update_timestamp()
        # Write back
        with open(self.entries_file, encoding="utf-8") as f:
            data = json.load(f)
        for item in data:
            if item.get("id") == entry_id:
                item.update(entry.model_dump())
                break
        with open(self.entries_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return entry

    def delete(self, entry_id: str) -> bool:
        """Delete an entry by ID. Returns True if found and deleted."""
        entries = self.load_all()
        if entry_id not in entries:
            return False
        with open(self.entries_file, encoding="utf-8") as f:
            data = json.load(f)
        data = [item for item in data if item.get("id") != entry_id]
        with open(self.entries_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("Deleted context entry %s", entry_id)
        return True

    # ── Batch operations ────────────────────────────────────────────────

    def create_many(self, entries: list[ContextEntry]) -> int:
        """Create multiple entries. Returns the number added."""
        if not entries:
            return 0
        self._ensure_file()
        with open(self.entries_file, encoding="utf-8") as f:
            data = json.load(f)
        existing_ids = {item.get("id") for item in data}
        added = 0
        for entry in entries:
            if entry.id not in existing_ids:
                data.append(entry.model_dump())
                existing_ids.add(entry.id)
                added += 1
        with open(self.entries_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return added

    # ── Query / Filter ──────────────────────────────────────────────────

    def search(self, query: str, entry_type: str | None = None) -> list[ContextEntry]:
        """Search entries by text (case-insensitive substring match)."""
        q = query.lower()
        results = []
        for entry in self.iter_entries():
            if q in entry.source_text.lower():
                results.append(entry)
                continue
            if entry.translated_text and q in entry.translated_text.lower():
                results.append(entry)
                continue
            if any(q in tag.lower() for tag in entry.tags):
                results.append(entry)
        if entry_type:
            results = [e for e in results if e.entry_type == entry_type]
        return results

    def filter_by_type(self, entry_type: str) -> list[ContextEntry]:
        """Filter entries by type."""
        return [e for e in self.iter_entries() if e.entry_type == entry_type]

    def tags(self) -> list[str]:
        """Return all unique tags."""
        tag_set: set[str] = set()
        for entry in self.iter_entries():
            tag_set.update(entry.tags)
        return sorted(tag_set)

    # ── Stats ───────────────────────────────────────────────────────────

    def count(self) -> int:
        return sum(1 for _ in self.iter_entries())

    def stats(self) -> dict:
        counts: dict[str, int] = {}
        for entry in self.iter_entries():
            counts[entry.entry_type] = counts.get(entry.entry_type, 0) + 1
        return {
            "total": self.count(),
            "by_type": counts,
            "tags": self.tags(),
        }
