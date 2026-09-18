"""Tests for style guide support in prompt builder."""

from swatl.translate.prompt_builder import STYLE_GUIDES, build_translation_prompt


class TestStyleGuideSupport:
    """Test that style guide options are correctly applied to prompts."""

    def test_default_style_is_formal(self):
        """Default style should be 'formal'."""
        prompt = build_translation_prompt("zh", "en")
        assert STYLE_GUIDES["formal"] in prompt

    def test_casual_style_applied(self):
        """'casual' style should inject casual instructions."""
        prompt = build_translation_prompt("zh", "en", style="casual")
        assert STYLE_GUIDES["casual"] in prompt

    def test_literary_style_applied(self):
        """'literary' style should inject literary instructions."""
        prompt = build_translation_prompt("zh", "en", style="literary")
        assert STYLE_GUIDES["literary"] in prompt

    def test_technical_style_applied(self):
        """'technical' style should inject technical instructions."""
        prompt = build_translation_prompt("zh", "en", style="technical")
        assert STYLE_GUIDES["technical"] in prompt

    def test_unknown_style_defaults_to_formal(self):
        """Unknown style should fall back to formal."""
        prompt = build_translation_prompt("zh", "en", style="unknown_style")
        assert STYLE_GUIDES["formal"] in prompt

    def test_all_styles_defined(self):
        """All expected style keys should be defined."""
        assert "formal" in STYLE_GUIDES
        assert "casual" in STYLE_GUIDES
        assert "literary" in STYLE_GUIDES
        assert "technical" in STYLE_GUIDES

    def test_prompt_contains_language(self):
        """Prompt should still contain language info regardless of style."""
        prompt = build_translation_prompt("zh", "en", style="casual")
        assert "Chinese" in prompt
        assert "English" in prompt

    def test_prompt_with_style_and_glossary(self):
        """Style and glossary should coexist in prompt."""
        from swatl.models import Glossary, GlossaryEntry

        glossary = Glossary(entries=[GlossaryEntry(source="你好", target="Hello")])
        prompt = build_translation_prompt("zh", "en", glossary=glossary, style="literary")
        assert STYLE_GUIDES["literary"] in prompt
        assert "Glossary" in prompt
        assert "你好 → Hello" in prompt

    def test_prompt_with_style_and_context(self):
        """Style and context should coexist in prompt."""
        prompt = build_translation_prompt("zh", "en", style="formal", context="[s1] 你好 → Hello")
        assert STYLE_GUIDES["formal"] in prompt
        assert "s1" in prompt
