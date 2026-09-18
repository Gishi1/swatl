"""Tests for context_db/ module (Phase 7: Context DB storage and management)."""

from __future__ import annotations

import json

from swatl.context_db.importer import (
    ContextImporter,
    chunk_text,
    extract_text_from_html,
    parse_csv_bilingual,
    parse_json_bilingual,
)
from swatl.context_db.model import ContextEntry, ContextImportChunk
from swatl.context_db.store import ContextEntryStore

# ── ContextEntry model tests ──────────────────────────────────────


class TestContextEntry:
    def test_create_entry(self):
        entry = ContextEntry(source_text="你好", translated_text="Hello")
        assert entry.id is not None
        assert entry.entry_type == "manual"
        assert entry.tags == []

    def test_create_entry_with_fields(self):
        entry = ContextEntry(
            source_text="三体",
            translated_text="Three-Body",
            entry_type="prefill",
            source_file="glossary.json",
            section="terminology",
            tags=["sci-fi", "proper-noun"],
        )
        assert entry.entry_type == "prefill"
        assert entry.source_file == "glossary.json"
        assert "sci-fi" in entry.tags

    def test_update_timestamp(self):
        entry = ContextEntry(source_text="test")
        before = entry.updated_at
        import time

        time.sleep(0.01)
        entry.update_timestamp()
        assert entry.updated_at > before


# ── ContextEntryStore tests ──────────────────────────────────────


class TestContextEntryStore:
    def test_create_store(self, tmp_path):
        store = ContextEntryStore(tmp_path / "state")
        # Directory is created lazily on first write
        assert "state" in str(store.entries_file)

    def test_create_and_get_entry(self, tmp_path):
        store = ContextEntryStore(tmp_path)
        entry = ContextEntry(source_text="你好", translated_text="Hello", tags=["test"])
        result = store.create(entry)
        assert result.id == entry.id
        fetched = store.get_entry(entry.id)
        assert fetched is not None
        assert fetched.source_text == "你好"

    def test_update_entry(self, tmp_path):
        store = ContextEntryStore(tmp_path)
        entry = ContextEntry(source_text="你好", translated_text="Hello")
        store.create(entry)
        updated = store.update(entry.id, translated_text="Hola")
        assert updated is not None
        assert updated.translated_text == "Hola"

    def test_update_nonexistent(self, tmp_path):
        store = ContextEntryStore(tmp_path)
        result = store.update("nonexistent-id", translated_text="test")
        assert result is None

    def test_delete_entry(self, tmp_path):
        store = ContextEntryStore(tmp_path)
        entry = ContextEntry(source_text="你好")
        store.create(entry)
        assert store.delete(entry.id) is True
        assert store.delete(entry.id) is False  # already deleted
        assert store.count() == 0

    def test_delete_nonexistent(self, tmp_path):
        store = ContextEntryStore(tmp_path)
        assert store.delete("nonexistent") is False

    def test_create_many(self, tmp_path):
        store = ContextEntryStore(tmp_path)
        entries = [
            ContextEntry(source_text=f"text{i}", translated_text=f"translation{i}")
            for i in range(5)
        ]
        added = store.create_many(entries)
        assert added == 5
        assert store.count() == 5

    def test_create_many_dedup(self, tmp_path):
        store = ContextEntryStore(tmp_path)
        entry = ContextEntry(id="fixed-id", source_text="hello")
        store.create(entry)
        entries = [
            ContextEntry(id="fixed-id", source_text="hello"),
            ContextEntry(id="new-id", source_text="world"),
        ]
        added = store.create_many(entries)
        assert added == 1  # only "new-id" is new

    def test_search(self, tmp_path):
        store = ContextEntryStore(tmp_path)
        store.create(ContextEntry(source_text="爱因斯坦", translated_text="Einstein"))
        store.create(ContextEntry(source_text="相对论", translated_text="Relativity"))
        results = store.search("相对论")
        assert len(results) == 1
        assert results[0].source_text == "相对论"

    def test_search_tags(self, tmp_path):
        store = ContextEntryStore(tmp_path)
        store.create(ContextEntry(source_text="test", tags=["sci-fi", "terminology"]))
        results = store.search("sci-fi")
        assert len(results) == 1

    def test_filter_by_type(self, tmp_path):
        store = ContextEntryStore(tmp_path)
        store.create(ContextEntry(source_text="t1", entry_type="segment"))
        store.create(ContextEntry(source_text="t2", entry_type="manual"))
        store.create(ContextEntry(source_text="t3", entry_type="segment"))
        assert len(store.filter_by_type("segment")) == 2
        assert len(store.filter_by_type("manual")) == 1

    def test_tags(self, tmp_path):
        store = ContextEntryStore(tmp_path)
        store.create(ContextEntry(source_text="t1", tags=["a", "b"]))
        store.create(ContextEntry(source_text="t2", tags=["b", "c"]))
        assert store.tags() == ["a", "b", "c"]

    def test_stats(self, tmp_path):
        store = ContextEntryStore(tmp_path)
        store.create(ContextEntry(source_text="t1", entry_type="segment"))
        store.create(ContextEntry(source_text="t2", entry_type="prefill"))
        stats = store.stats()
        assert stats["total"] == 2
        assert stats["by_type"]["segment"] == 1
        assert stats["by_type"]["prefill"] == 1


# ── ContextImporter tests ─────────────────────────────────────────


