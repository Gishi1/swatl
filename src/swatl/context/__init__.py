"""Context Database — embedding-based semantic retrieval for translation consistency.

This module provides:
- Embedding of text segments into vector space (local or cloud)
- FAISS-based vector index for nearest-neighbor search
- High-level retrieval that deduplicates and formats results for prompt injection
"""

from __future__ import annotations

from swatl.context.embedder import Embedder, EmbedderConfig
from swatl.context.index import FaissIndex
from swatl.context.retriever import ContextRetriever
from swatl.context.store import ContextStore

__all__ = [
    "Embedder",
    "EmbedderConfig",
    "FaissIndex",
    "ContextRetriever",
    "ContextStore",
]
