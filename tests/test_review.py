"""Tests for the review module."""

from swatl.models import Segment, SegmentStatus
from swatl.review.reviewer import ReviewSession
from swatl.state.store import SegmentStore


class TestReviewSession:
    """Tests for the ReviewSession class."""

    def test_load_segments_populates_review_items(self, tmp_path):
        """Load segments should populate review_items."""
        store = SegmentStore(tmp_path)
        segments = [
            Segment(
                id="p-001",
                doc="text/ch01.xhtml",
                anchor=".//p[1]",
                tag="p",
                source_text="你好世界",
                translated="Hello World",
                status=SegmentStatus.TRANSLATED,
            ),
            Segment(
                id="p-002",
                doc="text/ch01.xhtml",
                anchor=".//p[2]",
                tag="p",
                source_text="你好",
                translated="Hi",
                status=SegmentStatus.EDITED,
            ),
        ]
        store.append_many(segments)

        session = ReviewSession(store=store)
        session.load_segments()

        assert session.total == 2  # both translated/edited segments
        assert len(session.review_items) == 2

    def test_load_segments_empty_when_no_translated(self, tmp_path):
        """No translated segments means empty review."""
        store = SegmentStore(tmp_path)
        segments = [
            Segment(
                id="p-001",
                doc="text/ch01.xhtml",
                anchor=".//p[1]",
                tag="p",
                source_text="你好",
                translated=None,
                status=SegmentStatus.PENDING,
            ),
        ]
        store.append_many(segments)

        session = ReviewSession(store=store)
        session.load_segments()

        assert session.total == 0
        assert session.review_items == []

    def test_accept(self, tmp_path):
        """Accepting a segment should save it with proofread status."""
        store = SegmentStore(tmp_path)
        seg = Segment(
            id="p-001",
            doc="text/ch01.xhtml",
            anchor=".//p[1]",
            tag="p",
            source_text="你好",
            translated="Hello",
            status=SegmentStatus.TRANSLATED,
        )
        store.append_many([seg])

        session = ReviewSession(store=store)
        session.load_segments()
        result = session.accept()

        assert result.action == "accept"
        assert result.segment_id == "p-001"
        loaded = store.get_segment("p-001")
        assert loaded is not None
        assert loaded.status == SegmentStatus.PROOFREAD

    def test_edit(self, tmp_path):
        """Editing a segment should save with new text and edited status."""
        store = SegmentStore(tmp_path)
        seg = Segment(
            id="p-001",
            doc="text/ch01.xhtml",
            anchor=".//p[1]",
            tag="p",
            source_text="你好",
            translated="Hello",
            status=SegmentStatus.TRANSLATED,
        )
        store.append_many([seg])

        session = ReviewSession(store=store)
        session.load_segments()
        result = session.edit("你好世界")

        assert result.action == "edit"
        assert result.new_translated == "你好世界"
        loaded = store.get_segment("p-001")
        assert loaded is not None
        assert loaded.status == SegmentStatus.EDITED
        assert loaded.translated == "你好世界"

    def test_skip(self, tmp_path):
        """Skipping a segment should save with skipped status."""
        store = SegmentStore(tmp_path)
        seg = Segment(
            id="p-001",
            doc="text/ch01.xhtml",
            anchor=".//p[1]",
            tag="p",
            source_text="你好",
            translated="Hello",
            status=SegmentStatus.TRANSLATED,
        )
        store.append_many([seg])

        session = ReviewSession(store=store)
        session.load_segments()
        result = session.skip()

        assert result.action == "skip"
        loaded = store.get_segment("p-001")
        assert loaded is not None
        assert loaded.status == SegmentStatus.SKIPPED

    def test_regenerate(self, tmp_path):
        """Regenerating a segment should clear translation and mark pending."""
        store = SegmentStore(tmp_path)
        seg = Segment(
            id="p-001",
            doc="text/ch01.xhtml",
            anchor=".//p[1]",
            tag="p",
            source_text="你好",
            translated="Hello",
            status=SegmentStatus.TRANSLATED,
        )
        store.append_many([seg])

        session = ReviewSession(store=store)
        session.load_segments()
        result = session.regenerate()

        assert result.action == "regenerate"
        loaded = store.get_segment("p-001")
        assert loaded is not None
        assert loaded.status == SegmentStatus.PENDING
        assert loaded.translated is None

    def test_next_prev_navigation(self, tmp_path):
        """Navigation should move between review items."""
        store = SegmentStore(tmp_path)
        segments = [
            Segment(
                id=f"p-{i:03d}",
                doc="text/ch01.xhtml",
                anchor=".//p[1]",
                tag="p",
                source_text=f"你好{i}",
                translated=f"Hello{i}",
                status=SegmentStatus.TRANSLATED,
            )
            for i in range(1, 4)
        ]
        store.append_many(segments)

        session = ReviewSession(store=store)
        session.load_segments()

        assert session.total == 3
        assert session.current().segment.id == "p-001"

        session.next_item()
        assert session.current().segment.id == "p-002"

        session.next_item()
        assert session.current().segment.id == "p-003"

        session.prev_item()
        assert session.current().segment.id == "p-002"

    def test_done_saves_run_metadata(self, tmp_path):
        """Ending session should save run with review stage."""
        store = SegmentStore(tmp_path)
        from swatl.models import RunMetadata

        run = RunMetadata(
            book_title="Test Book",
            book_lang="zh",
            stages_completed=["translate"],
            total_segments=1,
        )
        store.save_run(run)

        seg = Segment(
            id="p-001",
            doc="text/ch01.xhtml",
            anchor=".//p[1]",
            tag="p",
            source_text="你好",
            translated="Hello",
            status=SegmentStatus.TRANSLATED,
        )
        store.append_many([seg])

        session = ReviewSession(store=store)
        session.load_segments()
        session.accept()
        session.done()

        loaded_run = store.load_run()
        assert loaded_run is not None
        assert "review" in loaded_run.stages_completed

    def test_summary(self, tmp_path):
        """Summary should show action counts."""
        store = SegmentStore(tmp_path)
        seg = Segment(
            id="p-001",
            doc="text/ch01.xhtml",
            anchor=".//p[1]",
            tag="p",
            source_text="你好",
            translated="Hello",
            status=SegmentStatus.TRANSLATED,
        )
        store.append_many([seg])

        session = ReviewSession(store=store)
        session.load_segments()
        session.accept()
        summary = session.summary()

        assert "1 segments reviewed" in summary
        assert "accept: 1" in summary

    def test_current_returns_none_out_of_range(self, tmp_path):
        """current() should return None when index is out of range."""
        store = SegmentStore(tmp_path)
        session = ReviewSession(store=store)
        assert session.current() is None

    def test_accept_no_segment_raises(self, tmp_path):
        """accept() on empty session should raise RuntimeError."""
        store = SegmentStore(tmp_path)
        session = ReviewSession(store=store)
        session.load_segments()
        try:
            session.accept()
            raise AssertionError("Should have raised")
        except RuntimeError:
            pass


def test_review_includes_proofread_segments(tmp_path):
    """Review must offer proofread segments, not only freshly translated ones.

    Regression: `swatl proofread` then `swatl review` reported "No translated
    segments to review" because only status=translated was selected.
    """
    from swatl.models import Segment, SegmentStatus
    from swatl.review.reviewer import ReviewSession
    from swatl.state import SegmentStore

    store = SegmentStore(tmp_path / "state")
    store.append_many(
        [
            Segment(
                id="p-0001",
                doc="doc",
                anchor=".//p[1]",
                tag="p",
                source_text="一",
                translated="one",
                status=SegmentStatus.PROOFREAD,
            ),
            Segment(
                id="p-0002",
                doc="doc",
                anchor=".//p[2]",
                tag="p",
                source_text="二",
                translated="two",
                status=SegmentStatus.TRANSLATED,
            ),
            Segment(
                id="p-0003",
                doc="doc",
                anchor=".//p[3]",
                tag="p",
                source_text="三",
                status=SegmentStatus.PENDING,
            ),
        ]
    )

    session = ReviewSession(store=store)
    session.load_segments()
    assert session.total == 2
    assert {item.segment.id for item in session.review_items} == {"p-0001", "p-0002"}
