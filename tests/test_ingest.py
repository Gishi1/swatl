"""Tests for EPUB ingest: reader and segmenter."""

from pathlib import Path

import pytest
from lxml import html


class TestEpubReader:
    def test_epub_is_zip(self, fixture_epub):
        import zipfile

        assert zipfile.is_zipfile(fixture_epub)

    def test_extract_epub(self, fixture_epub, tmp_path):
        from swatl.ingest import EpubInfo, extract_epub

        info, epub_dir = extract_epub(fixture_epub, output_dir=tmp_path / "extracted")

        assert isinstance(info, EpubInfo)
        assert info.title == "三体"
        assert info.author == "刘慈欣"
        assert info.language == "zh"
        assert len(info.spine_items) == 3  # ch01, ch02, ch03
        assert epub_dir.exists()

    def test_container_xml_required(self, tmp_path):
        import zipfile

        from swatl.ingest import extract_epub

        # Create an empty zip (no container.xml)
        empty_epub = tmp_path / "empty.epub"
        with zipfile.ZipFile(empty_epub, "w"):
            pass  # empty zip

        with pytest.raises(ValueError, match="container.xml"):
            extract_epub(empty_epub, output_dir=tmp_path / "out")

    def test_not_a_zip(self, tmp_path):
        from swatl.ingest import extract_epub

        bad_epub = tmp_path / "notepub.txt"
        bad_epub.write_text("not a zip")

        with pytest.raises(ValueError, match="ZIP"):
            extract_epub(bad_epub, output_dir=tmp_path / "out")


class TestSegmenter:
    def test_extract_segments_from_doc(self):
        from swatl.ingest.segmenter import extract_segments_from_doc

        html_content = """<html>
        <body>
            <h1>第一章</h1>
            <p>三体是一个宏大的概念。</p>
            <p>人类面临前所未有的挑战。</p>
            <blockquote><p>宇宙很大，生活更大。</p></blockquote>
            <script>var x = 1;</script>
            <style>.foo { color: red; }</style>
        </body>
        </html>"""

        body = html.fromstring(html_content)
        segments, counter = extract_segments_from_doc("ch01.xhtml", body)

        # Should have h1, 2x p, blockquote > p = 4 segments
        # script and style should be skipped
        assert len(segments) == 4
        assert segments[0].tag == "h1"
        assert segments[0].source_text == "第一章"
        assert segments[1].tag == "p"
        assert segments[1].source_text == "三体是一个宏大的概念。"
        assert segments[2].tag == "p"
        assert segments[2].source_text == "人类面临前所未有的挑战。"
        assert segments[3].tag == "p"  # blockquote content
        assert segments[3].source_text == "宇宙很大，生活更大。"

    def test_skips_empty_elements(self):
        from swatl.ingest.segmenter import extract_segments_from_doc

        html_content = """<html>
        <body>
            <p>   </p>
            <p>有内容</p>
            <h2></h2>
        </body>
        </html>"""

        body = html.fromstring(html_content)
        segments, _ = extract_segments_from_doc("ch01.xhtml", body)

        assert len(segments) == 1
        assert segments[0].source_text == "有内容"

    def test_extract_segments_from_epub(self, fixture_epub):
        from swatl.ingest import extract_epub, extract_segments_from_epub

        info, epub_dir = extract_epub(fixture_epub)
        segments, doc_count = extract_segments_from_epub(
            epub_dir, info.spine_items, info.mime_types, info.language
        )

        assert len(segments) > 0
        assert doc_count == 3  # 3 chapters

        # Check that segments contain Chinese text
        chinese_count = sum(
            1 for s in segments if any("\u4e00" <= c <= "\u9fff" for c in s.source_text)
        )
        assert chinese_count > 0

    def test_fixture_segment_ids_are_stable(self, fixture_epub):
        """Segment IDs should be stable across extractions."""
        from swatl.ingest import extract_epub, extract_segments_from_epub

        info1, dir1 = extract_epub(fixture_epub)
        segs1, _ = extract_segments_from_epub(
            dir1, info1.spine_items, info1.mime_types, info1.language
        )

        # Extract again into a fresh dir
        import tempfile

        info2, dir2 = extract_epub(fixture_epub, output_dir=Path(tempfile.mkdtemp()))
        segs2, _ = extract_segments_from_epub(
            dir2, info2.spine_items, info2.mime_types, info2.language
        )

        ids1 = [s.id for s in segs1]
        ids2 = [s.id for s in segs2]
        assert ids1 == ids2


class TestAnchorResolution:
    """Every generated anchor must resolve back to the element it came from.

    Write-back resolves anchors with ``body.xpath(anchor)``, so an anchor that
    only *looks* right silently drops a paragraph from the exported book.
    """

    def _doc_with_nested_paragraphs(self, tmp_path):
        from lxml import html as lhtml

        doc = tmp_path / "doc.xhtml"
        doc.write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>t</title></head>
