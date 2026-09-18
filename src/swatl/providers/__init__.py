"""providers package: LLM provider abstraction and adapters."""

from .mock import MockProvider
from .openai_compat import OpenAICompatible

__all__ = ["OpenAICompatible", "MockProvider"]
