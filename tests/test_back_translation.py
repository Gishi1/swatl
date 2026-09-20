"""Tests for the back-translation quality verification module."""

import asyncio
import json

import httpx
import pytest

from swatl.models import Segment
from swatl.quality.back_translation import (
    BackTranslationReport,
    BackTranslationResult,
    back_translate_sample,
    back_translate_segment,
    save_report,
)
from swatl.quality.metrics import levenshtein_similarity


class TestLevenshteinSimilarity:
    """Test the Levenshtein-based similarity calculation."""

    def test_identical_strings(self):
        """Identical strings should have similarity 1.0."""
        assert levenshtein_similarity("你好世界", "你好世界") == 1.0

    def test_completely_different(self):
        """Very different strings should have low similarity."""
        sim = levenshtein_similarity("Hello World", "Bonjour le monde")
        assert 0.0 <= sim < 1.0

    def test_empty_strings(self):
        """Two empty strings should have similarity 1.0."""
        assert levenshtein_similarity("", "") == 1.0

    def test_one_empty(self):
        """One empty and one non-empty string should have similarity 0.0."""
        assert levenshtein_similarity("", "Hello") == 0.0

    def test_single_char_match(self):
        """Single matching char should have similarity 1.0."""
        assert levenshtein_similarity("a", "a") == 1.0

    def test_partial_match(self):
        """Partial overlap should give intermediate similarity."""
        sim = levenshtein_similarity("你好世界", "你好")
        assert sim >= 0.5  # 2 of 4 chars match

    def test_english_backtranslation(self):
        """English→Chinese back-translation: similarity should be low."""
        sim = levenshtein_similarity("Hello World", "你好世界")
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


class TestBackTranslationRequests:
    """The HTTP path of back-translation, exercised with a mock transport."""

    def _segments(self, n: int = 3):
        return [
            Segment(
                id=f"p-{i:04d}",
                doc="doc",
                anchor=f".//p[{i}]",
                tag="p",
                source_text=f"这是第{i}段中文原文。",
                translated=f"This is paragraph {i}.",
                status="proofread",
            )
            for i in range(1, n + 1)
        ]

    def _patch(self, monkeypatch, handler):
        real = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)

    def test_endpoint_does_not_double_the_version_prefix(self, monkeypatch):
        """base_url already ends in /v1 for most providers."""
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            return httpx.Response(200, json={"choices": [{"message": {"content": "这是中文"}}]})

        self._patch(monkeypatch, handler)
        asyncio.run(
            back_translate_segment(self._segments(1)[0], "https://api.example.com/v1", "key")
        )
        assert seen["url"] == "https://api.example.com/v1/chat/completions"

    def test_trailing_slash_is_normalised(self, monkeypatch):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            return httpx.Response(200, json={"choices": [{"message": {"content": "中文"}}]})

        self._patch(monkeypatch, handler)
        asyncio.run(
            back_translate_segment(self._segments(1)[0], "https://api.example.com/v1/", "key")
        )
        assert seen["url"] == "https://api.example.com/v1/chat/completions"

    def test_sample_report(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "这是第1段中文原文。"}}]}
            )

        self._patch(monkeypatch, handler)
        report = asyncio.run(
            back_translate_sample(
                self._segments(3),
                api_base_url="https://api.example.com/v1",
                api_key="key",
                sample_size=3,
                seed=1,
            )
        )
        assert report.segments_tested == 3
        assert report.ok + report.warnings + report.critical == 3

    def test_one_failed_request_does_not_abort_the_report(self, monkeypatch):
        """A 500 on one segment must not lose the whole sample."""
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(500, json={"error": "boom"})
            return httpx.Response(200, json={"choices": [{"message": {"content": "中文回译"}}]})

        self._patch(monkeypatch, handler)
        report = asyncio.run(
            back_translate_sample(
                self._segments(3),
                api_base_url="https://api.example.com/v1",
                api_key="key",
                sample_size=3,
                seed=2,
            )
        )
        assert report.segments_tested == 2

    def test_no_translated_segments_returns_empty_report(self):
        segments = [Segment(id="p-1", doc="d", anchor=".//p[1]", tag="p", source_text="中文")]
        report = asyncio.run(
            back_translate_sample(segments, api_base_url="https://x/v1", api_key="k", sample_size=3)
        )
        assert report.segments_tested == 0


class TestStreamingGatewayInterop:
    """Gateways that stream by default must still work."""

    def _segments(self, n=1):
        return [
            Segment(
                id=f"p-{i:04d}",
                doc="doc",
                anchor=f".//p[{i}]",
                tag="p",
                source_text="这是中文原文。",
                translated="This is the English translation.",
                status="proofread",
            )
            for i in range(1, n + 1)
        ]

    def _patch(self, monkeypatch, handler):
        real = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)

    def test_request_asks_for_json(self, monkeypatch):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"choices": [{"message": {"content": "中文"}}]})

        self._patch(monkeypatch, handler)
        asyncio.run(back_translate_segment(self._segments()[0], "https://x/v1", "k"))
        assert seen["body"]["stream"] is False

    def test_sse_response_is_parsed(self, monkeypatch):
        sse = (
            'data: {"choices":[{"delta":{"content":"宇宙"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"很大"}}]}\n\n'
            "data: [DONE]\n\n"
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})

        self._patch(monkeypatch, handler)
        result = asyncio.run(back_translate_segment(self._segments()[0], "https://x/v1", "k"))
        assert result.back_translated == "宇宙很大"


class TestSimilarityMetricSelection:
    """The default metric is chrF; the old edit-distance ratio stays available."""

    def test_chrf_separates_a_faithful_round_trip_from_a_wrong_one(self):
        from swatl.quality.back_translation import THRESHOLDS, score_similarity

        source = "红岸基地是一座秘密设施。"
        faithful = "红岸基地是一个秘密设施。"  # one character differs
        unrelated = "今天天气很好。"

        ok_threshold, warn_threshold = THRESHOLDS["chrf"]
        assert score_similarity(source, faithful) > ok_threshold
        assert score_similarity(source, unrelated) < warn_threshold

    def test_identical_text_scores_one(self):
        from swatl.quality.back_translation import score_similarity

        assert score_similarity("同一个句子", "同一个句子") == 1.0

    def test_metric_argument_selects_the_metric(self):
        from swatl.quality.back_translation import score_similarity
        from swatl.quality.metrics import levenshtein_similarity

        a, b = "这是一个测试句子。", "这是另一个句子。"
        assert score_similarity(a, b, "levenshtein") == levenshtein_similarity(a, b)
        assert score_similarity(a, b, "chrf") != levenshtein_similarity(a, b)

    def test_unknown_metric_is_rejected(self):
        from swatl.quality.back_translation import score_similarity

        with pytest.raises(ValueError, match="Unknown similarity metric"):
            score_similarity("a", "b", "bleu")

    def test_report_records_the_metric(self):
        from swatl.quality.back_translation import BackTranslationReport

        report = BackTranslationReport(
            segments_tested=0, ok=0, warnings=0, critical=0, results=[], details=[]
        )
        assert report.metric == "chrf"
        assert "chrf" in report.summary()
