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
        segments, _ = extract_segments_from_doc("doc.xhtml", body)

        assert len(segments) == 9
        for seg in segments:
            matches = body.xpath(seg.anchor)
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
