"""Prompt builder: assemble system prompts, context windows, and glossary injection."""

from __future__ import annotations

from swatl.models import Glossary, Segment

STYLE_GUIDES = {
    "formal": (
        "Use formal, professional language suitable for academic, legal, or business contexts. "
        "Maintain a respectful and authoritative tone. Avoid contractions, slang, and colloquialisms."
    ),
    "casual": (
        "Use casual, conversational language. Feel free to use contractions, everyday expressions, "
        "and a relaxed tone. Write as if speaking to a friend."
    ),
    "literary": (
        "Use literary, evocative language with attention to rhythm, imagery, and nuance. "
        "Prioritize elegance and expressiveness over directness."
    ),
    "technical": (
        "Use precise technical language. Maintain consistency with industry-standard terminology. "
        "Be direct and unambiguous."
    ),
}

# Language-pair specific translation instructions
LANGUAGE_PAIR_INSTRUCTIONS = {
    ("zh", "en"): (
        "Translate Simplified Chinese to English. "
        "Note: Chinese text may contain no spaces between words — segment carefully. "
        "Proper nouns (人名、地名) should be transliterated using standard pinyin. "
        "Chinese measure words (量词) should be rendered naturally in English."
    ),
    ("ja", "en"): (
        "Translate Japanese to English. "
        "Note: Japanese uses three writing systems — Hiragana (ひらがな), Katakana (カタカナ), "
        "and Kanji (漢字). Maintain appropriate register — honorifics (尊敬語/謙譲語) should be "
        "rendered naturally in English (e.g., 'could you' for くださる). "
        "Proper nouns should use standard Romaji spelling. "
        "Omit topic markers (は/が/を) as they have no English equivalent."
    ),
    ("en", "zh"): (
        "Translate English to Simplified Chinese. "
        "Note: English text often requires word segmentation that is not obvious — "
        "use context to determine appropriate Chinese phrasing."
    ),
    ("en", "ja"): (
        "Translate English to Japanese. "
        "Note: Use standard Keigo (敬語) honorific forms by default unless the context "
        "suggests casual speech. Omit English articles when rendering to Japanese."
    ),
}


def build_context_window(segments: list[Segment], n_previous: int = 3) -> str:
    """Build a context window from the previous N translated segments.

    Used to maintain cross-paragraph coherence.
    """
    if n_previous <= 0:
        return ""

    translated = [s for s in segments if s.status == "translated" and s.translated]
    # Take the last n_previous segments
    context_segs = translated[-n_previous:]

    if not context_segs:
        return ""

    parts = []
    for seg in context_segs:
        parts.append(f"[{seg.id}] {seg.source_text} → {seg.translated}")
    return "\n".join(parts)


def build_translation_prompt(
    source_lang: str = "zh",
    target_lang: str = "en",
    glossary: Glossary | None = None,
    context: str | None = None,
    retrieved_context: str | None = None,
    style: str = "formal",
) -> str:
    """Build the system prompt for the translation task.

    Args:
        source_lang: Source language code (e.g. "zh").
        target_lang: Target language code (e.g. "en").
        glossary: Optional glossary for terminology consistency.
        context: Previous N segments for proximity-based context.
        retrieved_context: Semantically similar segments from ContextDB.
        style: Translation style (formal, casual, literary, technical).
    """
    # Map language codes to full names for user-friendly prompts
    lang_map = {
        "zh": "Chinese",
        "en": "English",
        "ja": "Japanese",
        "fr": "French",
        "de": "German",
        "es": "Spanish",
    }
    source_full = lang_map.get(source_lang, source_lang)
    target_full = lang_map.get(target_lang, target_lang)

    style_desc = STYLE_GUIDES.get(style, STYLE_GUIDES["formal"])

    lines = [
        f"You are a professional {source_full} → {target_full} translator.",
        "Translate the following text accurately and naturally.",
        style_desc,
        "Preserve all HTML tags and formatting. Do NOT add commentary.",
        "If the text is already in the target language, return it unchanged.",
        "",
    ]

    # Language-pair specific instructions
    pair_key = (source_lang, target_lang)
    if pair_key in LANGUAGE_PAIR_INSTRUCTIONS:
        lines.append(LANGUAGE_PAIR_INSTRUCTIONS[pair_key])
        lines.append("")

    if glossary and glossary.entries:
        lines.append("Glossary (use these exact translations):")
        for entry in glossary.entries:
            lines.append(f"- {entry.source} → {entry.target}")
        lines.append("")

    if context:
        lines.extend(
            [
                "Previous context (for continuity):",
                context,
                "",
            ]
        )

    if retrieved_context:
        lines.extend(
            [
                "Related context (semantically similar, from earlier in the document):",
                retrieved_context,
                "",
            ]
        )

    lines.append('Return JSON: {"translated": "..."}')
    return "\n".join(lines)


def build_proofread_prompt(glossary: Glossary | None = None) -> str:
    """Build the system prompt for the proofreading task."""
    lines = [
        "You are an English language proofreader.",
        "Review and improve the following translation for grammar, style, and naturalness.",
        "Preserve the original meaning and any glossary terms.",
        "",
    ]

    if glossary and glossary.entries:
        lines.append("Glossary (preserve these terms):")
        for entry in glossary.entries:
            lines.append(f"- {entry.source} → {entry.target}")
        lines.append("")

    lines.append('Return JSON: {"translated": "improved version"}')
    return "\n".join(lines)
