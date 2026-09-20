"""Tests for the writeback module."""

import asyncio
import zipfile


class TestWriteback:
    def test_writeback_creates_epub(self, fixture_epub, tmp_path):
        from swatl.ingest import extract_epub, extract_segments_from_epub
        from swatl.providers.mock import MockProvider
        from swatl.translate.translator import Translator
        from swatl.writeback.writer import writeback_segments

        # Extract and segment
        info, epub_dir = extract_epub(fixture_epub)
        segments, _ = extract_segments_from_epub(
            epub_dir, info.spine_items, info.mime_types, info.language
        )

        # Translate with mock
        provider = MockProvider(name="mock")
        trans = Translator(provider, "zh", "en")
        segments = asyncio.run(trans.translate_all(segments))

        # Write back
        output_path = tmp_path / "output.epub"
        result_path = writeback_segments(
            epub_dir, segments, target_lang="en", output_path=output_path
        )

        assert result_path.exists()
        assert result_path.suffix == ".epub"
        assert zipfile.is_zipfile(result_path)

    def test_writeback_preserves_structure(self, fixture_epub, tmp_path):
        """Non-text elements should be preserved in the output."""
        import asyncio

        from swatl.ingest import extract_epub, extract_segments_from_epub
        from swatl.providers.mock import MockProvider
        from swatl.translate.translator import Translator
        from swatl.writeback.writer import writeback_segments

        info, epub_dir = extract_epub(fixture_epub)
        segments, _ = extract_segments_from_epub(
            epub_dir, info.spine_items, info.mime_types, info.language
        )

        provider = MockProvider(name="mock")
        trans = Translator(provider, "zh", "en")
        segments = asyncio.run(trans.translate_all(segments))

        output_path = tmp_path / "output.epub"
        writeback_segments(epub_dir, segments, target_lang="en", output_path=output_path)

        # Check that the output EPUB has the expected files
        with zipfile.ZipFile(output_path, "r") as zf:
            names = zf.namelist()
            assert "content.opf" in names
            assert "style.css" in names
            assert "toc.ncx" in names
            assert "nav.xhtml" in names
            assert "images/cover.png" in names

    def test_writeback_translates_text(self, fixture_epub, tmp_path):
        """Translated text should appear in the output EPUB."""
        from swatl.ingest import extract_epub, extract_segments_from_epub
        from swatl.providers.mock import MockProvider
        from swatl.translate.translator import Translator
        from swatl.writeback.writer import writeback_segments

        info, epub_dir = extract_epub(fixture_epub)
        segments, _ = extract_segments_from_epub(
            epub_dir, info.spine_items, info.mime_types, info.language
        )

        provider = MockProvider(name="mock")
        trans = Translator(provider, "zh", "en")
        segments = asyncio.run(trans.translate_all(segments))

        output_path = tmp_path / "output.epub"
        writeback_segments(epub_dir, segments, target_lang="en", output_path=output_path)

        # Every segment's translation must be present verbatim in its document.
        # (Regression: the writer used to modify an in-memory tree and never
        # save it, so the exported EPUB stayed in Chinese.)
        with zipfile.ZipFile(output_path, "r") as zf:
            docs = {
                name: zf.read(name).decode("utf-8")
                for name in zf.namelist()
                if name.endswith((".xhtml", ".html", ".opf", ".ncx"))
            }
        for seg in segments:
            if not seg.translated:
                continue
            assert seg.translated in docs[seg.doc], f"missing translation for {seg.id}"

        # No CJK source text may survive in the translated body of chapter 1.
        ch1 = docs["text/ch01.xhtml"]
        body = ch1[ch1.index("<body") :]
        assert not any("\u4e00" <= c <= "\u9fff" for c in body), body

    def test_writeback_preserves_css(self, fixture_epub, tmp_path):
        """CSS should be byte-identical in output."""
        from swatl.ingest import extract_epub, extract_segments_from_epub
        from swatl.providers.mock import MockProvider
        from swatl.translate.translator import Translator
        from swatl.writeback.writer import writeback_segments

        info, epub_dir = extract_epub(fixture_epub)
        segments, _ = extract_segments_from_epub(
            epub_dir, info.spine_items, info.mime_types, info.language
        )

        provider = MockProvider(name="mock")
        trans = Translator(provider, "zh", "en")
        segments = asyncio.run(trans.translate_all(segments))

        output_path = tmp_path / "output.epub"
        writeback_segments(epub_dir, segments, target_lang="en", output_path=output_path)

        with zipfile.ZipFile(fixture_epub, "r") as zf_src:
            css_src = zf_src.read("style.css")
        with zipfile.ZipFile(output_path, "r") as zf_out:
            css_out = zf_out.read("style.css")

        assert css_src == css_out  # Byte-identical

    def test_writeback_preserves_image(self, fixture_epub, tmp_path):
        """Images should be byte-identical in output."""
        from swatl.ingest import extract_epub, extract_segments_from_epub
        from swatl.providers.mock import MockProvider
        from swatl.translate.translator import Translator
        from swatl.writeback.writer import writeback_segments

        info, epub_dir = extract_epub(fixture_epub)
        segments, _ = extract_segments_from_epub(
            epub_dir, info.spine_items, info.mime_types, info.language
        )

        provider = MockProvider(name="mock")
        trans = Translator(provider, "zh", "en")
        segments = asyncio.run(trans.translate_all(segments))

        output_path = tmp_path / "output.epub"
        writeback_segments(epub_dir, segments, target_lang="en", output_path=output_path)

        with zipfile.ZipFile(fixture_epub, "r") as zf_src:
            img_src = zf_src.read("images/cover.png")
        with zipfile.ZipFile(output_path, "r") as zf_out:
            img_out = zf_out.read("images/cover.png")

        assert img_src == img_out  # Byte-identical


