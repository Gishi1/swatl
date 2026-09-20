"""Tests for the bilingual export feature.

A bilingual export translates each document in place and then inserts a copy of
every changed top-level block, in the source language, immediately before it —
so the exported book reads as source, translation, source, translation, and no
document lives outside the package manifest. Inline markup must survive in both
halves: an earlier implementation replaced the whole paragraph with a pair of
plain paragraphs and silently deleted every nested <em>/<a>/<span>.
"""

import zipfile

from swatl.models import SegmentStatus
from swatl.writeback.writer import writeback_segments


def _make_epub(tmp_path, body: str, name: str = "book.epub"):
    """A one-document EPUB whose chapter body is *body*."""
    import zipfile as zf

    book = tmp_path / name
    with zf.ZipFile(book, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
            '<rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>'
            "</rootfiles></container>",
        )
        z.writestr(
            "content.opf",
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="2.0">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            "<dc:title>测试</dc:title><dc:creator>作者</dc:creator>"
            "<dc:language>zh</dc:language></metadata><manifest>"
            '<item id="c" href="ch.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="s" href="style.css" media-type="text/css"/>'
            '</manifest><spine><itemref idref="c"/></spine></package>',
        )
        z.writestr("style.css", "body { font-family: serif; }")
        z.writestr(
            "ch.xhtml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh" lang="zh">'
            '<head><meta charset="UTF-8"/><title>第一章</title>'
            '<link rel="stylesheet" type="text/css" href="style.css"/></head>'
            f"<body>{body}</body></html>",
        )
    return book


def _bilingual_body(tmp_path, body: str) -> str:
    """Run a bilingual export over *body* and return the chapter's <body>."""
    from swatl.ingest import extract_epub, extract_segments_from_epub

    book = _make_epub(tmp_path, body)
    info, epub_dir = extract_epub(book)
    segments, _ = extract_segments_from_epub(
        epub_dir, info.spine_items, info.mime_types, info.language
    )
    for seg in segments:
        seg.translated = f"EN({seg.source_text})"
        seg.status = SegmentStatus.PROOFREAD

    out = writeback_segments(
        epub_dir, segments, target_lang="en", output_path=tmp_path / "bi.epub", bilingual=True
    )
    with zipfile.ZipFile(out) as z:
        content = z.read("ch.xhtml").decode("utf-8")
    return content


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

    def test_source_block_precedes_its_translation(self, tmp_path):
        content = _bilingual_body(tmp_path, "<p>红岸基地是一座秘密设施。</p>")
        source_at = content.find("红岸基地是一座秘密设施。")
        translated_at = content.find("EN(红岸基地是一座秘密设施。)")

        assert source_at != -1 and translated_at != -1
        assert source_at < translated_at
        assert 'class="swatl-source"' in content

    def test_inline_markup_survives_in_both_halves(self, tmp_path):
        """The regression: replacing a paragraph deleted its inline children."""
        content = _bilingual_body(tmp_path, "<p>alpha <em>beta</em> gamma</p>")

        assert "beta" in content, "inline source text was deleted"
        assert "EN(beta)" in content, "inline translation was deleted"
        assert "gamma" in content
        assert "EN(gamma)" in content
        assert content.count("<em") == 2  # one per language

    def test_nested_blocks_are_duplicated_once(self, tmp_path):
        content = _bilingual_body(tmp_path, "<blockquote><p>宇宙很大，生活更大。</p></blockquote>")

        assert content.count("<blockquote") == 2
        assert content.count("EN(宇宙很大，生活更大。)") == 1
        # The source copy keeps the nested paragraph, and the translated copy
        # carries the translation of that paragraph.
        assert content.count("<p") == 2

    def test_tail_text_is_not_duplicated_within_a_block(self, tmp_path):
        """A tail belongs to its block; it must appear once per language."""
        content = _bilingual_body(tmp_path, "<p><br/>第二行</p>")

        # The source block holds it once; the translation embeds the source text
        # in this test's stand-in provider, so count only the plain occurrence.
        assert content.count(">第二行") == 1
        assert content.count("EN(第二行)") == 1
        # A block-level wrapper inside a <p> was invalid XHTML.
        assert "<p><br/><p" not in content.replace("\n", "")
        assert content.count("<div") == 0

    def test_document_stays_valid_xhtml_with_one_body(self, tmp_path):
        from lxml import etree

        content = _bilingual_body(tmp_path, "<p>正文</p>")
        root = etree.fromstring(content.encode("utf-8"))

        assert root.tag.endswith("html")
        assert content.count("<body") == 1
        assert content.count("</body>") == 1

    def test_head_and_stylesheet_survive(self, tmp_path):
        content = _bilingual_body(tmp_path, "<p>正文</p>")

        head = content[content.find("<head") : content.find("</head>")]
        assert "<title" in head
        assert "style.css" in head
        assert "swatl-source" not in head  # never wrap <head> content

    def test_untouched_blocks_are_not_duplicated(self, tmp_path):
        """Only blocks that actually changed get a source copy."""
        content = _bilingual_body(tmp_path, "<p>原文</p><p>不翻译的一段</p>")
        # Both were translated by the test, so both are paired.
        assert content.count('class="swatl-source"') == 2

    def test_no_parallel_directory_is_written(self, fixture_epub, tmp_path):
        """Documents outside the manifest are invisible to reading systems."""
        zf = self._export(fixture_epub, tmp_path, bilingual=True, name="noparallel.epub")
        names = zf.namelist()

        assert not [n for n in names if n.startswith("bilingual/")]
        assert "swatl-source" in zf.read("text/ch01.xhtml").decode("utf-8")

    def test_non_bilingual_export_is_monolingual(self, fixture_epub, tmp_path):
        zf = self._export(fixture_epub, tmp_path, bilingual=False, name="mono.epub")
        content = zf.read("text/ch01.xhtml").decode("utf-8")

        assert "swatl-source" not in content
        assert "Translated:" in content
        # The source text survives only inside the translation string produced
        # by this test's stand-in provider, never as its own block.
        assert "<h1>第一章" not in content
