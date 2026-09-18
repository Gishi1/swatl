"""Tests for cost tracking in RunMetadata and SegmentStore."""

from swatl.models import RunMetadata
from swatl.state.store import SegmentStore


class TestCostTracking:
    """Tests for cost tracking in run metadata."""

    def test_run_metadata_has_cost_field(self):
        """RunMetadata should have estimated_cost_usd field."""
        run = RunMetadata(book_title="Test", book_lang="zh")
        assert hasattr(run, "estimated_cost_usd")
        assert run.estimated_cost_usd == 0.0

    def test_run_metadata_with_cost(self):
        """RunMetadata can store cost information."""
        run = RunMetadata(
            book_title="Test",
            book_lang="zh",
            total_tokens_in=50000,
            total_tokens_out=50000,
            estimated_cost_usd=0.21,
        )
        assert run.estimated_cost_usd == 0.21

    def test_run_metadata_serializes_cost(self):
        """Cost field should serialize/deserialize correctly."""
        run = RunMetadata(
            book_title="Test",
            book_lang="zh",
            estimated_cost_usd=0.42,
            total_tokens_in=100000,
            total_tokens_out=80000,
        )
        data = run.to_dict()
        assert data["estimated_cost_usd"] == 0.42

        loaded = RunMetadata.from_dict(data)
        assert loaded.estimated_cost_usd == 0.42

    def test_store_saves_cost(self, tmp_path):
        """SegmentStore should save and load cost information."""
        store = SegmentStore(tmp_path)
        run = RunMetadata(
            book_title="Test Book",
            book_lang="zh",
            estimated_cost_usd=0.35,
            total_segments=100,
        )
        store.save_run(run)

        loaded = store.load_run()
        assert loaded is not None
        assert loaded.estimated_cost_usd == 0.35
        assert loaded.total_segments == 100

    def test_store_updates_cost_on_reload(self, tmp_path):
        """Updating run metadata should persist cost."""
        store = SegmentStore(tmp_path)
        run = RunMetadata(
            book_title="Test",
            book_lang="zh",
            estimated_cost_usd=0.10,
        )
        store.save_run(run)

        # Update with new cost
        run.estimated_cost_usd = 0.25
        store.save_run(run)

        loaded = store.load_run()
        assert loaded.estimated_cost_usd == 0.25
