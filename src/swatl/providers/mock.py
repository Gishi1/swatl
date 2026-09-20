"""Mock provider for testing — returns deterministic translations."""

from __future__ import annotations

from swatl.models import Glossary, Segment, SegmentStatus


class MockProvider:
    """Returns predictable translations for testing.

    Strategy: simple character-level substitution for Chinese, or
    returns a fixed translation template.
    """

    def __init__(self, name: str = "mock", target_lang: str = "en") -> None:
        self.name = name
        self.target_lang = target_lang
        self.cost_per_token_in: float = 0.0
        self.cost_per_token_out: float = 0.0

    @property
    def provider_type(self) -> str:
        return "mock"

    async def translate(
        self,
        segments: list[Segment],
        glossary: Glossary | None = None,
        target_lang: str | None = None,
        context: str | None = None,
        retrieved_contexts: list[str | None] | None = None,
        system_prompt: str | None = None,
    ) -> list[Segment]:
        """Translate segments deterministically."""
        results = []
        for seg in segments:
            translated = _mock_translate(seg.source_text, glossary)
            seg.translated = translated
            seg.status = SegmentStatus.TRANSLATED
            seg.provider = self.name
            seg.tokens_in = max(1, len(seg.source_text))
            seg.tokens_out = max(1, len(translated))
            results.append(seg)
        return results

    async def proofread(
        self, segments: list[Segment], glossary: Glossary | None = None
    ) -> list[Segment]:
        """Mock proofread: slightly modify translation for testing."""
        results = []
        for seg in segments:
            if seg.translated:
                seg.translated = seg.translated + " [proofread]"
                seg.status = SegmentStatus.PROOFREAD
            results.append(seg)
        return results

    async def test(self) -> dict:
        return {"ok": True, "latency_ms": 0, "error": None}


def _mock_translate(text: str, glossary: Glossary | None) -> str:
    """Convert Chinese text to a mock English translation.

    For testing: each CJK character → its Unicode code point as English text.
    Also replaces glossary terms with their specified target.
    """
    # Track glossary replacements with delimiters so they survive the loop
    if glossary and glossary.entries:
        for entry in glossary.entries:
            if entry.source in text:
                text = text.replace(entry.source, f"<<{entry.target}>>")

    # If the text has no CJK characters, just return "Translated: {text}". Any
    # glossary markers substituted above still have to be unwrapped, otherwise a
    # pure-ASCII term leaked through as "Translated: The <<Zhi Zi>> is here."
    if not any("\u4e00" <= c <= "\u9fff" for c in text):
        result = f"Translated: {text}"
        if glossary and glossary.entries:
            for entry in glossary.entries:
                result = result.replace(f"<<{entry.target}>>", f"[{entry.target}]")
        return result

    # CJK text: return a deterministic mock translation
    result_parts = []
    for c in text:
        if "\u4e00" <= c <= "\u9fff":
            # Convert to a mock English word
            result_parts.append(f"char{ord(c) % 100:02d}")
        else:
            result_parts.append(c)
    result = " ".join(result_parts)

    # Restore glossary replacements to clean format
    if glossary and glossary.entries:
        for entry in glossary.entries:
            spaced_marker = " ".join(f"<<{entry.target}>>")
            result = result.replace(spaced_marker, f"[{entry.target}]")

    return result
