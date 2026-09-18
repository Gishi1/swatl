"""Base provider abstract class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from swatl.models import Glossary, Segment


class Provider(ABC):
    """Abstract provider interface for LLM translation."""

    @abstractmethod
    async def translate(
        self,
        segments: list[Segment],
        glossary: Glossary | None,
        target_lang: str,
        context: str | None,
        retrieved_contexts: list[str | None] | None = None,
        system_prompt: str | None = None,
    ) -> list[Segment]:
        """Translate segments using the provider's LLM.

        Args:
            segments: Segments to translate.
            glossary: Optional glossary for terminology.
            target_lang: Target language code.
            context: Previous N segments for proximity context.
            retrieved_contexts: Per-segment semantically similar context from ContextDB.
            system_prompt: Full system prompt from the orchestrator (style guide,
                language-pair hints, glossary, context). Providers should use it
                verbatim when supplied so options such as ``--style`` take effect.
        """

    @abstractmethod
    async def proofread(self, segments: list[Segment], glossary: Glossary | None) -> list[Segment]:
        """Proofread translated segments."""

    @abstractmethod
    async def test(self) -> dict[str, Any]:
        """Test provider connectivity with a small request."""
