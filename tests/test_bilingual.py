"""Tests for the bilingual export feature.

A bilingual export replaces each document's paragraphs with source/target pairs
in place, so the exported book *is* the side-by-side edition and its documents
keep the hrefs the package manifest already declares. An earlier implementation
wrote a parallel ``bilingual/`` directory that was never added to the manifest,
which meant no reading system could reach it.
"""

import zipfile

from swatl.models import SegmentStatus
from swatl.writeback.writer import writeback_segments


class TestBilingualExport:
    """Tests for the bilingual EPUB export feature."""

    @staticmethod
    def _export(fixture_epub, tmp_path, bilingual: bool, name: str = "out.epub"):
        from swatl.ingest import extract_epub, extract_segments_from_epub

        info, epub_dir = extract_epub(fixture_epub)
        segments, _ = extract_segments_from_epub(
            epub_dir, info.spine_items, info.mime_types, info.language
        )
        for seg in segments:
            seg.translated = f"Translated: {seg.source_text}"
            seg.status = SegmentStatus.PROOFREAD

        output = tmp_path / name
        result = writeback_segments(
            epub_dir, segments, target_lang="en", output_path=output, bilingual=bilingual
        )
        assert result.exists()
        return zipfile.ZipFile(output)

    def test_bilingual_documents_hold_both_languages(self, fixture_epub, tmp_path):
        zf = self._export(fixture_epub, tmp_path, bilingual=True, name="bilingual.epub")
        content = zf.read("text/ch01.xhtml").decode("utf-8")

        assert 'class="swatl-source"' in content
        assert 'class="swatl-target"' in content
        assert "Translated:" in content

    def test_bilingual_preserves_structure(self, fixture_epub, tmp_path):
        """The original documents are the bilingual ones; nothing is duplicated."""
        zf = self._export(fixture_epub, tmp_path, bilingual=True, name="preserve.epub")
        names = zf.namelist()

        docs = [n for n in names if n.endswith(".xhtml")]
        assert docs
        # Every spine document that was translated carries both languages, and no
        # parallel copy exists outside the manifest.
        assert "swatl-bilingual" in zf.read("text/ch01.xhtml").decode("utf-8")
        assert not [n for n in names if n.startswith("bilingual/")]

    def test_bilingual_includes_translation_in_text(self, fixture_epub, tmp_path):
        """A translated segment appears next to its source text."""
        zf = self._export(fixture_epub, tmp_path, bilingual=True, name="text.epub")
        for name in zf.namelist():
            if name.endswith(".xhtml") and "Translated:" in zf.read(name).decode("utf-8"):
                return
        raise AssertionError("No document contains the translation")

    def test_source_half_is_not_the_translation(self, fixture_epub, tmp_path):
        """Both halves used to hold the translation, making the copy useless."""
        import re

        zf = self._export(fixture_epub, tmp_path, bilingual=True, name="halves.epub")
        content = zf.read("text/ch01.xhtml").decode("utf-8")

        sources = re.findall(r'class="swatl-source"[^>]*>(.*?)</p>', content, re.DOTALL)
        assert sources
        assert all("Translated:" not in source for source in sources)

    def test_non_bilingual_does_not_create_parallel_docs(self, fixture_epub, tmp_path):
        """Non-bilingual export leaves the book monolingual."""
        zf = self._export(fixture_epub, tmp_path, bilingual=False, name="non_bilingual.epub")
        names = zf.namelist()

        assert not [n for n in names if n.startswith("bilingual/")]
        assert "swatl-bilingual" not in zf.read("text/ch01.xhtml").decode("utf-8")
        assert "Translated:" in zf.read("text/ch01.xhtml").decode("utf-8")
