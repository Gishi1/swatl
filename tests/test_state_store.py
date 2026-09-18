"""Tests for segment store."""

import pytest

from swatl.models import RunMetadata, Segment
from swatl.state.store import SegmentStore


@pytest.fixture
def state_dir(tmp_path):
    return tmp_path / "state"


def test_create_store(state_dir):
    SegmentStore(state_dir)
    assert (state_dir / "segments.jsonl").exists()
    assert (state_dir / "run.json").exists() or not (state_dir / "run.json").exists()


def test_append_and_load_segment(state_dir):
    store = SegmentStore(state_dir)
    seg = Segment(
        id="p-0001",
        doc="text/ch01.xhtml",
        anchor=".//p[1]",
        tag="p",
        source_text="三体是一个宏大的概念。",
    )
    store.append_segment(seg)

    loaded = store.load_segments()
    assert "p-0001" in loaded
    assert loaded["p-0001"].source_text == "三体是一个宏大的概念。"


def test_append_many(state_dir):
    store = SegmentStore(state_dir)
    segments = [
        Segment(
            id=f"p-{i:04d}",
            doc="text/ch01.xhtml",
            anchor=f".//p[{i}]",
            tag="p",
            source_text=f"Segment {i}",
        )
        for i in range(5)
    ]
    store.append_many(segments)

    loaded = store.load_segments()
    assert len(loaded) == 5


def test_last_write_wins(state_dir):
    store = SegmentStore(state_dir)
    # Append two versions of the same segment
    seg1 = Segment(
        id="p-0001",
        doc="text/ch01.xhtml",
        anchor=".//p[1]",
        tag="p",
        source_text="Original",
        translated="First translation",
    )
    seg2 = Segment(
        id="p-0001",
        doc="text/ch01.xhtml",
        anchor=".//p[1]",
        tag="p",
        source_text="Original",
        translated="Second translation",
    )

    store.append_segment(seg1)
    store.append_segment(seg2)

    loaded = store.load_segments()
    assert loaded["p-0001"].translated == "Second translation"


def test_save_and_load_run(state_dir):
    store = SegmentStore(state_dir)
    run = RunMetadata(book_title="三体", book_lang="zh", pair=["zh", "en"])
    store.save_run(run)

    loaded = store.load_run()
    assert loaded is not None
    assert loaded.book_title == "三体"
    assert loaded.book_lang == "zh"


def test_load_nonexistent_run(state_dir):
    # Clean state — no run.json yet
    store = SegmentStore(state_dir)
    # The store constructor doesn't create run.json
    loaded = store.load_run()
    assert loaded is None


def test_pending_segments(state_dir):
    store = SegmentStore(state_dir)
    store.append_many(
        [
            Segment(id="p-0001", doc="doc", anchor=".//p[1]", tag="p", source_text="text"),
            Segment(
                id="p-0002",
                doc="doc",
                anchor=".//p[2]",
                tag="p",
                source_text="text",
                status="translated",
                translated="done",
            ),
            Segment(id="p-0003", doc="doc", anchor=".//p[3]", tag="p", source_text="text"),
        ]
    )

    pending = store.pending_segments()
    assert len(pending) == 2
    assert all(s.status == "pending" for s in pending)


def test_total_count(state_dir):
    store = SegmentStore(state_dir)
    store.append_many(
        [
            Segment(id=f"p-{i:04d}", doc="doc", anchor=".//p[1]", tag="p", source_text="text")
            for i in range(10)
        ]
    )
    assert store.total_count() == 10


def test_status_counts(state_dir):
    store = SegmentStore(state_dir)
    store.append_many(
        [
            Segment(
                id="p-0001",
                doc="doc",
                anchor=".//p[1]",
                tag="p",
                source_text="text",
                status="translated",
            ),
            Segment(
                id="p-0002",
                doc="doc",
                anchor=".//p[2]",
                tag="p",
                source_text="text",
                status="translated",
            ),
            Segment(
                id="p-0003",
                doc="doc",
                anchor=".//p[3]",
                tag="p",
                source_text="text",
                status="pending",
            ),
            Segment(
                id="p-0004",
                doc="doc",
                anchor=".//p[4]",
                tag="p",
                source_text="text",
                status="proofread",
            ),
        ]
    )

    counts = store.status_counts()
    assert counts.get("translated") == 2
    assert counts.get("pending") == 1
    assert counts.get("proofread") == 1


def test_last_write_wins_is_used_by_query_helpers(state_dir):
    """Re-appending a segment must not inflate counts or duplicate listings.

    The JSONL log is append-only: a resumed run, an in-place edit or a second
    translate pass writes a fresh line for the same segment id. Every query
    helper therefore has to work on the de-duplicated snapshot.
    """
    store = SegmentStore(state_dir)
    store.append_many(
        [
            Segment(id="p-0001", doc="doc", anchor=".//p[1]", tag="p", source_text="一"),
            Segment(id="p-0002", doc="doc", anchor=".//p[2]", tag="p", source_text="二"),
        ]
    )

    # Second pass over the same segments (as a resume or edit would do).
    updated = Segment(
        id="p-0001",
        doc="doc",
        anchor=".//p[1]",
        tag="p",
        source_text="一",
        translated="one",
        status="translated",
    )
    store.append_segment(updated)

    assert store.total_count() == 2
    assert store.status_counts() == {"pending": 1, "translated": 1}
    assert [s.id for s in store.translated_segments()] == ["p-0001"]
    assert len(store.pending_segments()) == 1
    assert store.get_segment("p-0001").translated == "one"
