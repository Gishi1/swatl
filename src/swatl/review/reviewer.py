"""Interactive review engine for segment-by-segment translation review."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from swatl.audit.auditor import audit_segments
from swatl.glossary import Glossary
from swatl.models import Segment, SegmentStatus
from swatl.state.store import SegmentStore

logger = logging.getLogger(__name__)


@dataclass
class ReviewItem:
    """A single segment presented for review with its issues."""

    segment: Segment
    issues: list[dict] = field(default_factory=list)


@dataclass
class ReviewResult:
    """Outcome of a single review action."""

    segment_id: str
    action: str  # "accept", "edit", "regenerate", "skip", "done"
    new_translated: str | None = None  # if "edit"
    notes: str = ""


@dataclass
class ReviewSession:
    """Manages an interactive review session."""

    store: SegmentStore
    glossary: Glossary | None = None
    results: list[ReviewResult] = field(default_factory=list)
    review_items: list[ReviewItem] = field(default_factory=list)
    current_index: int = 0
    total: int = 0

    def load_segments(self) -> None:
        """Load every segment that has a translation and audit them.

        Proofread segments are included: the documented workflow runs
        ``proofread`` before ``review``, and filtering to ``translated`` only
        made the review step a no-op for proofread books.
        """
        reviewable = {SegmentStatus.TRANSLATED, SegmentStatus.PROOFREAD, SegmentStatus.EDITED}
        segments = [
            s
            for s in self.store.load_segments().values()
            if s.translated and s.status in reviewable
        ]
        if not segments:
            return
        segments.sort(key=lambda s: s.id)
        report = audit_segments(segments, self.glossary)
        # Build a per-segment issues lookup from the flat issue list
        issues_by_seg: dict[str, list[dict]] = {}
        for issue in report.issues:
            issues_by_seg.setdefault(issue.segment_id, []).append(
                {
                    "type": issue.type,
                    "severity": issue.severity,
                    "detail": issue.detail,
                    "description": f"[{issue.severity}] {issue.type}: {issue.detail}",
                }
            )
        self.review_items = [
            ReviewItem(segment=seg, issues=issues_by_seg.get(seg.id, [])) for seg in segments
        ]
        self.total = len(self.review_items)

    def current(self) -> ReviewItem | None:
        if self.current_index < 0 or self.current_index >= self.total:
            return None
        return self.review_items[self.current_index]

    def next_item(self) -> ReviewItem | None:
        self.current_index += 1
        return self.current()

    def prev_item(self) -> ReviewItem | None:
        self.current_index = max(0, self.current_index - 1)
        return self.current()

    def accept(self) -> ReviewResult:
        """Accept the current segment as-is."""
        item = self.current()
        if item is None:
            raise RuntimeError("No segment to accept")
        seg = item.segment
        seg.status = SegmentStatus.PROOFREAD
        self.store.append_segment(seg)
        result = ReviewResult(
            segment_id=seg.id,
            action="accept",
            notes=f"Accepted as-is (status={seg.status})",
        )
        self.results.append(result)
        return result

    def edit(self, new_text: str) -> ReviewResult:
        """Edit the current segment's translation."""
        item = self.current()
        if item is None:
            raise RuntimeError("No segment to edit")
        seg = item.segment
        seg.translated = new_text
        seg.status = SegmentStatus.EDITED
        self.store.append_segment(seg)
        result = ReviewResult(
            segment_id=seg.id,
            action="edit",
            new_translated=new_text,
            notes=f"Edited to {len(new_text)} chars (status={seg.status})",
        )
        self.results.append(result)
        return result

    def skip(self) -> ReviewResult:
        """Skip the current segment (leave translation unchanged)."""
        item = self.current()
        if item is None:
            raise RuntimeError("No segment to skip")
        seg = item.segment
        seg.status = SegmentStatus.SKIPPED
        self.store.append_segment(seg)
        result = ReviewResult(
            segment_id=seg.id,
            action="skip",
            notes=f"Skipped (status={seg.status})",
        )
        self.results.append(result)
        return result

    def regenerate(self) -> ReviewResult:
        """Regenerate translation with an empty target to prompt re-translation.
        In practice this marks it as pending so it can be re-translated."""
        item = self.current()
        if item is None:
            raise RuntimeError("No segment to regenerate")
        seg = item.segment
        seg.translated = None
        seg.status = SegmentStatus.PENDING
        seg.glossary_hits = []
        self.store.append_segment(seg)
        result = ReviewResult(
            segment_id=seg.id,
            action="regenerate",
            new_translated=None,
            notes="Marked for re-translation",
        )
        self.results.append(result)
        return result

    def done(self) -> list[ReviewResult]:
        """End the session, saving any remaining segments."""
        # Save run metadata update
        run = self.store.load_run()
        if run:
            run.updated_at = run.updated_at  # no-op, triggers save
            run.stages_completed = list(set(run.stages_completed) | {"review"})
            self.store.save_run(run)
        return self.results

    def summary(self) -> str:
        """Return a text summary of the session results."""
        if not self.results:
            return "No review actions taken."
        actions: dict[str, int] = {}
        for r in self.results:
            actions[r.action] = actions.get(r.action, 0) + 1
        lines = [f"Review session complete: {self.total} segments reviewed"]
        for action, count in sorted(actions.items()):
            lines.append(f"  {action}: {count}")
        return "\n".join(lines)
