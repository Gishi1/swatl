"""Integration tests for the full translation pipeline."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fixtures.create_fixture import create_fixture_epub
from swatl.audit.auditor import audit_segments
from swatl.ingest import extract_epub, extract_segments_from_epub
from swatl.models import Glossary, GlossaryEntry, RunMetadata, Segment
from swatl.proofread.proofreader import Proofreader
from swatl.providers.mock import MockProvider
from swatl.translate import Translator
from swatl.writeback import writeback_segments


class TestEndToEndPipeline:
    """Test the full EPUB translation pipeline."""

    def test_full_pipeline_with_mock(self, tmp_path):
        """Test the complete pipeline: extract → translate → proofread → audit → writeback."""
        # Create fixture EPUB
        fixture = tmp_path / "fixture.epub"
        create_fixture_epub(fixture)

        # Step 1: Extract
        info, epub_dir = extract_epub(fixture)
        assert info.title == "三体"
        assert info.language == "zh"

        # Step 2: Segment
        segments, doc_count = extract_segments_from_epub(
            epub_dir, info.spine_items, info.mime_types, info.language
        )
        assert len(segments) > 0
        assert doc_count == 3
        assert all(s.status == "pending" for s in segments)

        # Step 3: Create glossary
        glossary = Glossary(
            entries=[
                GlossaryEntry(source="三体", target="Three-Body"),
            ]
        )

        # Step 4: Translate with MockProvider
        prov = MockProvider(name="mock", target_lang="en")
        trans = Translator(provider=prov, source_lang="zh", target_lang="en")
        segments = asyncio.run(trans.translate_all(segments, glossary))

        translated = [s for s in segments if s.status == "translated"]
        assert len(translated) == len(segments)

        # Step 5: Proofread
        prov2 = MockProvider(name="mock", target_lang="en")
        proofreader = Proofreader(provider=prov2)
        segments = asyncio.run(proofreader.proofread_all(segments, glossary))

        proofread = [s for s in segments if s.status == "proofread"]
        assert len(proofread) == len(segments)

        # Step 6: Audit
        report = audit_segments(segments, glossary)
        assert report.total_segments == len(segments)
        assert report.translated_count == len(segments)

        # Step 7: Write back
        output_path = tmp_path / "output.epub"
        result = writeback_segments(epub_dir, segments, target_lang="en", output_path=output_path)
        assert result.exists()

        # Verify output structure
        import zipfile

        assert zipfile.is_zipfile(result)
        with zipfile.ZipFile(result, "r") as zf:
            names = zf.namelist()
            assert any(n.endswith(".xhtml") for n in names)
            assert any(n.endswith(".css") for n in names)

    def test_state_checkpoint_resume(self, tmp_path):
        """Test checkpoint and resume functionality."""
        from swatl.state.store import SegmentStore

        store = SegmentStore(tmp_path)

        # Create test segments
        segments = [
            Segment(
                id=f"p-{i:04d}", doc="doc", anchor=".//p[1]", tag="p", source_text=f"Test text {i}"
            )
            for i in range(10)
        ]

        # Append segments
        store.append_many(segments)

        # Load and verify
        loaded = store.load_segments()
        assert len(loaded) == 10

        # Mark some as translated
        for seg_id, seg in list(loaded.items()):
            seg.status = "translated"
            seg.translated = f"Translation {seg_id}"

        store.append_many(list(loaded.values()))

        # Verify status counts
        counts = store.status_counts()
        assert counts.get("translated", 0) == 10

    def test_run_metadata_serialization(self):
        """Test run metadata save/load roundtrip."""
        run = RunMetadata(
            book_title="三体",
            book_author="刘慈欣",
            book_lang="zh",
            book_version="EPUB 3.0",
            pair=["zh", "en"],
            provider="mock",
            total_segments=100,
            stages_completed=["extract", "translate"],
            total_tokens_in=5000,
            total_tokens_out=4000,
        )

        data = run.to_dict()
        restored = RunMetadata.from_dict(data)

        assert restored.book_title == run.book_title
        assert restored.total_segments == run.total_segments
        assert restored.stages_completed == run.stages_completed