<body>
  <h1>标题一</h1>
  <p>第一段</p>
  <p>第二段</p>
  <blockquote><p>引用段落</p></blockquote>
  <h2>小节</h2>
  <p>第三段</p>
  <p>第四段</p>
  <ul><li>列表一</li><li>列表二</li></ul>
</body></html>""",
            encoding="utf-8",
        )
        tree = lhtml.parse(str(doc))
        return tree.find(".//body")

    def test_every_anchor_resolves_to_its_source_text(self, tmp_path):

        from swatl.ingest.segmenter import extract_segments_from_doc

        body = self._doc_with_nested_paragraphs(tmp_path)
        root = body.getroottree().getroot()
        segments, _ = extract_segments_from_doc("doc.xhtml", body)

        # 9 body elements + the document <title>
        assert len(segments) == 10
        assert [s.tag for s in segments].count("title") == 1
        for seg in segments:
            context = root if seg.anchor.startswith("/") else body
            matches = context.xpath(seg.anchor)
            assert matches, f"anchor did not resolve: {seg.id} -> {seg.anchor}"
            assert matches[0].text.strip() == seg.source_text

    def test_anchor_is_not_confused_by_nested_elements(self, tmp_path):
        from swatl.ingest.segmenter import extract_segments_from_doc

        body = self._doc_with_nested_paragraphs(tmp_path)
        segments, _ = extract_segments_from_doc("doc.xhtml", body)
        anchors = [s.anchor for s in segments]
        assert len(set(anchors)) == len(anchors), anchors
        # The paragraph inside <blockquote> must not consume a body-level index.
        assert ".//blockquote[1]/p[1]" in anchors
        assert ".//p[4]" in anchors


class TestNavigationAndTitleSegmentation:
    """EPUB3 nav documents and <title> elements must be translatable."""

    def _extract(self, tmp_path):
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent))
        from fixtures.create_fixture import create_epub3_fixture
        from swatl.ingest import extract_epub, extract_segments_from_epub

        book = create_epub3_fixture(tmp_path / "book3.epub")
        info, epub_dir = extract_epub(book)
        segments, doc_count = extract_segments_from_epub(
            epub_dir,
            info.spine_items,
            info.mime_types,
            info.language,
            extra_docs=info.nav_items,
        )
        return info, epub_dir, segments, doc_count

    def test_nav_document_is_detected(self, tmp_path):
        info, _dir, _segs, _n = self._extract(tmp_path)
        assert info.nav_items == ["nav.xhtml"]
        assert "nav.xhtml" not in info.spine_items

    def test_nav_and_title_are_segmented(self, tmp_path):
        _info, _dir, segments, doc_count = self._extract(tmp_path)
        assert doc_count == 2

        docs = {s.doc for s in segments}
        assert docs == {"text/ch01.xhtml", "nav.xhtml"}

        # Link text inside the nav document is extracted.
        nav_links = [s for s in segments if s.doc == "nav.xhtml" and s.tag == "a"]
        assert [s.source_text for s in nav_links] == ["第一章：三体世界"]

        # Document titles are extracted with an absolute anchor.
        titles = [s for s in segments if s.tag == "title"]
        assert {s.doc for s in titles} == {"text/ch01.xhtml", "nav.xhtml"}
        assert all(s.anchor.startswith("/html") for s in titles)

    def test_every_anchor_resolves_including_titles(self, tmp_path):
        from lxml import html as lhtml

        _info, epub_dir, segments, _n = self._extract(tmp_path)
        for doc in {s.doc for s in segments}:
            tree = lhtml.parse(str(epub_dir / doc))
            root = tree.getroot()
            body = tree.find(".//body")
            for seg in [s for s in segments if s.doc == doc]:
                context = root if seg.anchor.startswith("/") else body
                matches = context.xpath(seg.anchor)
                assert matches, f"{seg.id} anchor did not resolve: {seg.anchor}"
                assert matches[0].text.strip() == seg.source_text

    def test_spine_ids_are_stable_without_nav(self, tmp_path):
        """Adding a nav document must not renumber spine segments."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent))
        from fixtures.create_fixture import create_epub3_fixture
        from swatl.ingest import extract_epub, extract_segments_from_epub

        book = create_epub3_fixture(tmp_path / "book3.epub")
        info, epub_dir = extract_epub(book)
        with_nav, _ = extract_segments_from_epub(
            epub_dir, info.spine_items, info.mime_types, info.language, extra_docs=info.nav_items
        )
        without_nav, _ = extract_segments_from_epub(
            epub_dir, info.spine_items, info.mime_types, info.language
        )
        spine_ids_with = [s.id for s in with_nav if s.doc == "text/ch01.xhtml"]
        spine_ids_without = [s.id for s in without_nav if s.doc == "text/ch01.xhtml"]
        assert spine_ids_with == spine_ids_without


