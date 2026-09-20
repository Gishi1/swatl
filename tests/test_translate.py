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


def test_translate_all_updates_originals_by_id():
    """Every returned segment must be reflected back on the original object.

    The in-place update used to scan the whole list per result (O(n²)).
    """
    import asyncio

    from swatl.models import Segment
    from swatl.providers.mock import MockProvider
    from swatl.translate.translator import Translator

    segments = [
        Segment(id=f"p-{i:04d}", doc="d", anchor=f".//p[{i}]", tag="p", source_text=f"第{i}段中文")
        for i in range(1, 41)
    ]
    result = asyncio.run(Translator(MockProvider(), "zh", "en").translate_all(segments))

    assert len(result) == 40
    for original, updated in zip(segments, result, strict=True):
        assert original is updated
        assert original.translated
        assert original.status == "translated"


def test_glossary_hits_are_recorded():
    """Glossary terms found in a segment are recorded on the segment."""
    import asyncio

    from swatl.models import Glossary, GlossaryEntry, Segment
    from swatl.providers.mock import MockProvider
    from swatl.translate.translator import Translator

    segments = [
        Segment(id="p-0001", doc="d", anchor=".//p[1]", tag="p", source_text="三体世界的故事")
    ]
    glossary = Glossary(entries=[GlossaryEntry(source="三体", target="Three-Body")])
    result = asyncio.run(Translator(MockProvider(), "zh", "en").translate_all(segments, glossary))

    seg = result[0]
    assert "Three-Body" in (seg.translated or "")
    assert seg.glossary_hits == ["三体"]


class TestTranslationMemoryLanguageScoping:
    """A memory file must not serve another language's cached text."""

    @staticmethod
    def _seg() -> Segment:
        return Segment(
            id="p-0001",
            doc="d",
            anchor="./p[1]",
            tag="p",
            source_text="红岸基地",
            translated="Red Coast Base",
            status="translated",
        )

    def test_entries_are_scoped_to_the_target_language(self, tmp_path):
        from swatl.translate.translation_memory import TranslationMemory

        memory_file = tmp_path / "tm.json"
        english = TranslationMemory(memory_file, source_lang="zh", target_lang="en")
        english.add(self._seg())
        english.save_disk_cache()

        # Reusing the same file for another target must not return English.
        french = TranslationMemory(memory_file, source_lang="zh", target_lang="fr")
        assert french.lookup(self._seg()) is None

        # The original direction still hits.
        again = TranslationMemory(memory_file, source_lang="zh", target_lang="en")
        assert again.lookup(self._seg()) == "Red Coast Base"

    def test_source_language_is_part_of_the_key(self, tmp_path):
        from swatl.translate.translation_memory import TranslationMemory

        memory_file = tmp_path / "tm.json"
        zh = TranslationMemory(memory_file, source_lang="zh", target_lang="en")
        zh.add(self._seg())
        zh.save_disk_cache()

        ja = TranslationMemory(memory_file, source_lang="ja", target_lang="en")
        assert ja.lookup(self._seg()) is None


class TestMockProviderGlossaryMarkers:
    """The offline test provider must not leak its internal markers."""

    def test_ascii_term_marker_is_unwrapped(self):
        from swatl.providers.mock import _mock_translate

        glossary = Glossary(
            name="t",
            pair=["zh", "en"],
            entries=[GlossaryEntry(source="Sophon", target="Zhi Zi")],
        )
        result = _mock_translate("The Sophon is here.", glossary)

        assert "<<" not in result
        assert "[Zhi Zi]" in result

    def test_cjk_text_still_uses_markers(self):
        from swatl.providers.mock import _mock_translate

        glossary = Glossary(
            name="t",
            pair=["zh", "en"],
            entries=[GlossaryEntry(source="红岸基地", target="Red Coast Base")],
        )
        result = _mock_translate("红岸基地。", glossary)

        assert "<<" not in result
        assert "[Red Coast Base]" in result