class TestEpubConformance:
    """The exported EPUB must be structurally valid for real readers."""

    def _translate(self, fixture_epub):
        import asyncio

        from swatl.ingest import extract_epub, extract_segments_from_epub
        from swatl.providers.mock import MockProvider
        from swatl.translate.translator import Translator

        info, epub_dir = extract_epub(fixture_epub)
        segments, _ = extract_segments_from_epub(
            epub_dir, info.spine_items, info.mime_types, info.language
        )
        provider = MockProvider(name="mock")
        segments = asyncio.run(Translator(provider, "zh", "en").translate_all(segments))
        return epub_dir, segments

    def test_mimetype_is_first_and_stored(self, fixture_epub, tmp_path):
        from swatl.writeback.writer import writeback_segments

        epub_dir, segments = self._translate(fixture_epub)
        output_path = tmp_path / "output.epub"
        writeback_segments(epub_dir, segments, target_lang="en", output_path=output_path)

        with zipfile.ZipFile(output_path, "r") as zf:
            infos = zf.infolist()
            assert infos[0].filename == "mimetype"
            assert infos[0].compress_type == zipfile.ZIP_STORED
            assert zf.read("mimetype") == b"application/epub+zip"

    def test_no_stray_xml_declaration_comment(self, fixture_epub, tmp_path):
        from swatl.writeback.writer import writeback_segments

        epub_dir, segments = self._translate(fixture_epub)
        output_path = tmp_path / "output.epub"
        writeback_segments(epub_dir, segments, target_lang="en", output_path=output_path)

        with zipfile.ZipFile(output_path, "r") as zf:
            for name in zf.namelist():
                if name.endswith((".xhtml", ".html")):
                    content = zf.read(name)
                    assert b"<!--?xml" not in content, name