class TestInlineTailsAndEncoding:
    """Inline tails must be segmented, and parsing must not assume Latin-1."""

    def _doc(self, tmp_path, text: str, declared: bool = False):
        doc = tmp_path / "d.xhtml"
        meta = '<meta charset="UTF-8"/>' if declared else ""
        doc.write_text(
            f"<html><head>{meta}<title>标题</title></head><body>{text}</body></html>",
            encoding="utf-8",
        )
        return doc

    def test_utf8_without_declaration_is_not_mangled(self, tmp_path):
        from swatl.ingest.segmenter import extract_segments_from_doc, parse_xhtml

        doc = self._doc(tmp_path, "<p>点击这里继续</p>", declared=False)
        body = parse_xhtml(doc).find(".//body")
        segments, _ = extract_segments_from_doc("d.xhtml", body)
        assert [s.source_text for s in segments if s.tag == "p"] == ["点击这里继续"]

    def test_declared_charset_is_honoured(self, tmp_path):
        from swatl.ingest.segmenter import extract_segments_from_doc, parse_xhtml

        doc = self._doc(tmp_path, "<p>点击这里继续</p>", declared=True)
        body = parse_xhtml(doc).find(".//body")
        segments, _ = extract_segments_from_doc("d.xhtml", body)
        assert [s.source_text for s in segments if s.tag == "p"] == ["点击这里继续"]

    def test_tail_after_inline_element_is_segmented(self, tmp_path):
        from swatl.ingest.segmenter import TAIL_MARKER, extract_segments_from_doc, parse_xhtml

        doc = self._doc(tmp_path, "<p>点击<em>这里</em>继续阅读。</p>")
        body = parse_xhtml(doc).find(".//body")
        segments, _ = extract_segments_from_doc("d.xhtml", body)

        parts = {(s.tag, s.part): s.source_text for s in segments}
        assert parts[("p", "text")] == "点击"
        assert parts[("em", "text")] == "这里"
        assert parts[("em", "tail")] == "继续阅读。"

        tails = [s for s in segments if s.part == "tail"]
        assert len(tails) == 1
        assert tails[0].anchor.endswith(TAIL_MARKER)

    def test_whitespace_only_tail_is_ignored(self, tmp_path):
        from swatl.ingest.segmenter import extract_segments_from_doc, parse_xhtml

        doc = self._doc(tmp_path, "<p>文字<em>强调</em>  <span>另一段</span></p>")
        body = parse_xhtml(doc).find(".//body")
        segments, _ = extract_segments_from_doc("d.xhtml", body)
        assert [s for s in segments if s.part == "tail"] == []

    def test_tail_after_void_element_is_segmented(self, tmp_path):
        """Text after <br/> or <img/> has no other anchor and used to be lost.

        Neither element can hold text, so the parent's own text node stops at
        the first child; without a tail segment the second half of the paragraph
        stayed in Chinese inside an otherwise translated book.
        """
        from swatl.ingest.segmenter import extract_segments_from_doc, parse_xhtml

        doc = self._doc(
            tmp_path,
            "<p>第一行<br/>第二行</p><p>文字<img src='i.png'/>后面的文字</p>",
        )
        body = parse_xhtml(doc).find(".//body")
        segments, _ = extract_segments_from_doc("d.xhtml", body)

        by_tag: dict[tuple[str, str], str] = {(s.tag, s.part): s.source_text for s in segments}
        assert by_tag[("p", "text")] == "文字"
        assert by_tag[("br", "tail")] == "第二行"
        assert by_tag[("img", "tail")] == "后面的文字"

    def test_tail_after_script_is_segmented(self, tmp_path):
        """The text after a skipped element is still content."""
        from swatl.ingest.segmenter import extract_segments_from_doc, parse_xhtml

        doc = self._doc(tmp_path, "<p>保留<script>var x = 1;</script>脚本后的文字</p>")
        body = parse_xhtml(doc).find(".//body")
        segments, _ = extract_segments_from_doc("d.xhtml", body)

        by_tag = {(s.tag, s.part): s.source_text for s in segments}
        assert by_tag[("p", "text")] == "保留"
        assert by_tag[("script", "tail")] == "脚本后的文字"
        assert ("script", "text") not in by_tag  # the script body is untouched

    def test_skipped_subtree_is_not_segmented(self, tmp_path):
        """Nothing inside <svg> is translated, but the text after it is."""
        from swatl.ingest.segmenter import extract_segments_from_doc, parse_xhtml

        doc = self._doc(
            tmp_path,
            "<p>图标<svg><text>SVG文字</text><tspan>内部</tspan></svg>图后的文字</p>",
        )
        body = parse_xhtml(doc).find(".//body")
        segments, _ = extract_segments_from_doc("d.xhtml", body)

        texts = [s.source_text for s in segments]
        assert "SVG文字" not in texts
        assert "内部" not in texts
        assert "图后的文字" in texts

    def test_block_tail_is_segmented(self, tmp_path):
        """A block element's tail is content of its parent, not of the block."""
        from swatl.ingest.segmenter import extract_segments_from_doc, parse_xhtml

        doc = self._doc(tmp_path, "<div>块前<p>段落</p>块后</div>")
        body = parse_xhtml(doc).find(".//body")
        segments, _ = extract_segments_from_doc("d.xhtml", body)

        # Exclude the document <title>, which is segmented separately.
        texts = [s.source_text for s in segments if s.tag != "title"]
        assert texts == ["块前", "段落", "块后"]


