"""Tests for the mock provider and translation flow."""

from swatl.models import Glossary, GlossaryEntry, Segment
from swatl.providers.mock import MockProvider, _mock_translate


class TestMockProvider:
    async def test_translate_basic(self):
        provider = MockProvider(name="mock")
        segments = [
            Segment(
                id="p-0001",
                doc="doc",
                anchor=".//p[1]",
                tag="p",
                source_text="三体是一个宏大的概念。",
            ),
            Segment(
                id="p-0002", doc="doc", anchor=".//p[2]", tag="p", source_text="人类面临挑战。"
            ),
        ]

        result = await provider.translate(segments)
        assert len(result) == 2
        assert all(s.status == "translated" for s in result)
        assert all(s.translated for s in result)
        assert all(s.provider == "mock" for s in result)

    async def test_translate_with_glossary(self):
        provider = MockProvider(name="mock")
        glossary = Glossary(
            entries=[
                GlossaryEntry(source="三体", target="Three-Body"),
            ]
        )
        segments = [
            Segment(
                id="p-0001",
                doc="doc",
                anchor=".//p[1]",
                tag="p",
                source_text="三体是一个宏大的概念。",
            ),
        ]

        result = await provider.translate(segments, glossary=glossary)
        # Glossary terms should appear in the translation
        assert "Three-Body" in result[0].translated

    async def test_proofread_basic(self):
        provider = MockProvider(name="mock")
        segments = [
            Segment(
                id="p-0001",
                doc="doc",
                anchor=".//p[1]",
                tag="p",
                source_text="三体",
                translated="Translated text",
            ),
        ]

        result = await provider.proofread(segments)
        assert result[0].status == "proofread"
        assert "[proofread]" in result[0].translated

    async def test_test_connectivity(self):
        provider = MockProvider(name="mock")
        result = await provider.test()
        assert result["ok"] is True


class TestMockTranslate:
    def test_cjk_translation(self):
        result = _mock_translate("三体", None)
        assert "char" in result  # mock produces "charXX" pattern

    def test_ascii_translation(self):
        result = _mock_translate("Hello world", None)
        assert result == "Translated: Hello world"

    def test_glossary_injection(self):
        glossary = Glossary(entries=[GlossaryEntry(source="三体", target="Three-Body")])
        result = _mock_translate("三体世界", glossary)
        assert "[Three-Body]" in result
