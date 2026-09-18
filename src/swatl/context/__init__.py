"""Context Database — embedding-based semantic retrieval for translation consistency.

This module provides:
- Embedding of text segments into vector space (Ollama, sentence-transformers or cloud)
- FAISS-based vector index for nearest-neighbor search
- High-level retrieval that deduplicates and formats results for prompt injection
- A bridge from curated context databases to a retriever (``build_db_retriever``)
"""

from __future__ import annotations

from swatl.context.db_context import (
    DB_CONTEXT_LABEL,
    EmbeddingResolution,
    build_db_retriever,
    resolve_embedding_config,
)
from swatl.context.embedder import (
    Embedder,
    EmbedderConfig,
    list_ollama_models,
    ollama_is_available,
    pick_ollama_embedding_model,
)
from swatl.context.index import FaissIndex
from swatl.context.retriever import ContextRetriever, RetrievedContext
from swatl.context.store import ContextStore

__all__ = [
    "DB_CONTEXT_LABEL",
    "Embedder",
    "EmbedderConfig",
    "EmbeddingResolution",
    "FaissIndex",
    "ContextRetriever",
    "ContextStore",
    "RetrievedContext",
    "build_db_retriever",
    "list_ollama_models",
    "ollama_is_available",
    "pick_ollama_embedding_model",
    "resolve_embedding_config",
]