class TestEpub2NcxSegmentation:
    """EPUB2 tables of contents (toc.ncx) must be translated too.

    Readers show these labels in the contents list, so leaving them in the
    source language gives an English book with a Chinese table of contents.
    """

    @staticmethod
    def _extract(fixture_epub):
        from swatl.ingest import extract_epub, extract_segments_from_epub

        info, epub_dir = extract_epub(fixture_epub)
        segments, doc_count = extract_segments_from_epub(
            epub_dir,
            info.spine_items,
            info.mime_types,
            info.language,
            extra_docs=info.nav_items + info.ncx_items,
        )
        return info, epub_dir, segments, doc_count

    def test_ncx_is_detected(self, fixture_epub):
        info, _epub_dir, _segments, _docs = self._extract(fixture_epub)
        assert info.ncx_items == ["toc.ncx"]

    def test_ncx_is_not_mistaken_for_xhtml(self, fixture_epub):
        """NCX is XML: the HTML parser would drop its namespace."""
        info, _epub_dir, _segments, _docs = self._extract(fixture_epub)
        assert "toc.ncx" not in info.nav_items
        assert "toc.ncx" not in info.spine_items

    def test_doc_title_and_nav_labels_are_segmented(self, fixture_epub):
        _info, _epub_dir, segments, _docs = self._extract(fixture_epub)
        ncx = [s for s in segments if s.doc == "toc.ncx"]

        assert [s.tag for s in ncx] == ["docTitle", "navLabel", "navLabel", "navLabel"]
        assert ncx[0].source_text == "三体"
        assert ncx[1].source_text == "第一章：三体世界"
        assert [s.source_text for s in ncx] == [
            "三体",
            "第一章：三体世界",
            "第二章：倒计时",
            "第三章：回答",
        ]

    def test_ncx_anchors_resolve_back_to_the_text_nodes(self, fixture_epub):
        """The anchor must be resolvable, or the label is never written back."""
        from swatl.ingest.segmenter import parse_xml

        _info, epub_dir, segments, _docs = self._extract(fixture_epub)
        root = parse_xml(epub_dir / "toc.ncx").getroot()

        for seg in segments:
            if seg.doc != "toc.ncx":
                continue
            found = root.xpath(seg.anchor)
            assert len(found) == 1, f"{seg.id}: {seg.anchor} matched {len(found)} nodes"
            assert (found[0].text or "").strip() == seg.source_text

    def test_ncx_labels_are_written_back_as_xml(self, fixture_epub, tmp_path):
        """The exported NCX stays XML with its namespace and structure."""
        import zipfile

        from lxml import etree

        from swatl.writeback import writeback_segments

        _info, epub_dir, segments, _docs = self._extract(fixture_epub)
        for seg in segments:
            if seg.doc == "toc.ncx":
                seg.translated = "EN " + seg.source_text
                seg.status = "translated"

        out = writeback_segments(
            epub_dir, segments, target_lang="en", output_path=tmp_path / "o.epub"
        )
        with zipfile.ZipFile(out) as zf:
            raw = zf.read("toc.ncx")

        text = raw.decode("utf-8")
        assert "<html" not in text.lower()  # not rewritten as a web page
        root = etree.fromstring(raw)
        ns = {"n": "http://www.daisy.org/z3986/2005/ncx/"}
        assert root.findall(".//n:text", ns)[1].text == "EN 第一章：三体世界"
        # Structure that readers depend on is untouched.
        assert len(root.findall(".//n:navPoint", ns)) == 3
        assert [c.get("src") for c in root.findall(".//n:content", ns)] == [
            "text/ch01.xhtml",
            "text/ch02.xhtml",
            "text/ch03.xhtml",
        ]
