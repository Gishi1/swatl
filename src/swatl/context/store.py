"""Persistence layer for ContextDB index + metadata.

Manages the .swatl-state/context_db/ directory structure.
"""

from __future__ import annotations

import logging
from pathlib import Path

from swatl.context.embedder import Embedder, EmbedderConfig
from swatl.context.index import FaissIndex

logger = logging.getLogger(__name__)

# Default subdirectory for context data within a state directory.
CONTEXT_DB_SUBDIR = "context_db"


class ContextStore:
    """Manages persistence and lifecycle of the context vector index.

    Coordinates:
    - Loading an existing index from disk
    - Saving the index after updates
    - Managing the embedder (lazy init)
    """

    def __init__(
        self,
        state_dir: str | Path,
        config: EmbedderConfig | None = None,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.context_dir = self.state_dir / CONTEXT_DB_SUBDIR
        self.config = config or EmbedderConfig()
        self._embedder: Embedder | None = None
        self._index: FaissIndex | None = None

    # ── Properties (lazy) ───────────────────────────────────────────────

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = Embedder(self.config)
        return self._embedder

    @property
    def index(self) -> FaissIndex:
        if self._index is None:
            self._index = FaissIndex(dimension=self.config.dimension)
        return self._index

    # ── Index lifecycle ─────────────────────────────────────────────────

    @property
    def index_path(self) -> Path:
        """Path to the FAISS index file."""
        return self.context_dir / "index"

    @property
    def is_initialized(self) -> bool:
        """Check if the context DB exists on disk."""
        return self.index_path.exists()

    def load(self) -> bool:
        """Load the index from disk. Returns True if successful."""
        return self.index.load(self.index_path)

    def save(self) -> None:
        """Save the index to disk."""
        self.index.save(self.index_path)

    def save_if_changed(self, changed: bool = False) -> None:
        """Save only if there were changes."""
        if changed:
            self.save()

    def clear(self) -> None:
        """Remove the context DB from disk."""
        if self.context_dir.exists():
            import shutil

            shutil.rmtree(self.context_dir)
        self._embedder = None
        self._index = None

    # ── Add segments to index ──────────────────────────────────────────

    def add_segments(
        self,
        segments: list,  # Segment objects with .id, .doc, .anchor, .source_text, .translated
    ) -> int:
        """Embed and add segments to the index.

        Returns the number of segments added.
        """
        if not segments:
            return 0

        pairs = [seg for seg in segments if getattr(seg, "translated", None)]
        if not pairs:
            return 0

        texts = [seg.source_text for seg in pairs]

        # Embed in batch
        vectors = self.embedder.embed(texts)

        # Build metadata
        metadata = []
        for seg, vec in zip(pairs, vectors, strict=True):
            metadata.append(
                {
                    "segment_id": seg.id,
                    "doc": seg.doc,
                    "anchor": seg.anchor,
                    "source_text": seg.source_text,
                    "translated_text": seg.translated or "",
                    "stage": getattr(seg, "status", "translated"),
                    "_vector": vec,  # internal: keep vector for rebuild
                }
            )

        # Add to index
        self.index.add(vectors, metadata)
        logger.info("Added %d segments to context index (%d total)", len(vectors), self.index.count)
        return len(vectors)

    def remove_segment(self, segment_id: str) -> bool:
        """Remove a segment from the index by its ID. Returns True if found."""
        target_ids = [
            i for i, m in enumerate(self.index._metadata) if m.get("segment_id") == segment_id
        ]
        if not target_ids:
            return False
        # Get FAISS IDs (they match indices if no deletions)
        self.index.remove(target_ids)
        return True

    # ── Stats ───────────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Return index statistics."""
        return {
            "vector_count": self.index.count,
            "dimension": self.config.dimension,
            "backend": self.config.backend,
            "model": self.config.model,
            "is_initialized": self.is_initialized,
        }
