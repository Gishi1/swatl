"""Tests for language-aware audit heuristics (Japanese support)."""

from swatl.audit.auditor import (
    CJK_UNIFIED,
    HIRAGANA,
    KATAKANA,
    _count_cjk_chars,
    _detect_cjk_residue,
    audit_segments,
)
from swatl.models import Segment


class TestCJKDetection:
    """Test CJK character detection regexes."""

    def test_cjk_unified_matches_kanji(self):
        """CJK Unified range should match Kanji."""
        text = "漢字テスト"
        assert len(CJK_UNIFIED.findall(text)) == 2  # 2 Kanji (漢, 字)

    def test_hiragana_matches_hiragana(self):
        """Hiragana range should match Hiragana characters."""
        text = "ひらがな"
        assert len(HIRAGANA.findall(text)) == 4

    def test_katakana_matches_katakana(self):
        """Katakana range should match Katakana characters."""
        text = "カクカク"
        assert len(KATAKANA.findall(text)) == 4

    def test_hiragana_does_not_match_kanji(self):
        """Hiragana pattern should not match Kanji."""
        text = "漢字"
        assert len(HIRAGANA.findall(text)) == 0

    def test_cjk_unified_does_not_match_hiragana(self):
        """CJK Unified range should not match Hiragana."""
        text = "ひらがな"
        assert len(CJK_UNIFIED.findall(text)) == 0


class TestDetectCjkResidue:
    """Test language-aware CJK residue detection."""

    def test_zh_source_flags_cjk_in_output(self):
        """zh→en: any CJK in output should be flagged."""
        text = "Hello 世界"
        result = _detect_cjk_residue(text, source_lang="zh")
        assert len(result) > 0
        assert "世" in result

    def test_ja_source_flags_hiragana_in_output(self):
        """ja→en: Hiragana in output should be flagged."""
        text = "Hello こんにちは"
        result = _detect_cjk_residue(text, source_lang="ja")
        assert any(c in result for c in "こんにちは")

    def test_ja_source_flags_katakana_in_output(self):
        """ja→en: Katakana in output should be flagged."""
        text = "Hello コンニチワ"
        result = _detect_cjk_residue(text, source_lang="ja")
        assert any(c in result for c in "コンニチワ")

    def test_ja_source_flags_kanji_in_output(self):
        """ja→en: Kanji in output should be flagged."""
        text = "Hello 日本"
        result = _detect_cjk_residue(text, source_lang="ja")
        assert any(c in result for c in "日本")

    def test_clean_english_no_residue_zh(self):
        """Clean English should not trigger CJK detection for zh source."""
        text = "Hello world, this is a test."
        result = _detect_cjk_residue(text, source_lang="zh")
        assert len(result) == 0

    def test_clean_english_no_residue_ja(self):
        """Clean English should not trigger CJK detection for ja source."""
        text = "Hello world, this is a test."
        result = _detect_cjk_residue(text, source_lang="ja")
        assert len(result) == 0


class TestCountCjkChars:
    """Test CJK character counting for length-ratio heuristics."""

    def test_zh_counts_kanji_only(self):
        """zh source should count only CJK Unified characters."""
        text = "こんにちは世界"  # 5 Hiragana + 2 Kanji
        # Hiragana not counted for zh
        assert _count_cjk_chars(text, source_lang="zh") == 2

    def test_ja_counts_all_japanese(self):
        """ja source should count Hiragana + Katakana + Kanji."""
        text = "こんにちは世界"  # 5 Hiragana + 2 Kanji
        assert _count_cjk_chars(text, source_lang="ja") == 7


class TestAuditSegmentsLanguageAware:
    """Test audit_segments with language-aware source_lang parameter."""

    def test_zh_audit_flags_cjk_residue(self):
        """zh→en: CJK residue should be detected."""
        seg = Segment(
            id="s1",
            doc="ch1",
            anchor="p[1]",
            tag="p",
            source_text="你好世界",
            translated="Hello 世界",
            status="translated",
        )
        report = audit_segments([seg], source_lang="zh")
        cjk_issues = [i for i in report.issues if i.type == "cjk_residue"]
        assert len(cjk_issues) == 1

    def test_ja_audit_flags_hiragana_residue(self):
        """ja→en: Hiragana residue should be detected."""
        seg = Segment(
            id="s1",
            doc="ch1",
            anchor="p[1]",
            tag="p",
            source_text="こんにちは世界",
            translated="Hello こんにちは",
            status="translated",
        )
        report = audit_segments([seg], source_lang="ja")
        cjk_issues = [i for i in report.issues if i.type == "cjk_residue"]
        assert len(cjk_issues) == 1

    def test_clean_translation_no_cjk_residue(self):
        """Clean translation should not flag CJK residue."""
        seg = Segment(
            id="s1",
            doc="ch1",
            anchor="p[1]",
            tag="p",
            source_text="你好世界",
            translated="Hello world",
            status="translated",
        )
        report = audit_segments([seg], source_lang="zh")
        cjk_issues = [i for i in report.issues if i.type == "cjk_residue"]
        assert len(cjk_issues) == 0

    def test_audit_respects_source_lang(self):
        """source_lang parameter should not affect audit when text is clean."""
        seg = Segment(
            id="s1",
            doc="ch1",
            anchor="p[1]",
            tag="p",
            source_text="Hello world",
            translated="Good day",
            status="translated",
        )
        report_zh = audit_segments([seg], source_lang="zh")
        report_ja = audit_segments([seg], source_lang="ja")
        # Both should have no CJK residue
        assert len(report_zh.issues) == 0
        assert len(report_ja.issues) == 0
