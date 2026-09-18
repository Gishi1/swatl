"""Embedding wrapper: Ollama (local server), sentence-transformers, or OpenAI."""

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

# Default endpoint for a local Ollama server.
OLLAMA_DEFAULT_URL = "http://127.0.0.1:11434"

# Embedding models we know the dimension of, keyed by an Ollama model prefix.
# Anything else is sized from the first response.
OLLAMA_MODEL_DIMENSIONS: dict[str, int] = {
    "bge-m3": 1024,
    "bge-large": 1024,
    "bge-base": 768,
    "nomic-embed-text": 768,
    "mxbai-embed-large": 1024,
    "all-minilm": 384,
    "snowflake-arctic-embed": 1024,
    "qwen3-embedding": 1024,
}

# Preference order when auto-selecting an Ollama embedding model.
OLLAMA_MODEL_PREFERENCE = ("bge-m3", "qwen3-embedding", "nomic-embed-text", "mxbai-embed-large")


@dataclass
class EmbedderConfig:
    """Configuration for the embedding backend."""

    # "ollama", "local" (sentence-transformers) or "openai"
    backend: str = "ollama"
    # Model identifier — an Ollama model name, a LOCAL_MODELS key, or an OpenAI model ID
    model: str = "bge-m3"
    # Embedding dimension (output dimension after any reduction).
    # 0 means "unknown, adopt the dimension of the first response".
    dimension: int = 0
    # API key for cloud fallback
    api_key: str = ""
    # Base URL: Ollama server or OpenAI-compatible endpoint
    base_url: str = ""
    # Reduce dimensionality for local models (only nomic supports this via MRL)
    reduce_dimensions: bool = False
    reduce_to: int = 256
    # Timeout in seconds for embedding requests
    timeout: float = 120.0

    def __post_init__(self) -> None:
        if self.backend == "ollama" and not self.base_url:
            self.base_url = OLLAMA_DEFAULT_URL
        if self.dimension == 0:
            self.dimension = self._infer_dimension()

    def _infer_dimension(self) -> int:
        if self.backend == "openai":
            return DIMENSIONS.get("openai", 1536)
        if self.backend == "ollama":
            model_lower = self.model.lower()
            for prefix, dimension in OLLAMA_MODEL_DIMENSIONS.items():
                if model_lower.startswith(prefix):
                    return dimension
            return 0  # adopt whatever the server returns
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
        if self.config.backend == "ollama":
            return self._embed_ollama(texts)
        if self.config.backend == "openai":
            return self._embed_openai(texts)
        return self._embed_local(texts)

    def embed_one(self, text: str) -> list[float]:
        """Embed a single text and return the vector."""
        result = self.embed([text])
        return result[0] if result else []

    @staticmethod
    def _normalise(vectors: list[list[float]]) -> list[list[float]]:
        """L2-normalise vectors so inner product equals cosine similarity."""
        import math

        normalised: list[list[float]] = []
        for vector in vectors:
            norm = math.sqrt(sum(v * v for v in vector))
            normalised.append([v / norm for v in vector] if norm else list(vector))
        return normalised

    def _adopt_dimension(self, vectors: list[list[float]]) -> None:
        """Record the real output dimension, overriding a guess."""
        if vectors and vectors[0] and self.config.dimension != len(vectors[0]):
            if self.config.dimension:
                logger.debug(
                    "Embedding dimension %d differs from configured %d; adopting the model's",
                    len(vectors[0]),
                    self.config.dimension,
                )
            self.config.dimension = len(vectors[0])

    # ── Ollama ──────────────────────────────────────────────────────────

    def _embed_ollama(self, texts: list[str]) -> list[list[float]]:
        import httpx

        base_url = (self.config.base_url or OLLAMA_DEFAULT_URL).rstrip("/")
        response = httpx.post(
            f"{base_url}/api/embed",
            json={"model": self.config.model, "input": texts},
            timeout=self.config.timeout,
        )
        response.raise_for_status()
        vectors = response.json().get("embeddings") or []
        if len(vectors) != len(texts):
            raise ValueError(f"Ollama returned {len(vectors)} embeddings for {len(texts)} inputs")
        vectors = self._normalise(vectors)
        self._adopt_dimension(vectors)
        return vectors

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
        if self.config.backend == "ollama":
            return ollama_is_available(self.config.base_url or OLLAMA_DEFAULT_URL)
        if self.config.backend == "openai":
            return bool(self.config.api_key)
        try:
            import sentence_transformers  # noqa: F401

            return True
        except ImportError:
            return False

    def describe(self) -> str:
        """A short human-readable description of the backend in use."""
        if self.config.backend == "ollama":
            return f"ollama:{self.config.model} at {self.config.base_url or OLLAMA_DEFAULT_URL}"
        if self.config.backend == "openai":
            return f"openai:{self.config.model}"
        return f"sentence-transformers:{self.config.model}"


# ── Ollama discovery helpers ────────────────────────────────────────────


def ollama_is_available(base_url: str = OLLAMA_DEFAULT_URL, timeout: float = 1.5) -> bool:
    """Whether an Ollama server answers at *base_url*."""
    import httpx

    try:
        response = httpx.get(f"{base_url.rstrip('/')}/api/version", timeout=timeout)
        return response.status_code == 200
    except Exception:
        return False


def list_ollama_models(base_url: str = OLLAMA_DEFAULT_URL, timeout: float = 3.0) -> list[str]:
    """Names of the models installed on an Ollama server (empty when unreachable)."""
    import httpx

    try:
        response = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=timeout)
        response.raise_for_status()
        return [m.get("name", "") for m in response.json().get("models", [])]
    except Exception:
        return []


def pick_ollama_embedding_model(
    installed: list[str], preference: tuple[str, ...] = OLLAMA_MODEL_PREFERENCE
) -> str | None:
    """Choose an embedding model from what the server actually has.

    Ollama has no reliable "is this an embedding model" flag in ``/api/tags``,
    so known embedding families are matched by name in preference order.
    """
    lowered = {name.lower(): name for name in installed}
    for wanted in preference:
        for lower, original in lowered.items():
            if lower.startswith(wanted) or f"/{wanted}" in lower:
                return original
    return None
