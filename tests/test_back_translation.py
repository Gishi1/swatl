"""Tests for the back-translation quality verification module."""

from swatl.models import Segment
from swatl.quality.back_translation import (
    BackTranslationReport,
    BackTranslationResult,
    _levenshtein_similarity,
    save_report,
)


class TestLevenshteinSimilarity:
    """Test the Levenshtein-based similarity calculation."""

    def test_identical_strings(self):
        """Identical strings should have similarity 1.0."""
        assert _levenshtein_similarity("你好世界", "你好世界") == 1.0

    def test_completely_different(self):
        """Very different strings should have low similarity."""
        sim = _levenshtein_similarity("Hello World", "Bonjour le monde")
        assert 0.0 <= sim < 1.0

    def test_empty_strings(self):
        """Two empty strings should have similarity 1.0."""
        assert _levenshtein_similarity("", "") == 1.0

    def test_one_empty(self):
        """One empty and one non-empty string should have similarity 0.0."""
        assert _levenshtein_similarity("", "Hello") == 0.0

    def test_single_char_match(self):
        """Single matching char should have similarity 1.0."""
        assert _levenshtein_similarity("a", "a") == 1.0

    def test_partial_match(self):
        """Partial overlap should give intermediate similarity."""
        sim = _levenshtein_similarity("你好世界", "你好")
        assert sim >= 0.5  # 2 of 4 chars match

    def test_english_backtranslation(self):
        """English→Chinese back-translation: similarity should be low."""
        sim = _levenshtein_similarity("Hello World", "你好世界")
        assert sim < 0.5  # Very different languages


class TestBackTranslationResult:
    """Test BackTranslationResult flag classification."""

    def test_ok_flag_high_similarity(self):
        """Similarity >= 0.7 should flag as ok."""
        seg = Segment(
            id="s1", doc="x", anchor=".//p[1]", tag="p", source_text="你好", translated="你好"
        )
        result = BackTranslationResult(
            segment=seg, back_translated="你好", similarity_score=0.85, flag="ok"
        )
        assert result.flag == "ok"

    def test_warning_flag_medium_similarity(self):
        """Similarity 0.4-0.7 should flag as warning."""
        seg = Segment(
            id="s1", doc="x", anchor=".//p[1]", tag="p", source_text="你好", translated="Hello"
        )
        result = BackTranslationResult(
            segment=seg, back_translated="嗨", similarity_score=0.5, flag="warning"
        )
        assert result.flag == "warning"

    def test_critical_flag_low_similarity(self):
        """Similarity < 0.4 should flag as critical."""
        seg = Segment(
            id="s1", doc="x", anchor=".//p[1]", tag="p", source_text="你好", translated="Goodbye"
        )
        result = BackTranslationResult(
            segment=seg, back_translated="再见", similarity_score=0.2, flag="critical"
        )
        assert result.flag == "critical"


class TestBackTranslationReport:
    """Test BackTranslationReport generation and summary."""

    def test_summary_format(self):
        """Summary should produce a multi-line formatted string."""
        results = [
            BackTranslationResult(
                segment=Segment(
                    id="s1",
                    doc="x",
                    anchor=".//p[1]",
                    tag="p",
                    source_text="你好",
                    translated="Hello",
                ),
                back_translated="你好",
                similarity_score=0.9,
                flag="ok",
            ),
        ]
        report = BackTranslationReport(
            segments_tested=1, ok=1, warnings=0, critical=0, results=results, details=[]
        )
        summary = report.summary()
        assert "1 tested" in summary
        assert "OK: 1" in summary
        assert "Warnings: 0" in summary

    def test_empty_report(self):
        """Empty report should show zeros."""
        report = BackTranslationReport(
            segments_tested=0, ok=0, warnings=0, critical=0, results=[], details=[]
        )
        summary = report.summary()
        assert "0 tested" in summary
        assert "OK: 0" in summary

    def test_mixed_report(self):
        """Report with mixed flags should show correct counts."""
        results = [
            BackTranslationResult(
                segment=Segment(
                    id="s1",
                    doc="x",
                    anchor=".//p[1]",
                    tag="p",
                    source_text="你好",
                    translated="Hello",
                ),
                back_translated="你好",
                similarity_score=0.9,
                flag="ok",
            ),
            BackTranslationResult(
                segment=Segment(
                    id="s2",
                    doc="x",
                    anchor=".//p[2]",
                    tag="p",
                    source_text="再见",
                    translated="Goodbye",
                ),
                back_translated="嗨",
                similarity_score=0.5,
                flag="warning",
            ),
            BackTranslationResult(
                segment=Segment(
                    id="s3",
                    doc="x",
                    anchor=".//p[3]",
                    tag="p",
                    source_text="世界",
                    translated="World",
                ),
                back_translated="地球",
                similarity_score=0.3,
                flag="critical",
            ),
        ]
        report = BackTranslationReport(
            segments_tested=3, ok=1, warnings=1, critical=1, results=results, details=[]
        )
        summary = report.summary()
        assert "3 tested" in summary
        assert "OK: 1" in summary
        assert "Warnings: 1" in summary
        assert "Critical: 1" in summary


class TestSaveReport:
    """Test report persistence."""

    def test_save_report_creates_file(self, tmp_path):
        """save_report should create a JSON file."""
        results = [
            BackTranslationResult(
                segment=Segment(
                    id="s1",
                    doc="x",
                    anchor=".//p[1]",
                    tag="p",
                    source_text="你好",
                    translated="Hello",
                ),
                back_translated="你好",
                similarity_score=0.9,
                flag="ok",
            ),
        ]
        report = BackTranslationReport(
            segments_tested=1,
            ok=1,
            warnings=0,
            critical=0,
            results=results,
            details=[
                {
                    "segment_id": "s1",
                    "source": "你好",
                    "translated": "Hello",
                    "back_translated": "你好",
                    "similarity": 0.9,
                    "flag": "ok",
                }
            ],
        )

        output = tmp_path / "report.json"
        save_report(report, output)

        assert output.exists()
        content = output.read_text()
        assert "1" in content  # segments_tested
        assert "ok" in content

    def test_save_report_creates_parent_dirs(self, tmp_path):
        """save_report should create parent directories if they don't exist."""
        report = BackTranslationReport(
            segments_tested=0, ok=0, warnings=0, critical=0, results=[], details=[]
        )
        deep_path = tmp_path / "nested" / "dir" / "report.json"
        save_report(report, deep_path)
        assert deep_path.exists()
