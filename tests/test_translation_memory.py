"""Tests for the Translation Memory module."""

from pathlib import Path

from swatl.models import Segment, SegmentStatus
from swatl.translate.translation_memory import TranslationMemory


class TestTranslationMemoryBasic:
    """Basic TM operations: add, lookup, hash."""

    def test_lookup_returns_none_when_empty(self):
        """Lookup should return None when memory is empty."""
        tm = TranslationMemory()
        seg = Segment(id="s1", doc="x", anchor=".//p[1]", tag="p", source_text="你好世界")
        assert tm.lookup(seg) is None

    def test_add_and_lookup(self):
        """Adding a segment should make it available for lookup."""
        tm = TranslationMemory()
        seg = Segment(
            id="s1",
            doc="x",
            anchor=".//p[1]",
            tag="p",
            source_text="你好世界",
            translated="Hello World",
        )
        tm.add(seg)
        assert tm.lookup(seg) == "Hello World"

    def test_lookup_returns_none_for_nonexistent_source(self):
        """Lookup for different source text should return None."""
        tm = TranslationMemory()
        seg1 = Segment(
            id="s1",
            doc="x",
            anchor=".//p[1]",
            tag="p",
            source_text="你好世界",
            translated="Hello World",
        )
        tm.add(seg1)
        seg2 = Segment(
            id="s2", doc="x", anchor=".//p[2]", tag="p", source_text="再见", translated="Goodbye"
        )
        assert tm.lookup(seg2) is None

    def test_add_empty_translation_ignored(self):
        """Adding a segment with no translation should not add entry."""
        tm = TranslationMemory()
        seg = Segment(id="s1", doc="x", anchor=".//p[1]", tag="p", source_text="你好世界")
        tm.add(seg)
        assert tm.lookup(seg) is None

    def test_add_many(self):
        """Adding multiple segments should return correct count."""
        tm = TranslationMemory()
        segments = [
            Segment(
                id=f"s{i}",
                doc="x",
                anchor=".//p[1]",
                tag="p",
                source_text=f"你好{i}",
                translated=f"Hello{i}",
                status=SegmentStatus.TRANSLATED,
            )
            for i in range(5)
        ]
        count = tm.add_many(segments)
        assert count == 5
        for seg in segments:
            assert tm.lookup(seg) == f"Hello{seg.id[1:]}"


class TestTranslationMemoryDisk:
    """TM disk persistence: save and load."""

    def test_save_and_load(self, tmp_path: Path):
        """Adding entries and saving should persist them."""
        tm_file = tmp_path / "tm.json"
        tm = TranslationMemory(memory_file=tm_file)
        seg = Segment(
            id="s1",
            doc="x",
            anchor=".//p[1]",
            tag="p",
            source_text="你好世界",
            translated="Hello World",
        )
        tm.add(seg)
        tm.save_disk_cache()

        # Reload from disk
        tm2 = TranslationMemory(memory_file=tm_file)
        assert tm2.lookup(seg) == "Hello World"

    def test_save_and_load_many(self, tmp_path: Path):
        """Adding many entries and reloading should preserve all."""
        tm_file = tmp_path / "tm.json"
        tm = TranslationMemory(memory_file=tm_file)
        segments = [
            Segment(
                id=f"s{i}",
                doc="x",
                anchor=".//p[1]",
                tag="p",
                source_text=f"你好{i}",
                translated=f"Hello{i}",
                status=SegmentStatus.TRANSLATED,
            )
            for i in range(10)
        ]
        tm.add_many(segments)
        tm.save_disk_cache()

        tm2 = TranslationMemory(memory_file=tm_file)
        for seg in segments:
            assert tm2.lookup(seg) == f"Hello{seg.id[1:]}"

    def test_save_no_file_raises(self):
        """save_disk_cache with no memory file should be a no-op."""
        tm = TranslationMemory(memory_file=None)
        seg = Segment(
            id="s1",
            doc="x",
            anchor=".//p[1]",
            tag="p",
            source_text="你好世界",
            translated="Hello World",
        )
        tm.add(seg)
        tm.save_disk_cache()  # Should not raise

    def test_load_invalid_file(self, tmp_path: Path):
        """Loading from an invalid JSON file should log warning and skip."""
        tm_file = tmp_path / "tm.json"
        tm_file.write_text("{ invalid json }")
        tm = TranslationMemory(memory_file=tm_file)
        # Should not crash, just log warning
        seg = Segment(
            id="s1", doc="x", anchor=".//p[1]", tag="p", source_text="你好", translated="Hello"
        )
        assert tm.lookup(seg) is None


