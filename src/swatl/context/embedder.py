"""Embedding wrapper: Ollama (local server) or any OpenAI-compatible endpoint."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Embedding backends this package can talk to. Any OpenAI-compatible
# ``/v1/embeddings`` server can be used through "openai", including a local
# Ollama server, LM Studio or a translation proxy.
BACKENDS = ("ollama", "openai")

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

    # "ollama" or "openai" (see BACKENDS)
    backend: str = "ollama"
    # Model identifier — an Ollama model name or an OpenAI-compatible model ID
    model: str = "bge-m3"
    # Embedding dimension (output dimension after any reduction).
    # 0 means "unknown, adopt the dimension of the first response".
    dimension: int = 0
    # API key for cloud fallback
    api_key: str = ""
    # Base URL: Ollama server or OpenAI-compatible endpoint
    base_url: str = ""
    # Timeout in seconds for embedding requests
    timeout: float = 120.0

    def __post_init__(self) -> None:
        if self.backend not in BACKENDS:
            raise ValueError(
                f"Unknown embedding backend {self.backend!r}: choose one of {', '.join(BACKENDS)}"
            )
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
            return DIMENSIONS["nomic"]
        if model_lower.startswith("all-minilm"):
            return DIMENSIONS["minilm"]
        if model_lower.startswith("bge"):
            return DIMENSIONS["bge"]
        return 0  # adopt whatever the server returns


class Embedder:
    """Embeds text through a local Ollama server or an OpenAI-compatible API."""

    def __init__(self, config: EmbedderConfig | None = None) -> None:
        self.config = config or EmbedderConfig()
        self._client = None  # Lazy-loaded OpenAI client

    # ── Public API ──────────────────────────────────────────────────────

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts and return vectors."""
        if not texts:
            return []
        if self.config.backend == "ollama":
            return self._embed_ollama(texts)
        return self._embed_openai(texts)

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
        return bool(self.config.api_key)

    def describe(self) -> str:
        """A short human-readable description of the backend in use."""
        if self.config.backend == "ollama":
            return f"ollama:{self.config.model} at {self.config.base_url or OLLAMA_DEFAULT_URL}"
        return f"openai:{self.config.model}"


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
