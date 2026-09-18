"""Tests for prompt builder and translator."""

from swatl.models import Glossary, GlossaryEntry, Segment
from swatl.providers.mock import MockProvider
from swatl.translate.prompt_builder import (
    build_context_window,
    build_proofread_prompt,
    build_translation_prompt,
)
from swatl.translate.translator import Translator, parse_json_response


class TestPromptBuilder:
    def test_translation_prompt_basic(self):
        prompt = build_translation_prompt("zh", "en")
        assert "Chinese → English translator" in prompt
        assert "Return JSON" in prompt

    def test_translation_prompt_with_glossary(self):
        glossary = Glossary(entries=[GlossaryEntry(source="三体", target="Three-Body")])
        prompt = build_translation_prompt("zh", "en", glossary=glossary)
        assert "三体 → Three-Body" in prompt

    def test_translation_prompt_with_context(self):
        context = "p-0001: 三体 → Three-Body"
        prompt = build_translation_prompt("zh", "en", context=context)
        assert context in prompt

    def test_proofread_prompt(self):
        prompt = build_proofread_prompt()
        assert "proofreader" in prompt.lower()
        assert "Return JSON" in prompt

    def test_build_context_window(self):
        segments = [
            Segment(
                id="p-0001",
                doc="d",
                anchor=".//p[1]",
                tag="p",
                source_text="A",
                translated="A-trans",
                status="translated",
            ),
            Segment(
                id="p-0002",
                doc="d",
                anchor=".//p[2]",
                tag="p",
                source_text="B",
                translated="B-trans",
                status="translated",
            ),
            Segment(
                id="p-0003", doc="d", anchor=".//p[3]", tag="p", source_text="C", status="pending"
            ),
        ]
        window = build_context_window(segments, n_previous=2)
        assert "p-0001" in window
        assert "p-0002" in window
        assert "p-0003" not in window

    def test_build_context_window_empty(self):
        segments = [
            Segment(
                id="p-0003", doc="d", anchor=".//p[3]", tag="p", source_text="C", status="pending"
            ),
        ]
        window = build_context_window(segments, n_previous=3)
        assert window == ""


class TestParseJsonResponse:
    def test_direct_json(self):
        result = parse_json_response('{"translated": "hello"}')
        assert result == {"translated": "hello"}

    def test_markdown_wrapped(self):
        result = parse_json_response('```\n{"translated": "hello"}\n```')
        assert result == {"translated": "hello"}

    def test_plain_text_no_json(self):
        result = parse_json_response("Just a plain text response")
        assert result is None

    def test_empty(self):
        result = parse_json_response("")
        assert result is None


class TestEstimateTokens:
    def test_estimate_tokens_zh(self):
        segments = [
            Segment(
                id="p-0001",
                doc="d",
                anchor=".//p[1]",
                tag="p",
                source_text="三体是一个宏大的概念。",
            ),  # ~13 CJK + punctuation
        ]
        t_in, t_out = Translator(MockProvider(), "zh", "en").estimate_tokens(segments)
        assert t_in > 0
        assert t_out > 0
        # zh input should be more tokens than ASCII (CJK ≈ 1 token/char)
        assert t_in >= t_out
