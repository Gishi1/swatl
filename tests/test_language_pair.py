"""Tests for language-pair-specific prompt instructions."""

from swatl.translate.prompt_builder import (
    LANGUAGE_PAIR_INSTRUCTIONS,
    build_translation_prompt,
)


class TestLanguagePairInstructions:
    """Test that language-pair instructions are correctly applied."""

    def test_zh_to_en_instructions(self):
        """zh→en should include Chinese-specific notes."""
        prompt = build_translation_prompt("zh", "en")
        assert "Simplified Chinese to English" in prompt
        assert "no spaces between words" in prompt
        assert "pinyin" in prompt
        assert "measure words" in prompt

    def test_ja_to_en_instructions(self):
        """ja→en should include Japanese-specific notes."""
        prompt = build_translation_prompt("ja", "en")
        assert "Japanese to English" in prompt
        assert "Hiragana" in prompt
        assert "Katakana" in prompt
        assert "Kanji" in prompt
        assert "honorifics" in prompt
        assert "Romaji" in prompt
        assert "topic markers" in prompt

    def test_en_to_zh_instructions(self):
        """en→zh should include reverse-direction notes."""
        prompt = build_translation_prompt("en", "zh")
        assert "English to Simplified Chinese" in prompt

    def test_en_to_ja_instructions(self):
        """en→ja should include Japanese target notes."""
        prompt = build_translation_prompt("en", "ja")
        assert "English to Japanese" in prompt
        assert "Keigo" in prompt

    def test_unknown_pair_has_no_extra_instructions(self):
        """Unknown pair should not crash but has no extra instructions."""
        prompt = build_translation_prompt("fr", "de")
        assert "French" in prompt
        assert "German" in prompt
        # No language-pair specific note should appear
        assert "Hiragana" not in prompt
        assert "pinyin" not in prompt

    def test_all_supported_pairs_defined(self):
        """All expected pairs should be in LANGUAGE_PAIR_INSTRUCTIONS."""
        assert ("zh", "en") in LANGUAGE_PAIR_INSTRUCTIONS
        assert ("ja", "en") in LANGUAGE_PAIR_INSTRUCTIONS
        assert ("en", "zh") in LANGUAGE_PAIR_INSTRUCTIONS
        assert ("en", "ja") in LANGUAGE_PAIR_INSTRUCTIONS

    def test_instructions_combine_with_style(self):
        """Language-pair instructions should coexist with style guide."""
        prompt = build_translation_prompt("ja", "en", style="casual")
        assert "Hiragana" in prompt
        assert "conversational" in prompt

    def test_instructions_combine_with_glossary(self):
        """Language-pair instructions should coexist with glossary."""
        from swatl.models import Glossary, GlossaryEntry

        glossary = Glossary(entries=[GlossaryEntry(source="日本語", target="Japanese")])
        prompt = build_translation_prompt("ja", "en", glossary=glossary)
        assert "Hiragana" in prompt
        assert "Glossary" in prompt
        assert "日本語 → Japanese" in prompt
