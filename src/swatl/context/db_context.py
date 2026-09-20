"""Bridge between curated context databases and embedding retrieval.

The Context DB stores human-curated entries (terminology, reference passages,
prefilled segment pairs). This module turns a database into a
:class:`~swatl.context.retriever.ContextRetriever` so those entries are
actually injected into translation prompts at run time.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from swatl.context.embedder import (
    OLLAMA_DEFAULT_URL,
    Embedder,
    EmbedderConfig,
    list_ollama_models,
    ollama_is_available,
    pick_ollama_embedding_model,
)
from swatl.context.index import FaissIndex
from swatl.context.keyword import BM25Index
from swatl.context.retriever import KEYWORD_CONTEXT_LABEL, ContextRetriever, KeywordRetriever

if TYPE_CHECKING:  # pragma: no cover - typing only
    from swatl.context_db.store import ContextEntryStore

logger = logging.getLogger(__name__)

# Retrieval from curated entries is inherently cross-document: the entry for a
# term is stored once and applies everywhere in the book.
DB_CONTEXT_LABEL = "Reference context (terminology and passages curated for this book)"


@dataclass
class EmbeddingResolution:
    """How the embedding backend was chosen, for reporting to the user."""

    config: EmbedderConfig | None
    reason: str  # human-readable explanation
    explicit: bool = False  # True when the user asked for this backend


def resolve_embedding_config(
    backend: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    config_file: EmbedderConfig | None = None,
) -> EmbeddingResolution:
    """Decide which embedding backend to use.

    Priority: explicit arguments → config file → environment → auto-detection
    (a reachable local Ollama server).
    """
    if backend:
        cfg = EmbedderConfig(
            backend=backend,
            model=model or (config_file.model if config_file else "") or _default_model(backend),
            base_url=base_url or (config_file.base_url if config_file else ""),
            api_key=os.environ.get("SWATL_EMBEDDING_API_KEY", ""),
        )
        if backend == "ollama" and not cfg.model:
            picked, note = _pick_ollama_model(cfg.base_url)
            cfg.model = picked or "bge-m3"
            return EmbeddingResolution(cfg, f"requested ({note})", explicit=True)
        return EmbeddingResolution(cfg, "requested on the command line", explicit=True)

    if config_file is not None:
        cfg = EmbedderConfig(
            backend=config_file.backend,
            model=model or config_file.model,
            base_url=base_url or config_file.base_url,
            api_key=config_file.api_key or os.environ.get("SWATL_EMBEDDING_API_KEY", ""),
            dimension=config_file.dimension,
        )
        return EmbeddingResolution(cfg, "from the [embedding] config section")

    env_backend = os.environ.get("SWATL_EMBEDDING_BACKEND")
    if env_backend:
        cfg = EmbedderConfig(
            backend=env_backend,
            model=model
            or os.environ.get("SWATL_EMBEDDING_MODEL", "")
            or _default_model(env_backend),
            base_url=base_url or os.environ.get("SWATL_EMBEDDING_URL", ""),
            api_key=os.environ.get("SWATL_EMBEDDING_API_KEY", ""),
        )
        return EmbeddingResolution(cfg, "from SWATL_EMBEDDING_* environment variables")

    # Auto-detect a local Ollama server; anything else must be configured.
    ollama_url = base_url or os.environ.get("OLLAMA_HOST") or OLLAMA_DEFAULT_URL
    if ollama_is_available(ollama_url):
        picked, note = _pick_ollama_model(ollama_url)
        if picked:
            cfg = EmbedderConfig(backend="ollama", model=picked, base_url=ollama_url)
            return EmbeddingResolution(cfg, f"auto-detected Ollama ({note})")
        return EmbeddingResolution(
            None,
            f"Ollama is running at {ollama_url} but has no known embedding model "
            f"(try: ollama pull bge-m3)",
        )

    return EmbeddingResolution(
        None,
        "no embedding backend available: start Ollama (ollama pull bge-m3), or configure "
        "an OpenAI-compatible endpoint with --embedding-backend openai --embedding-url",
    )


def _default_model(backend: str) -> str:
    return "bge-m3" if backend == "ollama" else "text-embedding-3-small"


def _pick_ollama_model(base_url: str) -> tuple[str | None, str]:
    installed = list_ollama_models(base_url)
    picked = pick_ollama_embedding_model(installed)
    if picked:
        return picked, f"using {picked}"
    return None, "no embedding model installed"


def build_db_retriever(
    store: ContextEntryStore,
    config: EmbedderConfig,
    k: int = 5,
    min_score: float = 0.35,
    max_tokens: int = 1500,
    embedder: Embedder | None = None,
) -> ContextRetriever | None:
    """Build a retriever over a context database's entries.

    Returns ``None`` when the database has no entries that can be embedded.
    Raises whatever the embedder raises (connection errors, missing model) so
    the caller can decide whether to continue without context. Pass *embedder*
    to reuse one instance or to inject a stub in tests.
    """
    entries = [e for e in store.iter_entries() if e.source_text.strip()]
    if not entries:
        return None

    embedder = embedder or Embedder(config)
    vectors = embedder.embed([e.source_text for e in entries])
    if len(vectors) != len(entries):
        raise ValueError(
            f"Embedder returned {len(vectors)} vectors for {len(entries)} context entries"
        )

    index = FaissIndex(dimension=len(vectors[0]))
    index.add(
        vectors,
        [
            {
                "segment_id": entry.id,
                "doc": entry.source_file or "",
                "anchor": entry.section or "",
                "source_text": entry.source_text,
                "translated_text": entry.translated_text or "",
                "entry_type": entry.entry_type,
            }
            for entry in entries
        ],
    )

    logger.debug(
        "Context DB '%s': indexed %d entries with %s (dim=%d)",
        store.name,
        len(entries),
        embedder.describe(),
        index.dimension,
    )
    return ContextRetriever(
        embedder=embedder,
        index=index,
        k=k,
        min_score=min_score,
        cross_doc=True,  # curated entries apply to the whole book
        max_tokens=max_tokens,
        context_label=DB_CONTEXT_LABEL,
    )


def build_keyword_retriever(
    store: ContextEntryStore,
    k: int = 5,
    max_tokens: int = 1500,
) -> KeywordRetriever | None:
    """Build a BM25 retriever over a context database, with no backend at all.

    Used when no embedding backend is available: keyword ranking is weaker than
    semantic search, but a useful context feature beats none, and it needs
    nothing installed or running.
    """
    entries = [e for e in store.iter_entries() if e.source_text.strip()]
    if not entries:
        return None

    keywords = [
        {
            "segment_id": entry.id,
            "doc": entry.source_file or "",
            "anchor": entry.section or "",
            "source_text": entry.source_text,
            "translated_text": entry.translated_text or "",
            "entry_type": entry.entry_type,
        }
        for entry in entries
    ]
    return KeywordRetriever(
        index=BM25Index.from_entries(keywords),
        k=k,
        cross_doc=True,  # curated entries apply to the whole book
        max_tokens=max_tokens,
        context_label=KEYWORD_CONTEXT_LABEL,
    )
