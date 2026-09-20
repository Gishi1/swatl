"""JSONL segment store with last-write-wins semantics."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from swatl.models import RunMetadata, Segment

logger = logging.getLogger(__name__)


class SegmentStore:
    """Append-only JSONL store for segments with last-write-wins on load."""

    def __init__(self, state_dir: str | Path, create: bool = True) -> None:
        """Open a store.

        ``create=False`` is for read-only callers (e.g. the web API): it never
        touches the filesystem, so browsing a mistyped state directory cannot
        litter the disk with empty folders.
        """
        self.state_dir = Path(state_dir)
        self._create = create
        if self._create:
            self.state_dir.mkdir(parents=True, exist_ok=True)
        self.jsonl_path = self.state_dir / "segments.jsonl"
        if self._create:
            self.jsonl_path.touch(exist_ok=True)
        self._run_path = self.state_dir / "run.json"
        self._local_cache: dict[str, dict] = {}  # id → last line (last-write-wins)

    # ── Load ────────────────────────────────────────────────────────────

    def exists(self) -> bool:
        """Whether the state directory exists on disk."""
        return self.state_dir.is_dir()

    def load_segments(self) -> dict[str, Segment]:
        """Load all segments from the JSONL file. Last-write-wins per id."""
        segments: dict[str, Segment] = {}
        for seg in self.iter_segments():
            segments[seg.id] = seg
        self._local_cache = {sid: seg.model_dump() for sid, seg in segments.items()}
        return segments

    def iter_segments(self) -> Iterator[Segment]:
        """Yield segments from the JSONL file.

        A segment that cannot be parsed is skipped with a warning. An append
        interrupted by a kill, a full disk or a crash leaves a half-written last
        line, and raising here used to make *every* read of the run fail — a
        run with thousands of good lines became unusable because of one. Losses
        are reported rather than hidden so the affected segments can be found.
        """
        if not self.jsonl_path.exists():
            return
        skipped = 0
        with open(self.jsonl_path, encoding="utf-8", errors="replace") as f:
            for line_number, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield Segment.model_validate(json.loads(line))
                except (json.JSONDecodeError, ValidationError, UnicodeDecodeError) as e:
                    skipped += 1
                    logger.warning(
                        "Skipping unreadable segment record at %s:%d (%s)",
                        self.jsonl_path.name,
                        line_number,
                        e,
                    )
        if skipped:
            logger.warning(
                "%d segment record(s) in %s could not be read and were skipped",
                skipped,
                self.jsonl_path.name,
            )

    def load_run(self) -> RunMetadata | None:
        """Load run metadata, or None if it is missing or unreadable."""
        if not self._run_path.exists():
            return None
        try:
            with open(self._run_path, encoding="utf-8") as f:
                return RunMetadata.from_dict(json.load(f))
        except (json.JSONDecodeError, ValidationError, OSError) as e:
            logger.warning("Could not read run metadata from %s: %s", self._run_path, e)
            return None

    def save_run(self, run: RunMetadata) -> None:
        """Persist run metadata."""
        run.updated_at = _now_iso()
        # Written to a temporary file and moved into place so an interrupted
        # write cannot leave a truncated (unreadable) run.json behind.
        fd, tmp_name = tempfile.mkstemp(dir=self._run_path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(run.to_dict(), f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, self._run_path)
        except OSError:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    # ── Append / Update ─────────────────────────────────────────────────

    def append_segment(self, segment: Segment) -> None:
        """Append (or overwrite) a single segment to the JSONL."""
        with open(self.jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(segment.model_dump(), ensure_ascii=False) + "\n")
        self._local_cache[segment.id] = segment.model_dump()

    def append_many(self, segments: list[Segment]) -> None:
        """Append a batch of segments."""
        if not segments:
            return
        with open(self.jsonl_path, "a", encoding="utf-8") as f:
            for seg in segments:
                f.write(json.dumps(seg.model_dump(), ensure_ascii=False) + "\n")
                self._local_cache[seg.id] = seg.model_dump()

    # ── Query helpers ────────────────────────────────────────────────────

    def get_segment(self, segment_id: str) -> Segment | None:
        """Get the latest version of a segment, or None."""
        data = self._local_cache.get(segment_id)
        if data is not None:
            return Segment.model_validate(data)
        # Fallback: refresh the last-write-wins snapshot and look up again
        return self.load_segments().get(segment_id)

    # NOTE: all query helpers below operate on the last-write-wins snapshot so
    # that re-runs, resumes and in-place edits never double-count a segment.

    def pending_segments(self) -> list[Segment]:
        """Return all pending segments (not yet translated or proofread)."""
        return [s for s in self.load_segments().values() if s.status == "pending"]

    def translated_segments(self) -> list[Segment]:
        """Return all translated but unproofread segments."""
        return [s for s in self.load_segments().values() if s.status in ("translated", "edited")]

    def completed_segments(self) -> list[Segment]:
        """Return all segments with a translated value (proofread or edited)."""
        return [
            s
            for s in self.load_segments().values()
            if s.status in ("proofread", "edited") and s.translated
        ]

    def failed_segments(self) -> list[Segment]:
        """Return segments in failed status."""
        return [s for s in self.load_segments().values() if s.status == "failed"]

    def total_count(self) -> int:
        """Number of unique segments (last-write-wins)."""
        return len(self.load_segments())

    def status_counts(self) -> dict[str, int]:
        """Count of unique segments per status (last-write-wins)."""
        counts: dict[str, int] = {}
        for seg in self.load_segments().values():
            counts[seg.status] = counts.get(seg.status, 0) + 1
        return counts


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
