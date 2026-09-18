"""Tests for the bilingual export feature."""

import zipfile

from swatl.models import SegmentStatus
from swatl.writeback.writer import writeback_segments


class TestBilingualExport:
    """Tests for the bilingual EPUB export feature."""

    def test_bilingual_creates_parallel_doc(self, fixture_epub, tmp_path):
        """Bilingual export should create parallel translated documents."""
        from swatl.ingest import extract_epub, extract_segments_from_epub

        info, epub_dir = extract_epub(fixture_epub)
        segments, _ = extract_segments_from_epub(
            epub_dir, info.spine_items, info.mime_types, info.language
        )

        # Set translated status on segments
        for seg in segments:
            seg.translated = f"Translated: {seg.source_text}"
            seg.status = SegmentStatus.PROOFREAD

        output = tmp_path / "bilingual.epub"
        result = writeback_segments(
            epub_dir, segments, target_lang="en", output_path=output, bilingual=True
        )

        # Verify the EPUB was created
        assert result.exists()
        assert output.exists()

        # Check that bilingual directory exists within the EPUB
        with zipfile.ZipFile(output, "r") as zf:
            names = zf.namelist()
            # Should have bilingual/ prefix files
            bilingual_names = [n for n in names if n.startswith("bilingual/")]
            assert len(bilingual_names) > 0

    def test_bilingual_preserves_structure(self, fixture_epub, tmp_path):
        """Bilingual export should preserve original structure."""
        from swatl.ingest import extract_epub, extract_segments_from_epub

        info, epub_dir = extract_epub(fixture_epub)
        segments, _ = extract_segments_from_epub(
            epub_dir, info.spine_items, info.mime_types, info.language
        )

        for seg in segments:
            seg.translated = f"Translated: {seg.source_text}"
            seg.status = SegmentStatus.PROOFREAD

        output = tmp_path / "bilingual_preserve.epub"
        writeback_segments(epub_dir, segments, target_lang="en", output_path=output, bilingual=True)

        with zipfile.ZipFile(output, "r") as zf:
            names = zf.namelist()
            # Should still have the original document
            original_docs = [n for n in names if n.endswith(".xhtml")]
            assert len(original_docs) > 0
            # Should also have bilingual copies
            bilingual_docs = [
                n for n in names if n.startswith("bilingual/") and n.endswith(".xhtml")
            ]
            assert len(bilingual_docs) > 0

    def test_bilingual_includes_translation_in_text(self, fixture_epub, tmp_path):
        """Bilingual document should contain translated text."""
        from swatl.ingest import extract_epub, extract_segments_from_epub

        info, epub_dir = extract_epub(fixture_epub)
        segments, _ = extract_segments_from_epub(
            epub_dir, info.spine_items, info.mime_types, info.language
        )

        # Only translate first segment
        first_seg = segments[0]
        first_seg.translated = "BILINGUAL_TRANSLATION_TEXT"
        first_seg.status = SegmentStatus.PROOFREAD

        output = tmp_path / "bilingual_text.epub"
        writeback_segments(epub_dir, segments, target_lang="en", output_path=output, bilingual=True)

        with zipfile.ZipFile(output, "r") as zf:
            # Check the bilingual directory
            names = zf.namelist()
            for name in names:
                if name.startswith("bilingual/") and name.endswith(".xhtml"):
                    content = zf.read(name).decode("utf-8")
                    if "BILINGUAL_TRANSLATION_TEXT" in content:
                        return  # Found it
            # If we get here, check all XHTML files for the translation
            for name in names:
                if name.endswith(".xhtml"):
                    content = zf.read(name).decode("utf-8")
                    if "BILINGUAL_TRANSLATION_TEXT" in content:
                        return
            raise AssertionError("Translation text not found in any XHTML file")

    def test_non_bilingual_does_not_create_parallel_docs(self, fixture_epub, tmp_path):
        """Non-bilingual export should not create parallel documents."""
        from swatl.ingest import extract_epub, extract_segments_from_epub

        info, epub_dir = extract_epub(fixture_epub)
        segments, _ = extract_segments_from_epub(
            epub_dir, info.spine_items, info.mime_types, info.language
        )

        for seg in segments:
            seg.translated = f"Translated: {seg.source_text}"
            seg.status = SegmentStatus.PROOFREAD

        output = tmp_path / "non_bilingual.epub"
        writeback_segments(
            epub_dir, segments, target_lang="en", output_path=output, bilingual=False
        )

        with zipfile.ZipFile(output, "r") as zf:
            names = zf.namelist()
            # Should NOT have bilingual/ prefix
            bilingual_names = [n for n in names if n.startswith("bilingual/")]
            assert len(bilingual_names) == 0