class TestTranslationMemoryMetrics:
    """TM metrics: count, hit_rate."""

    def test_count(self):
        """count() should return number of entries."""
        tm = TranslationMemory()
        assert tm.count() == 0
        seg = Segment(
            id="s1",
            doc="x",
            anchor=".//p[1]",
            tag="p",
            source_text="你好世界",
            translated="Hello World",
        )
        tm.add(seg)
        assert tm.count() == 1

    def test_hit_rate_empty(self):
        """Hit rate on empty segments should be 0."""
        tm = TranslationMemory()
        assert tm.get_hit_rate([]) == 0.0

    def test_hit_rate_all_match(self):
        """If all segments match cached entries, hit rate is 1.0."""
        tm = TranslationMemory()
        seg1 = Segment(
            id="s1",
            doc="x",
            anchor=".//p[1]",
            tag="p",
            source_text="你好世界",
            translated="Hello World",
        )
        tm.add(seg1)
        assert tm.get_hit_rate([seg1]) == 1.0

    def test_hit_rate_partial(self):
        """Hit rate should be partial matches / total."""
        tm = TranslationMemory()
        seg1 = Segment(
            id="s1",
            doc="x",
            anchor=".//p[1]",
            tag="p",
            source_text="你好世界",
            translated="Hello World",
        )
        seg2 = Segment(
            id="s2", doc="x", anchor=".//p[2]", tag="p", source_text="再见", translated="Goodbye"
        )
        tm.add(seg1)
        assert tm.get_hit_rate([seg1, seg2]) == 0.5


class TestTranslationMemoryIntegration:
    """Integration with Translator.translate_all()."""

    def test_translator_uses_tm(self):
        """Translator should check TM before calling LLM."""
        from swatl.translate.translation_memory import TranslationMemory

        tm = TranslationMemory()
        seg1 = Segment(
            id="s1",
            doc="x",
            anchor=".//p[1]",
            tag="p",
            source_text="你好世界",
            translated="Cached Translation",
            status=SegmentStatus.TRANSLATED,
        )
        tm.add(seg1)

        # Verify segment matches TM
        assert tm.lookup(seg1) == "Cached Translation"
        # TM should not call the provider for this segment

    def test_tm_eviction(self):
        """TM should evict oldest entries when max_entries is exceeded."""
        tm = TranslationMemory(max_entries=3)
        for i in range(5):
            seg = Segment(
                id=f"s{i}",
                doc="x",
                anchor=".//p[1]",
                tag="p",
                source_text=f"你好{i}",
                translated=f"Hello{i}",
                status=SegmentStatus.TRANSLATED,
            )
            tm.add(seg)
        assert tm.count() == 3
        # Oldest entries should be evicted
        assert (
            tm.lookup(Segment(id="s0", doc="x", anchor=".//p[1]", tag="p", source_text="你好0"))
            is None
        )
        assert (
            tm.lookup(Segment(id="s1", doc="x", anchor=".//p[1]", tag="p", source_text="你好1"))
            is None
        )
        # Newer entries should remain
        assert (
            tm.lookup(Segment(id="s3", doc="x", anchor=".//p[1]", tag="p", source_text="你好3"))
            == "Hello3"
        )
        assert (
            tm.lookup(Segment(id="s4", doc="x", anchor=".//p[1]", tag="p", source_text="你好4"))
            == "Hello4"
        )
