"""Translation Memory — hash-based cache for previously translated segments."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from swatl.models import Segment

logger = logging.getLogger(__name__)


class TranslationMemory:
    """In-memory + on-disk translation memory using segment hash as key."""

    def __init__(self, memory_file: Path | None = None, max_entries: int = 100_000) -> None:
        self.max_entries = max_entries
        self._mem_cache: dict[str, str] = {}  # hash → translation
        if memory_file is not None:
            self._memory_file = Path(memory_file)
            self._load_disk_cache()
        else:
            self._memory_file = None

    def _hash(self, source_text: str) -> str:
        """Compute a short hash of the source text."""
        return hashlib.sha256(source_text.encode("utf-8")).hexdigest()[:16]

    def _load_disk_cache(self) -> None:
        """Load TM entries from disk JSON file."""
        if self._memory_file is None or not self._memory_file.exists():
            return
        try:
            with open(self._memory_file, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for entry in data.values():
                    if isinstance(entry, dict) and "hash" in entry and "translation" in entry:
                        self._mem_cache[entry["hash"]] = entry["translation"]
            logger.info("Loaded %d TM entries from disk", len(self._mem_cache))
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Failed to load TM from %s: %s", self._memory_file, e)

    def save_disk_cache(self) -> None:
        """Persist TM entries to disk."""
        if self._memory_file is None:
            return
        self._memory_file.parent.mkdir(parents=True, exist_ok=True)
        entries: dict[str, dict[str, Any]] = {}
        for h, t in self._mem_cache.items():
            entries[h] = {"hash": h, "translation": t}
        with open(self._memory_file, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)
        logger.info("Saved %d TM entries to disk", len(self._mem_cache))

    def lookup(self, segment: Segment) -> str | None:
        """Check if we have a cached translation for this segment's source text."""
        h = self._hash(segment.source_text)
        if h in self._mem_cache:
            logger.debug("TM hit for segment %s (hash=%s)", segment.id, h)
            return self._mem_cache[h]
        logger.debug("TM miss for segment %s (hash=%s)", segment.id, h)
        return None

    def add(self, segment: Segment) -> bool:
        """Add a translated segment. Returns True when a new entry was stored."""
        if not segment.translated:
            return False
        h = self._hash(segment.source_text)
        if h in self._mem_cache:
            return False
        self._mem_cache[h] = segment.translated
        # Evict oldest (FIFO by insertion order) until within capacity.
        while len(self._mem_cache) > self.max_entries:
            self._mem_cache.pop(next(iter(self._mem_cache)))
        return True

    def add_many(self, segments: list[Segment]) -> int:
        """Add multiple translated segments. Returns count of new entries."""
        return sum(1 for seg in segments if self.add(seg))

    def count(self) -> int:
        """Return number of entries in the memory."""
        return len(self._mem_cache)

    def get_hit_rate(self, segments: list[Segment]) -> float:
        """Estimate hit rate: fraction of segments that would match cached entries."""
        if not segments:
            return 0.0
        hits = sum(1 for seg in segments if self.lookup(seg) is not None)
        return hits / len(segments)