class TestPackageLanguage:
    """The exported package document must declare the target language."""

    def _export(self, fixture_epub, tmp_path):
        import asyncio

        from swatl.ingest import extract_epub, extract_segments_from_epub
        from swatl.providers.mock import MockProvider
        from swatl.translate.translator import Translator
        from swatl.writeback.writer import writeback_segments

        info, epub_dir = extract_epub(fixture_epub)
        segments, _ = extract_segments_from_epub(
            epub_dir, info.spine_items, info.mime_types, info.language
        )
        segments = asyncio.run(Translator(MockProvider(), "zh", "en").translate_all(segments))
        output_path = tmp_path / "output.epub"
        writeback_segments(epub_dir, segments, target_lang="en", output_path=output_path)
        return output_path

    def test_dc_language_updated_to_target(self, fixture_epub, tmp_path):
        output_path = self._export(fixture_epub, tmp_path)
        with zipfile.ZipFile(output_path) as zf:
            opf = zf.read("content.opf").decode("utf-8")
        assert "<dc:language>en</dc:language>" in opf
        assert "<dc:language>zh</dc:language>" not in opf

    def test_source_opf_is_not_modified_in_place(self, fixture_epub, tmp_path):
        """The extraction directory is scratch space, but the writer must only
        touch the extracted copy — never the user's original EPUB."""
        import zipfile as zf_mod

        before = zf_mod.ZipFile(fixture_epub).read("content.opf")
        self._export(fixture_epub, tmp_path)
        after = zf_mod.ZipFile(fixture_epub).read("content.opf")
        assert before == after


class TestNavigationWriteback:
    """Nav documents and <title> elements must be translated in the export."""

    def _export_epub3(self, tmp_path):
        import asyncio
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent))
        from fixtures.create_fixture import create_epub3_fixture
        from swatl.ingest import extract_epub, extract_segments_from_epub
        from swatl.providers.mock import MockProvider
        from swatl.translate.translator import Translator
        from swatl.writeback.writer import writeback_segments

        book = create_epub3_fixture(tmp_path / "book3.epub")
        info, epub_dir = extract_epub(book)
        segments, _ = extract_segments_from_epub(
            epub_dir,
            info.spine_items,
            info.mime_types,
            info.language,
            extra_docs=info.nav_items,
        )
        segments = asyncio.run(Translator(MockProvider(), "zh", "en").translate_all(segments))
        output_path = tmp_path / "output3.epub"
        writeback_segments(epub_dir, segments, target_lang="en", output_path=output_path)
        with zipfile.ZipFile(output_path) as zf:
            return {name: zf.read(name).decode("utf-8") for name in zf.namelist()}, segments

    def test_nav_document_translated(self, tmp_path):
        docs, _segments = self._export_epub3(tmp_path)
        nav = docs["nav.xhtml"]
        body = nav[nav.index("<body") :]
        assert not any("\u4e00" <= c <= "\u9fff" for c in body), body
        assert "char" in body  # mock translation marker

    def test_document_title_translated(self, tmp_path):
        docs, _segments = self._export_epub3(tmp_path)
        assert "<title>目录</title>" not in docs["nav.xhtml"]
        assert "第一章" not in docs["text/ch01.xhtml"]

    def test_spine_document_still_translated(self, tmp_path):
        docs, segments = self._export_epub3(tmp_path)
        chapter = docs["text/ch01.xhtml"]
        for seg in segments:
            if seg.doc == "text/ch01.xhtml" and seg.translated:
                assert seg.translated in chapter, seg.id


class TestInlineTailWriteback:
    """Text after an inline element must reach the exported EPUB."""

    def test_tail_is_written_back(self, tmp_path):
        import asyncio

        from lxml import html as lhtml

        from swatl.ingest.segmenter import extract_segments_from_doc, parse_xhtml
        from swatl.providers.mock import MockProvider
        from swatl.translate.translator import Translator
        from swatl.writeback.writer import _write_document

        doc = tmp_path / "d.xhtml"
        doc.write_text(
            "<html><head><title>标题</title></head><body>"
            "<p>点击<em>这里</em>继续阅读。</p>"
            "</body></html>",
            encoding="utf-8",
        )
        body = parse_xhtml(doc).find(".//body")
        segments, _ = extract_segments_from_doc("d.xhtml", body)

        tail_segs = [s for s in segments if s.part == "tail"]
        assert [s.source_text for s in tail_segs] == ["继续阅读。"]

        segments = asyncio.run(Translator(MockProvider(), "zh", "en").translate_all(segments))
        _write_document(doc, segments, "en")

        result = doc.read_text(encoding="utf-8")
        assert tail_segs[0].translated in result
        assert not any("\u4e00" <= c <= "\u9fff" for c in result)
        # The inline element survives.
        assert lhtml.fromstring(result.encode("utf-8")).find(".//em") is not None


