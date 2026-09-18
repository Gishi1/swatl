"""JSONL segment store with last-write-wins semantics."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from swatl.models import RunMetadata, Segment


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
        """Yield segments from the JSONL file."""
        if not self.jsonl_path.exists():
            return
        with open(self.jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                yield Segment.model_validate(json.loads(line))

    def load_run(self) -> RunMetadata | None:
        """Load run metadata, or None if not present."""
        if not self._run_path.exists():
            return None
        with open(self._run_path, encoding="utf-8") as f:
            return RunMetadata.from_dict(json.load(f))

    def save_run(self, run: RunMetadata) -> None:
        """Persist run metadata."""
        run.updated_at = _now_iso()
        with open(self._run_path, "w", encoding="utf-8") as f:
            json.dump(run.to_dict(), f, indent=2, ensure_ascii=False)

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