class TestChunkText:
    def test_chunks_basic(self):
        text = " ".join([f"Word {i}" for i in range(20)])
        chunks = chunk_text(text, chunk_size=30, overlap=5)
        assert len(chunks) >= 1
        # Chunks should not be empty
        assert all(c.strip() for c in chunks)

    def test_chunks_with_sentences(self):
        text = "Hello world. This is a test. More text here. Final sentence."
        chunks = chunk_text(text, chunk_size=20, overlap=5)
        assert len(chunks) >= 1

    def test_chunks_small_text(self):
        text = "Short text."
        chunks = chunk_text(text, chunk_size=100)
        assert len(chunks) == 1
        assert chunks[0] == "Short text."


class TestExtractTextFromHtml:
    def test_basic_html(self):
        html = "<html><body><p>Hello <b>world</b>.</p></body></html>"
        result = extract_text_from_html(html)
        assert "Hello world" in result

    def test_removes_scripts(self):
        html = "<p>Text</p><script>alert(1)</script><p>More</p>"
        result = extract_text_from_html(html)
        assert "alert" not in result
        assert "Text" in result
        assert "More" in result

    def test_decodes_html_entities(self):
        html = "<p>&amp; &lt; &gt; &quot;</p>"
        result = extract_text_from_html(html)
        assert "&amp;" not in result
        assert "&" in result


class TestParseBilingual:
    def test_parse_json(self):
        data = json.dumps([{"source": "你好", "target": "Hello"}])
        pairs = parse_json_bilingual(data)
        assert len(pairs) == 1
        assert pairs[0] == ("你好", "Hello")

    def test_parse_json_list_of_dicts(self):
        data = json.dumps(
            [
                {"source": "你好", "target": "Hello"},
                {"source": "世界", "target": "World"},
            ]
        )
        pairs = parse_json_bilingual(data)
        assert len(pairs) == 2

    def test_parse_csv(self):
        csv_data = "你好,Hello\n世界,World"
        pairs = parse_csv_bilingual(csv_data)
        assert len(pairs) == 2
        assert pairs[0] == ("你好", "Hello")

    def test_parse_csv_tab_delimited(self):
        csv_data = "你好\tHello\n世界\tWorld"
        pairs = parse_csv_bilingual(csv_data, delimiter="\t")
        assert len(pairs) == 2


class TestContextImporter:
    def test_import_text(self, tmp_path):
        importer = ContextImporter(chunk_size=10, overlap=3)
        result = importer.import_text("Hello world this is a test", "test.txt")
        assert result.entries_created > 0
        assert result.chunks_total == result.entries_created

    def test_import_json(self, tmp_path):
        importer = ContextImporter()
        data = json.dumps(
            [
                {"source": "你好", "target": "Hello"},
                {"source": "世界", "target": "World"},
            ]
        )
        result = importer.import_json(data, "test.json")
        assert result.entries_created == 2

    def test_import_csv(self, tmp_path):
        importer = ContextImporter()
        csv_data = "你好,Hello\n世界,World"
        result = importer.import_csv(csv_data, "test.csv")
        assert result.entries_created == 2

    def test_preview_chunks(self, tmp_path):
        importer = ContextImporter(chunk_size=15, overlap=5)
        text = "Hello world this is a longer text for chunking"
        chunks = importer.preview_chunks(text)
        assert len(chunks) > 0
        assert isinstance(chunks[0], ContextImportChunk)

    def test_detect_json(self, tmp_path):
        importer = ContextImporter()
        assert importer.detect_format('{"source":"x"}', "data.json") == "json"

    def test_detect_html(self, tmp_path):
        importer = ContextImporter()
        assert importer.detect_format("<html><body>Test</body></html>", "page.html") == "html"

    def test_detect_text(self, tmp_path):
        importer = ContextImporter()
        assert importer.detect_format("Hello world", "readme.txt") == "text"


def test_partial_update_does_not_corrupt_required_fields(tmp_path):
    """A partial PATCH-style update must not null out required fields.

    Regression: the web GUI edit modal only sends source/translation/tags; an
    unguarded update wrote ``entry_type: null`` and every later read of the
    Context DB failed validation.
    """
    from swatl.context_db.model import ContextEntry
    from swatl.context_db.store import ContextEntryStore

    store = ContextEntryStore(tmp_path)
    entry = ContextEntry(source_text="原文", translated_text="Original", entry_type="curated")
    store.create(entry)

    updated = store.update(entry.id, translated_text="Edited", entry_type=None, source_text=None)
    assert updated is not None
    assert updated.entry_type == "curated"
    assert updated.source_text == "原文"
    assert updated.translated_text == "Edited"

    # The store must still be readable afterwards.
    reloaded = ContextEntryStore(tmp_path).get_entry(entry.id)
    assert reloaded is not None
    assert reloaded.entry_type == "curated"


def test_load_all_repairs_null_entry_type(tmp_path):
    """A persisted null entry_type is repaired instead of breaking the store."""
    import json

    from swatl.context_db.store import ContextEntryStore

    entries_file = tmp_path / "context_db" / "entries.json"
    entries_file.parent.mkdir(parents=True, exist_ok=True)
    entries_file.write_text(
        json.dumps(
            [
                {"id": "bad", "source_text": "x", "entry_type": None},
                {"id": "ok", "source_text": "y", "entry_type": "manual"},
            ]
        ),
        encoding="utf-8",
    )

    store = ContextEntryStore(tmp_path)
    entries = store.load_all()
    assert entries["bad"].entry_type == "manual"
    assert set(entries) == {"bad", "ok"}