class TestBilingualExport:
    """`--bilingual` must produce a valid, genuinely bilingual copy.

    The copy previously held the *translation* in both halves, replaced the
    document <title> with a wrapper <div> inside <head>, emitted two </body>
    tags, dropped the stylesheet, and raised XPathEvalError on every tail
    segment (silently, since the failure was swallowed).
    """

    @staticmethod
    def _bilingual_export(fixture_epub, tmp_path):
        import asyncio

        from swatl.ingest import extract_epub, extract_segments_from_epub
        from swatl.providers.mock import MockProvider
        from swatl.translate.translator import Translator
        from swatl.writeback.writer import writeback_segments

        info, epub_dir = extract_epub(fixture_epub)
        segments, _ = extract_segments_from_epub(
            epub_dir,
            info.spine_items,
            info.mime_types,
            info.language,
            extra_docs=info.nav_items + info.ncx_items,
        )
        segments = asyncio.run(
            Translator(MockProvider(name="mock"), "zh", "en").translate_all(segments)
        )
        out = writeback_segments(
            epub_dir, segments, target_lang="en", output_path=tmp_path / "bi.epub", bilingual=True
        )
        return zipfile.ZipFile(out)

    def test_copy_is_valid_xml_with_one_body(self, fixture_epub, tmp_path):
        from lxml import etree

        zf = self._bilingual_export(fixture_epub, tmp_path)
        raw = zf.read("text/ch01.xhtml")
        root = etree.fromstring(raw)
        assert root.tag.endswith("html")

        text = raw.decode()
        assert text.count("<body") == 1
        assert text.count("</body>") == 1
        # No wrapper inside <head>, where a <div> would be invalid.
        head = text[text.find("<head") : text.find("</head>")]
        assert "swatl-bilingual" not in head
        assert "<title>" in head

    def test_source_half_holds_the_original_and_target_the_translation(
        self, fixture_epub, tmp_path
    ):
        import re

        zf = self._bilingual_export(fixture_epub, tmp_path)
        text = zf.read("text/ch01.xhtml").decode()

        sources = re.findall(r'class="swatl-source"[^>]*>(.*?)</p>', text, re.DOTALL)
        targets = re.findall(r'class="swatl-target"[^>]*>(.*?)</p>', text, re.DOTALL)

        assert sources and targets
        assert len(sources) == len(targets)
        assert any("\u4e00" <= c <= "\u9fff" for s in sources for c in s), (
            "source half lost the Chinese"
        )
        assert not any("\u4e00" <= c <= "\u9fff" for t in targets for c in t)
        assert sources != targets

    def test_stylesheet_and_language_survive(self, fixture_epub, tmp_path):
        zf = self._bilingual_export(fixture_epub, tmp_path)
        text = zf.read("text/ch01.xhtml").decode()
        assert "style.css" in text
        assert 'xml:lang="en"' in text

    def test_bilingual_documents_are_the_reading_order(self, fixture_epub, tmp_path):
        """The side-by-side documents replace the spine content, so readers show them.

        Nothing is written to a parallel directory, because files outside the
        package manifest are invisible to reading systems.
        """
        zf = self._bilingual_export(fixture_epub, tmp_path)
        names = zf.namelist()
        assert not [n for n in names if n.startswith("bilingual/")]
        assert "swatl-bilingual" in zf.read("text/ch01.xhtml").decode()
        # Other spine documents are bilingual too.
        assert "swatl-bilingual" in zf.read("text/ch02.xhtml").decode()

    def test_ncx_is_still_translated_normally(self, fixture_epub, tmp_path):
        """The NCX has labels, not prose: it must not be wrapped in blocks."""
        zf = self._bilingual_export(fixture_epub, tmp_path)
        ncx = zf.read("toc.ncx").decode()
        assert "swatl-bilingual" not in ncx
        assert "<ncx" in ncx
