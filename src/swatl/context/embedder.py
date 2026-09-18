"""Embedding wrapper: sentence-transformers (local) + OpenAI (cloud fallback)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Supported model IDs for local embedding.
LOCAL_MODELS: dict[str, str] = {
    "nomic-embed-text-v2-moe": "nomic-ai/nomic-embed-text-v2-moe",
    "nomic-embed-text": "nomic-ai/nomic-embed-text-v1",
    "all-MiniLM-L6-v2": "sentence-transformers/all-MiniLM-L6-v2",
    "BGE-M3": "BAAI/bge-m3",
}

# Default embedding dimensions per model family.
DIMENSIONS: dict[str, int] = {
    "nomic": 768,
    "openai": 1536,
    "minilm": 384,
    "bge": 1024,
}


@dataclass
class EmbedderConfig:
    """Configuration for the embedding backend."""

    # "local" or "openai"
    backend: str = "local"
    # Model identifier — one of LOCAL_MODELS keys or an OpenAI model ID
    model: str = "nomic-embed-text-v2-moe"
    # Embedding dimension (output dimension after any reduction)
    dimension: int = 0  # computed automatically from model
    # OpenAI API key for cloud fallback
    api_key: str = ""
    # Base URL for OpenAI-compatible cloud embedding (defaults to official endpoint)
    base_url: str = ""
    # Reduce dimensionality for local models (only nomic supports this via MRL)
    reduce_dimensions: bool = True
    reduce_to: int = 256

    def __post_init__(self) -> None:
        if self.dimension == 0:
            self.dimension = self._infer_dimension()

    def _infer_dimension(self) -> int:
        if self.backend == "openai":
            return DIMENSIONS.get("openai", 1536)
        model_lower = self.model.lower()
        if model_lower.startswith("nomic"):
            return self.reduce_to if self.reduce_dimensions else DIMENSIONS["nomic"]
        if model_lower.startswith("all-minilm") or model_lower.startswith("all-MiniLM"):
            return DIMENSIONS["minilm"]
        if model_lower.startswith("bge"):
            return DIMENSIONS["bge"]
        return 768


class Embedder:
    """Wraps sentence-transformers for local embedding or OpenAI API for cloud."""

    def __init__(self, config: EmbedderConfig | None = None) -> None:
        self.config = config or EmbedderConfig()
        self._pipeline = None  # Lazy-loaded sentence-transformers pipeline
        self._client = None  # Lazy-loaded OpenAI client

    # ── Public API ──────────────────────────────────────────────────────

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts and return vectors."""
        if not texts:
            return []
        if self.config.backend == "openai":
            return self._embed_openai(texts)
        return self._embed_local(texts)

    def embed_one(self, text: str) -> list[float]:
        """Embed a single text and return the vector."""
        result = self.embed([text])
        return result[0] if result else []

    # ── Local (sentence-transformers) ───────────────────────────────────

    def _embed_local(self, texts: list[str]) -> list[list[float]]:
        import torch
        from sentence_transformers import SentenceTransformer

        if self._pipeline is None:
            model_name = LOCAL_MODELS.get(
                self.config.model,
                f"huggingface/{self.config.model}",
            )
            logger.info("Loading embedding model: %s", model_name)
            self._pipeline = SentenceTransformer(
                model_name,
                trust_remote_code=True,
            )
            # Set reduce_to dimension if supported (nomic)
            if self.config.reduce_dimensions and hasattr(self._pipeline, "set_norm"):
                try:
                    self._pipeline.set_norm(self.config.reduce_to)
                except Exception:
                    pass

        with torch.no_grad():
            embeddings = self._pipeline.encode(
                texts,
                show_progress_bar=False,
                normalize_embeddings=True,  # cosine similarity via inner product
            )

        # Cast to list[list[float]]
        result = embeddings.tolist()
        # Trim to configured dimension
        dim = self.config.dimension
        if dim and dim < len(result[0]):
            result = [vec[:dim] for vec in result]
        return result

    # ── Cloud (OpenAI) ──────────────────────────────────────────────────

    def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        from openai import OpenAI

        if self._client is None:
            self._client = OpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url or None,
            )

        response = self._client.embeddings.create(
            model=self.config.model or "text-embedding-3-small",
            input=texts,
            dimensions=self.config.dimension or None,
        )
        return [d.embedding for d in response.data]

    # ── Model info ──────────────────────────────────────────────────────

    @property
    def dimension(self) -> int:
        return self.config.dimension

    @property
    def is_available(self) -> bool:
        if self.config.backend == "openai":
            return bool(self.config.api_key)
        try:
            import sentence_transformers  # noqa: F401

            return True
        except ImportError:
            return False
