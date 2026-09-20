"""JSON/JSONL store for ContextDB entries."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from swatl.context_db.model import ContextEntry

logger = logging.getLogger(__name__)

# Default filename for the context entries store. Named databases live beside
# it as "<name>.json" so the default keeps working for existing state dirs.
ENTRIES_FILE = "entries.json"
DEFAULT_DB = "default"
DB_FILE_SUFFIX = ".json"

# Database names become file names, so they are deliberately restrictive.
_DB_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")

# Stems that already mean something inside the context_db directory: the default
# entries file, and the FAISS index plus its metadata written by
# swatl.context.index. A database named "entries" or "index" resolves to those
# exact files, so creating or deleting one would clobber the curated default
# database / corrupt the vector index.
RESERVED_DB_STEMS = frozenset({Path(ENTRIES_FILE).stem, DEFAULT_DB, "index"})


def validate_db_name(name: str) -> str:
    """Return *name* if it is a safe database name, else raise ``ValueError``."""
    if name == DEFAULT_DB:
        return name
    if not _DB_NAME_RE.fullmatch(name or ""):
        raise ValueError(
            f"Invalid context database name {name!r}: use letters, digits, '.', '_' or "
            "'-' (max 64 characters)"
        )
    if name.endswith(DB_FILE_SUFFIX) or ".." in name:
        raise ValueError(f"Invalid context database name {name!r}")
    # Compared case-insensitively: on a case-insensitive filesystem "Entries"
    # and "entries" are the same file.
    if name.lower() in RESERVED_DB_STEMS:
        raise ValueError(
            f"Invalid context database name {name!r}: reserved for the default "
            "database and the vector index"
        )
    return name


def context_db_dir(state_dir: str | Path) -> Path:
    """Directory holding the context databases for a state directory."""
    return Path(state_dir) / "context_db"


def database_path(state_dir: str | Path, name: str = DEFAULT_DB) -> Path:
    """Path of a named context database file."""
    validate_db_name(name)
    if name == DEFAULT_DB:
        return context_db_dir(state_dir) / ENTRIES_FILE
    return context_db_dir(state_dir) / f"{name}{DB_FILE_SUFFIX}"


def list_databases(state_dir: str | Path) -> list[dict]:
    """Describe every context database in *state_dir*.

    Returns a list of ``{"name", "entries", "exists"}`` dicts, default first
    and the rest alphabetically.
    """
    directory = context_db_dir(state_dir)
    names: list[str] = []
    if directory.is_dir():
        for path in sorted(directory.iterdir()):
            if path.name == ENTRIES_FILE:
                names.append(DEFAULT_DB)
            elif (
                path.suffix == DB_FILE_SUFFIX
                and _DB_NAME_RE.fullmatch(path.stem)
                and path.stem.lower() not in RESERVED_DB_STEMS
            ):
                names.append(path.stem)

    if DEFAULT_DB not in names:
        names.append(DEFAULT_DB)

    ordered = [DEFAULT_DB] + sorted(n for n in names if n != DEFAULT_DB)
    return [
        {
            "name": name,
            "entries": ContextEntryStore(state_dir, name=name, create=False).count(),
            "exists": database_path(state_dir, name).exists(),
        }
        for name in ordered
    ]


def create_database(state_dir: str | Path, name: str, copy_from: str | None = None) -> Path:
    """Create an empty (or copied) context database and return its path."""
    target = database_path(state_dir, name)
    if target.exists():
        raise FileExistsError(f"Context database '{name}' already exists")

    target.parent.mkdir(parents=True, exist_ok=True)
    if copy_from:
        source = database_path(state_dir, copy_from)
        if not source.exists():
            raise FileNotFoundError(f"Context database '{copy_from}' not found")
        shutil.copyfile(source, target)
    else:
        target.write_text("[]", encoding="utf-8")
    logger.debug("Created context database '%s'", name)
    return target


def delete_database(state_dir: str | Path, name: str) -> bool:
    """Delete a named context database. The default database is protected."""
    if name == DEFAULT_DB:
        raise ValueError("The default context database cannot be deleted")
    target = database_path(state_dir, name)
    if not target.exists():
        return False
    target.unlink()
    logger.debug("Deleted context database '%s'", name)
    return True


def _is_nullable(field) -> bool:
    """Whether a Pydantic field's annotation permits ``None``."""
    return type(None) in getattr(field.annotation, "__args__", ())


def _backup_path(path: Path) -> Path:
    """Path of the backup copy kept beside a context database."""
    return path.with_suffix(path.suffix + ".bak")


