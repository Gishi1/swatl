"""FAISS index management for ContextDB — add, query, save, load."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class FaissIndex:
    """Thin wrapper around FAISS for vector storage and nearest-neighbor search.

    Supports:
    - Exact inner-product search (IndexFlatIP) on normalized vectors
    - Batch add / single add
    - Save / load to disk (binary FAISS index + metadata JSON)
    - Document filtering (optional)
    """

    def __init__(self, dimension: int = 768, index_path: str | Path | None = None) -> None:
        self.dimension = dimension
        self._index = None  # Lazy-initialized
        self._metadata: list[dict[str, Any]] = []  # Parallel list of metadata dicts
        self._index_path = Path(index_path) if index_path else None

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def count(self) -> int:
        return len(self._metadata)

    @property
    def is_empty(self) -> bool:
        return self.count == 0

    def _ensure_index(self) -> None:
        """Create the FAISS index if it hasn't been created yet."""
        import faiss

        if self._index is None:
            # IndexFlatIP for exact inner-product search on normalized vectors
            # (equivalent to cosine similarity)
            self._index = faiss.IndexFlatIP(self.dimension)
            logger.debug("Created FAISS IndexFlatIP (dim=%d)", self.dimension)

    # ── Add / Remove ────────────────────────────────────────────────────

    def add(self, vectors: list[list[float]], metadata: list[dict[str, Any]]) -> None:
        """Add vectors and associated metadata to the index."""
        if not vectors:
            return
        self._ensure_index()

        arr = np.array(vectors, dtype=np.float32)
        self._index.add(arr)
        # Store vectors in metadata for rebuild (remove _vector on save)
        for vec, meta in zip(vectors, metadata, strict=True):
            entry = dict(meta)
            entry["_vector"] = vec
            self._metadata.append(entry)
        logger.debug("Added %d vectors (total: %d)", len(vectors), self.count)

    def add_single(self, vector: list[float], metadata: dict[str, Any]) -> None:
        """Add a single vector and metadata entry."""
        self.add([vector], [metadata])

    def remove(self, indices: list[int]) -> None:
        """Remove entries by their FAISS internal IDs.

        Note: FAISS IndexFlatIP doesn't support in-place removal efficiently.
        This rebuilds the index from remaining entries.
        """
        if not indices or self.is_empty:
            return
        remaining = [i for i in range(self.count) if i not in set(indices)]
        if not remaining:
            self._index = None
            self._metadata = []
            return
        import numpy as np

        # The vectors are read back out of FAISS rather than from the metadata
        # copy: save() strips the "_vector" field deliberately, so after a load
        # every entry had an empty vector and the rebuild asserted. IndexFlatIP
        # can reconstruct its vectors, so this works on a freshly built index
        # and on one loaded from disk alike.
        vectors = np.array([self._index.reconstruct(int(i)) for i in remaining], dtype=np.float32)
        metadata = [self._metadata[i] for i in remaining]
        self._metadata = metadata
        self._rebuild(vectors)

    def _rebuild(self, vectors: np.ndarray) -> None:
        """Rebuild the FAISS index from vectors (metadata already set)."""
        import faiss

        if len(vectors) == 0:
            self._index = None
            return
        self._index = faiss.IndexFlatIP(self.dimension)
        self._index.add(vectors)

    # ── Query ───────────────────────────────────────────────────────────

    def query(
        self,
        vector: list[float],
        k: int = 5,
        doc_filter: str | None = None,
        min_score: float = 0.0,
    ) -> list[tuple[int, float, dict[str, Any]]]:
        """Query the index for the top-K nearest neighbors.

        Returns list of (faiss_id, score, metadata_dict).
        Optionally filters to segments from the same document (doc).
        """
        if self.is_empty:
            return []

        self._ensure_index()
        q = np.array([vector], dtype=np.float32)
        scores, ids = self._index.search(q, min(k, self.count))
        results: list[tuple[int, float, dict[str, Any]]] = []
        for score, faiss_id in zip(scores[0], ids[0], strict=False):
            if faiss_id < 0:  # FAISS pads with -1
                break
            if score < min_score:
                continue
            meta = self._metadata[faiss_id]
            if doc_filter and meta.get("doc") != doc_filter:
                continue
            results.append((int(faiss_id), float(score), meta))
        return results[:k]

    def query_multi(
        self,
        vectors: list[list[float]],
        k: int = 5,
        doc_filter: str | None = None,
        min_score: float = 0.0,
    ) -> list[list[tuple[int, float, dict[str, Any]]]]:
        """Query for multiple vectors at once (batched search)."""
        if self.is_empty:
            return []

        self._ensure_index()
        arr = np.array(vectors, dtype=np.float32)
        scores, ids = self._index.search(arr, min(k, self.count))
        all_results: list[list[tuple[int, float, dict[str, Any]]]] = []
        for s, i in zip(scores, ids, strict=True):
            results: list[tuple[int, float, dict[str, Any]]] = []
            for score, faiss_id in zip(s, i, strict=False):
                if faiss_id < 0 or score < min_score:
                    break
                meta = self._metadata[faiss_id]
                if doc_filter and meta.get("doc") != doc_filter:
                    continue
                results.append((int(faiss_id), float(score), meta))
            all_results.append(results[:k])
        return all_results

    # ── Persistence ─────────────────────────────────────────────────────

    def save(self, path: str | Path | None = None) -> None:
        """Save the FAISS index and metadata to disk."""
        import faiss

        save_path = Path(path) if path else self._index_path
        if save_path is None:
            logger.warning("No path specified for save; skipping.")
            return
        save_path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(save_path))
        # Save metadata separately as JSON
        meta_path = save_path.with_suffix(".json")
        import json

        # Strip internal _vector field from saved metadata
        clean_meta = [{k: v for k, v in m.items() if not k.startswith("_")} for m in self._metadata]
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(clean_meta, f, ensure_ascii=False, indent=2)
        logger.info("Saved FAISS index (%d vectors) to %s", self.count, save_path)

    def load(self, path: str | Path | None = None) -> bool:
        """Load the FAISS index and metadata from disk. Returns True on success."""
        import faiss

        load_path = Path(path) if path else self._index_path
        if load_path is None or not load_path.exists():
            return False
        try:
            index = faiss.read_index(str(load_path))
            meta_path = load_path.with_suffix(".json")
            metadata: list[dict[str, Any]] = []
            if meta_path.exists():
                import json

                with open(meta_path, encoding="utf-8") as f:
                    metadata = json.load(f)

            # One metadata row per vector is an invariant of every read path: a
            # missing or stale metadata file used to load "successfully" with an
            # empty list, after which the next add() bound metadata to the wrong
            # vectors and queries returned another entry's text.
            if len(metadata) != index.ntotal:
                logger.error(
                    "Refusing to load %s: %d vectors but %d metadata rows",
                    load_path,
                    index.ntotal,
                    len(metadata),
                )
                self._index = None
                self._metadata = []
                return False

            self._index = index
            self.dimension = index.d
            self._metadata = metadata
            logger.info(
                "Loaded FAISS index (%d vectors, dim=%d) from %s",
                self.count,
                self.dimension,
                load_path,
            )
            return True
        except Exception as e:
            logger.error("Failed to load FAISS index: %s", e)
            self._index = None
            self._metadata = []
            return False

    # ── Utility ─────────────────────────────────────────────────────────

    def get_metadata(self, faiss_id: int) -> dict[str, Any] | None:
        """Retrieve metadata for a FAISS-internal ID."""
        if 0 <= faiss_id < len(self._metadata):
            return self._metadata[faiss_id]
        return None

    def clear(self) -> None:
        """Clear all vectors and metadata."""
        self._index = None
        self._metadata = []
