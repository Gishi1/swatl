"""Tests for models."""

from swatl.models import (
    Glossary,
    GlossaryEntry,
    ProviderConfig,
    RunMetadata,
    Segment,
    SegmentStatus,
)


class TestSegment:
    def test_create_segment(self):
        seg = Segment(
            id="p-0001",
            doc="text/ch01.xhtml",
            anchor=".//p[1]",
            tag="p",
            source_text="三体是一个宏大的概念。",
        )
        assert seg.id == "p-0001"
        assert seg.translated is None
        assert seg.status == SegmentStatus.PENDING

    def test_segment_with_translation(self):
        seg = Segment(
            id="p-0001",
            doc="text/ch01.xhtml",
            anchor=".//p[1]",
            tag="p",
            source_text="三体",
            translated="Three-Body",
            status="translated",
        )
        assert seg.translated == "Three-Body"
        assert seg.status == SegmentStatus.TRANSLATED

    def test_model_dump_roundtrip(self):
        seg = Segment(
            id="p-0001",
            doc="text/ch01.xhtml",
            anchor=".//p[1]",
            tag="p",
            source_text="三体",
            translated="Three-Body",
        )
        data = seg.model_dump()
        seg2 = Segment.model_validate(data)
        assert seg2.id == seg.id
        assert seg2.translated == seg.translated


class TestRunMetadata:
    def test_create_run(self):
        run = RunMetadata(book_title="三体", book_lang="zh", pair=["zh", "en"])
        assert run.book_title == "三体"
        assert run.pair == ["zh", "en"]
        assert run.total_segments == 0

    def test_model_roundtrip(self):
        run = RunMetadata(book_title="三体", book_lang="zh", pair=["zh", "en"], provider="deepseek")
        data = run.to_dict()
        run2 = RunMetadata.from_dict(data)
        assert run2.book_title == run.book_title
        assert run2.provider == run.provider


class TestGlossary:
    def test_create_glossary(self):
        g = Glossary(name="Test", pair=["zh", "en"])
        assert g.name == "Test"
        assert len(g.entries) == 0

    def test_add_entry(self):
        g = Glossary(entries=[GlossaryEntry(source="三体", target="Three-Body")])
        assert len(g.entries) == 1
        assert g.entries[0].source == "三体"
        assert g.entries[0].target == "Three-Body"


class TestProviderConfig:
    def test_create_config(self):
        cfg = ProviderConfig(
            type="openai-compatible",
            base_url="https://api.example.com",
            model="test-model",
            api_key_env="TEST_KEY",
        )
        assert cfg.type == "openai-compatible"
        assert cfg.model == "test-model"