def _atomic_write_json(path: Path, data: list[dict[str, Any]]) -> None:
    """Write *data* to *path* without ever truncating the existing file.

    ``open(path, "w")`` empties the file before the new content is written, so a
    crash, a full disk or a second writer (the web server and the CLI both edit
    context databases) could leave a curated glossary unreadable. The new
    content goes to a temporary file in the same directory and is moved into
    place atomically, and the version being replaced is kept as ``<name>.bak``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            shutil.copyfile(path, _backup_path(path))
        except OSError:  # pragma: no cover - the backup is best effort
            logger.debug("Could not back up %s", path, exc_info=True)

    tmp_path = path.with_name(path.name + ".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except OSError:
        tmp_path.unlink(missing_ok=True)
        raise


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    """Read a JSON array, recovering from the backup when the file is corrupt.

    A missing file is an empty database. A damaged one is reported loudly rather
    than raising out of every read path, and the previous version is used when a
    backup exists.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError:
        logger.error("Could not read context database %s", path, exc_info=True)
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        backup = _backup_path(path)
        if not backup.exists():
            logger.error(
                "Context database %s is corrupt and has no backup; treating it as empty", path
            )
            return []
        logger.error("Context database %s is corrupt; recovering from %s", path, backup)
        try:
            data = json.loads(backup.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.error("Backup %s is unusable; treating the database as empty", backup)
            return []

    if not isinstance(data, list):
        logger.error("Context database %s does not contain a JSON array", path)
        return []
    return data


class ContextEntryStore:
    """Persists context entries to a JSON file with CRUD operations.

    Each state directory can hold several databases: ``default`` (the
    historical ``context_db/entries.json``) plus any number of named ones.
    """

    def __init__(self, state_dir: str | Path, name: str = DEFAULT_DB, create: bool = True) -> None:
        """Open the context store.

        ``create=False`` is for read-only callers: it never writes to disk, so
        listing entries in a non-existent state directory is side-effect free.
        """
        self.state_dir = Path(state_dir)
        self.name = validate_db_name(name)
        self._create = create
        self.entries_file = database_path(self.state_dir, self.name)

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
        data = _load_json_list(self.entries_file)
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
        data = _load_json_list(self.entries_file)
        data.append(entry.model_dump())
        _atomic_write_json(self.entries_file, data)
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
        data = _load_json_list(self.entries_file)
        for item in data:
            if item.get("id") == entry_id:
                item.update(entry.model_dump())
                break
        _atomic_write_json(self.entries_file, data)
        return entry

    def delete(self, entry_id: str) -> bool:
        """Delete an entry by ID. Returns True if found and deleted."""
        entries = self.load_all()
        if entry_id not in entries:
            return False
        data = _load_json_list(self.entries_file)
        data = [item for item in data if item.get("id") != entry_id]
        _atomic_write_json(self.entries_file, data)
        logger.info("Deleted context entry %s", entry_id)
        return True

    # ── Batch operations ────────────────────────────────────────────────

    def create_many(self, entries: list[ContextEntry]) -> int:
        """Create multiple entries. Returns the number added."""
        if not entries:
            return 0
        self._ensure_file()
        data = _load_json_list(self.entries_file)
        existing_ids = {item.get("id") for item in data}
        added = 0
        for entry in entries:
            if entry.id not in existing_ids:
                data.append(entry.model_dump())
                existing_ids.add(entry.id)
                added += 1
        _atomic_write_json(self.entries_file, data)
        return added

    # ── Import / export ─────────────────────────────────────────────────

    CSV_COLUMNS = ("source", "target", "entry_type", "tags")

    def export_json(self, indent: int = 2) -> str:
        """Serialise the whole database as JSON (round-trips via import)."""
        return json.dumps(
            [e.model_dump() for e in self.iter_entries()],
            ensure_ascii=False,
            indent=indent,
        )

    def export_csv(self) -> str:
        """Serialise the database as CSV with a header row.

        Tags are joined with ``|`` because the field is a list.
        """
        import csv
        from io import StringIO

        buffer = StringIO()
        writer = csv.writer(buffer)
        writer.writerow(self.CSV_COLUMNS)
        for entry in self.iter_entries():
            writer.writerow(
                [
                    entry.source_text,
                    entry.translated_text or "",
                    entry.entry_type,
                    "|".join(entry.tags),
                ]
            )
        return buffer.getvalue()

    def export(self, fmt: str = "json") -> str:
        """Serialise the database in *fmt* (``json`` or ``csv``)."""
        if fmt == "json":
            return self.export_json()
        if fmt == "csv":
            return self.export_csv()
        raise ValueError(f"Unsupported export format {fmt!r}: use 'json' or 'csv'")

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
