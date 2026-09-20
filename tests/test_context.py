"""Tests for context/ module (Phase 6: embedding-based context retrieval)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from swatl.context.embedder import Embedder, EmbedderConfig
from swatl.context.index import FaissIndex
from swatl.context.retriever import ContextRetriever, RetrievedContext
from swatl.context.store import ContextStore
from swatl.models import Segment

# ── EmbedderConfig tests ──────────────────────────────────────────


class TestEmbedderConfig:
    def test_default_config(self):
        # Ollama is the default because it is the zero-download local option
        # when a server is running; callers override to use the others.
        cfg = EmbedderConfig()
        assert cfg.backend == "ollama"
        assert cfg.model == "bge-m3"
        assert cfg.dimension == 1024
        assert cfg.base_url == "http://127.0.0.1:11434"

    def test_ollama_unknown_model_adopts_server_dimension(self):
        cfg = EmbedderConfig(backend="ollama", model="some-custom-embed")
        assert cfg.dimension == 0  # decided by the first response

    def test_unknown_backend_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown embedding backend"):
            EmbedderConfig(backend="sentence-transformers")

    def test_local_backend_is_gone(self):
        """The in-process backend was removed with its torch dependency."""
        with pytest.raises(ValueError):
            EmbedderConfig(backend="local")

    def test_openai_backend(self):
        cfg = EmbedderConfig(backend="openai", model="text-embedding-3-small")
        assert cfg.backend == "openai"
        assert cfg.dimension == 1536

    def test_minilm_dimension(self):
        cfg = EmbedderConfig(model="all-MiniLM-L6-v2")
        assert cfg.dimension == 384

    def test_bge_dimension(self):
        cfg = EmbedderConfig(model="BGE-M3")
        # BGE-M3 defaults to 1024
        assert cfg.dimension == 1024


# ── FaissIndex tests ──────────────────────────────────────────────


class TestFaissIndex:
    @pytest.fixture
    def index(self):
        return FaissIndex(dimension=3)

    def test_create_index(self):
        idx = FaissIndex(dimension=5)
        assert idx.count == 0
        assert idx.is_empty

    def test_add_vectors(self, index):
        vectors = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6], [0.7, 0.8, 0.9]]
        metadata = [
            {"segment_id": "s1", "source_text": "hello"},
            {"segment_id": "s2", "source_text": "world"},
            {"segment_id": "s3", "source_text": "test"},
        ]
        index.add(vectors, metadata)
        assert index.count == 3

    def test_add_single(self, index):
        index.add_single([0.1, 0.2, 0.3], {"segment_id": "s1"})
        assert index.count == 1

    def test_add_empty(self, index):
        index.add([], [])
        assert index.count == 0

    def test_query_returns_results(self, index):
        vectors = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        metadata = [
            {"segment_id": "s1", "source_text": "hello", "doc": "text/ch01.xhtml"},
            {"segment_id": "s2", "source_text": "world", "doc": "text/ch01.xhtml"},
            {"segment_id": "s3", "source_text": "test", "doc": "text/ch02.xhtml"},
        ]
        index.add(vectors, metadata)
        results = index.query([1.0, 0.0, 0.0], k=3)
        assert len(results) == 3
        assert results[0][2]["segment_id"] == "s1"  # highest score

    def test_query_with_doc_filter(self, index):
        vectors = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        metadata = [
            {"segment_id": "s1", "doc": "text/ch01.xhtml"},
            {"segment_id": "s2", "doc": "text/ch01.xhtml"},
            {"segment_id": "s3", "doc": "text/ch02.xhtml"},
        ]
        index.add(vectors, metadata)
        # Query with ch01 filter
        results = index.query([0.0, 0.0, 1.0], k=5, doc_filter="text/ch01.xhtml")
        assert len(results) == 2
        for _faiss_id, _score, meta in results:
            assert meta["doc"] == "text/ch01.xhtml"

    def test_query_empty_index(self, index):
        assert index.query([0.1, 0.2, 0.3]) == []

    def test_save_and_load(self, tmp_path):
        index = FaissIndex(dimension=3, index_path=tmp_path / "index")
        vectors = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        metadata = [{"segment_id": "s1"}, {"segment_id": "s2"}]
        index.add(vectors, metadata)
        index.save()

        # Load into a new index
        new_index = FaissIndex(dimension=3, index_path=tmp_path / "index")
        assert new_index.load() is True
        assert new_index.count == 2
        assert new_index._metadata[0]["segment_id"] == "s1"

    def test_load_nonexistent(self, tmp_path):
        index = FaissIndex(dimension=3, index_path=tmp_path / "nonexistent")
        assert index.load() is False

    def test_remove_entries(self, index):
        # Use distinct vectors that won't collide
        vectors = [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
            [1.0, 1.0, 0.0],
            [0.0, 1.0, 1.0],
        ]
        metadata = [{"segment_id": f"s{i}"} for i in range(5)]
        index.add(vectors, metadata)
        assert index.count == 5
        index.remove([0, 2, 4])
        assert index.count == 2
        ids = [m["segment_id"] for m in index._metadata]
        assert "s0" not in ids
        assert "s2" not in ids
        assert "s4" not in ids
        assert "s1" in ids
        assert "s3" in ids

    def test_clear(self, index):
        index.add_single([0.1, 0.2, 0.3], {"id": "s1"})
        index.clear()
        assert index.count == 0
        assert index.is_empty

    def test_query_multi(self, index):
        vectors = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6], [0.7, 0.8, 0.9]]
        metadata = [{"segment_id": f"s{i}"} for i in range(3)]
        index.add(vectors, metadata)
        queries = [[0.1, 0.2, 0.3], [0.7, 0.8, 0.9]]
        results = index.query_multi(queries, k=2)
        assert len(results) == 2
        assert len(results[0]) == 2
        assert len(results[1]) == 2


# ── ContextRetriever tests ────────────────────────────────────────


class TestContextRetriever:
    @pytest.fixture
    def mock_embedder(self):
        embedder = MagicMock()
        embedder.dimension = 3
        embedder.embed_one.return_value = [0.5, 0.5, 0.5]
        # Batched retrieval embeds the whole batch in one call.
        embedder.embed.side_effect = lambda texts: [[0.5, 0.5, 0.5] for _ in texts]
        return embedder

    @pytest.fixture
    def mock_index(self):
        idx = FaissIndex(dimension=3)
        idx.add(
            [[0.5, 0.5, 0.5], [0.3, 0.3, 0.3], [0.1, 0.1, 0.1]],
            [
                {
                    "segment_id": "p-0012",
                    "source_text": "概念来自相对论。",
                    "translated_text": "Concept from relativity.",
                    "doc": "text/ch01.xhtml",
                },
                {
                    "segment_id": "p-0047",
                    "source_text": "爱因斯坦提出理论。",
                    "translated_text": "Einstein proposed theory.",
                    "doc": "text/ch01.xhtml",
                },
                {
                    "segment_id": "p-0099",
                    "source_text": "量子纠缠现象。",
                    "translated_text": "Quantum entanglement phenomenon.",
                    "doc": "text/ch02.xhtml",
                },
            ],
        )
        return idx

    @pytest.fixture
    def retriever(self, mock_embedder, mock_index):
        return ContextRetriever(
            embedder=mock_embedder,
            index=mock_index,
            k=5,
            min_score=0.0,
            cross_doc=False,
        )

    def test_retrieve_empty_index(self, mock_embedder):
        empty_index = FaissIndex(dimension=3)
        retriever = ContextRetriever(embedder=mock_embedder, index=empty_index)
        assert retriever.retrieve("hello") == []

    def test_retrieve_returns_context(self, retriever):
        items = retriever.retrieve("测试文本", current_doc="text/ch01.xhtml")
        assert len(items) > 0
        assert isinstance(items[0], RetrievedContext)
        assert items[0].segment_id == "p-0012"

    def test_retrieve_deduplicates_proximity(self, retriever):
        proximity = {"p-0012", "p-0047"}
        items = retriever.retrieve("测试文本", proximity_ids=proximity)
        ids = [i.segment_id for i in items]
        assert "p-0012" not in ids
        assert "p-0047" not in ids

    def test_retrieve_doc_filter(self, retriever):
        items = retriever.retrieve("测试文本", current_doc="text/ch01.xhtml")
        ids = [i.segment_id for i in items]
        # ch02 should be filtered out when cross_doc=False
        assert "p-0099" not in ids

    def test_format_context_empty(self, retriever):
        assert retriever.format_context([]) == ""

    def test_format_context(self, retriever):
        items = [
            RetrievedContext(
                segment_id="p-0012",
                source_text="概念来自相对论。",
                translated_text="Concept from relativity.",
                doc="text/ch01.xhtml",
                anchor=".//p[1]",
                similarity=0.9,
            ),
        ]
        formatted = retriever.format_context(items)
        assert "p-0012" in formatted
        assert "概念来自相对论。" in formatted
        assert "Related context" in formatted

    def test_retrieve_and_format(self, retriever):
        result = retriever.retrieve_and_format("测试文本", current_doc="text/ch01.xhtml")
        assert isinstance(result, str)
        assert "p-0012" in result


# ── ContextStore tests ────────────────────────────────────────────


class TestContextStore:
    @pytest.fixture
    def cfg(self):
        return EmbedderConfig(backend="openai", dimension=3, api_key="test-key")

    def test_create_store(self, tmp_path):
        store = ContextStore(tmp_path)
        assert store.is_initialized is False

    def test_add_segments(self, tmp_path, cfg):
        store = ContextStore(tmp_path, config=cfg)
        segments = [
            Segment(
                id="s1",
                doc="text/ch01.xhtml",
                anchor=".//p[1]",
                tag="p",
                source_text="你好世界",
                translated="Hello world",
                status="translated",
            ),
            Segment(
                id="s2",
                doc="text/ch01.xhtml",
                anchor=".//p[2]",
                tag="p",
                source_text="测试文本",
                translated="Test text",
                status="translated",
            ),
        ]
        # Use mock embedder since we don't want to call OpenAI
        mock_emb = MagicMock()
        mock_emb.embed.return_value = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        store._embedder = mock_emb
        added = store.add_segments(segments)
        assert added == 2
        assert store.index.count == 2

    def test_add_segments_skips_none_translation(self, tmp_path, cfg):
        store = ContextStore(tmp_path, config=cfg)
        segments = [
            Segment(
                id="s1",
                doc="text/ch01.xhtml",
                anchor=".//p[1]",
                tag="p",
                source_text="你好",
                translated="Hello",
                status="translated",
            ),
            Segment(
                id="s2",
                doc="text/ch01.xhtml",
                anchor=".//p[2]",
                tag="p",
                source_text="世界",
                translated=None,
                status="pending",
            ),
        ]
        mock_emb = MagicMock()
        mock_emb.embed.return_value = [[0.1, 0.2, 0.3]]
        store._embedder = mock_emb
        added = store.add_segments(segments)
        assert added == 1

    def test_stats(self, tmp_path, cfg):
        store = ContextStore(tmp_path, config=cfg)
        stats = store.stats()
        assert stats["dimension"] == 3
        assert stats["backend"] == "openai"
        assert stats["is_initialized"] is False

    def test_persistence(self, tmp_path, cfg):
        store = ContextStore(tmp_path, config=cfg)
        seg = Segment(
            id="s1",
            doc="text/ch01.xhtml",
            anchor=".//p[1]",
            tag="p",
            source_text="你好",
            translated="Hello",
            status="translated",
        )
        mock_emb = MagicMock()
        mock_emb.embed.return_value = [[0.1, 0.2, 0.3]]
        store._embedder = mock_emb
        store.add_segments([seg])
        store.save()

        # Re-create store and load
        store2 = ContextStore(tmp_path, config=cfg)
        assert store2.load() is True
        assert store2.index.count == 1


# ── Embedder tests ────────────────────────────────────────────────


class TestEmbedder:
    @patch("openai.OpenAI")
    def test_embed_one(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_emb = MagicMock()
        mock_emb.embedding = [0.1, 0.2, 0.3]
        mock_response = MagicMock()
        mock_response.data = [mock_emb]
        mock_client.embeddings.create.return_value = mock_response
        mock_openai_cls.return_value = mock_client

        embedder = Embedder(EmbedderConfig(backend="openai", dimension=3, api_key="test-key"))
        result = embedder.embed_one("hello")
        assert isinstance(result, list)
        assert len(result) == 3
        # Vectors are L2-normalised so the flat inner-product index behaves as
        # cosine similarity, exactly as the Ollama path does.
        assert result == pytest.approx([0.1 / 0.3741657, 0.2 / 0.3741657, 0.3 / 0.3741657])
        assert sum(v * v for v in result) == pytest.approx(1.0)

    def test_dimension_property(self):
        embedder = Embedder(EmbedderConfig(backend="openai", dimension=256))
        assert embedder.dimension == 256

    def test_is_available_openai_with_key(self):
        embedder = Embedder(EmbedderConfig(backend="openai", api_key="k"))
        assert embedder.is_available is True

    def test_describe_ollama(self):
        embedder = Embedder(EmbedderConfig(backend="ollama", model="bge-m3"))
        assert embedder.describe() == "ollama:bge-m3 at http://127.0.0.1:11434"

    def test_is_available_openai_no_key(self):
        embedder = Embedder(EmbedderConfig(backend="openai", api_key=""))
        assert embedder.is_available is False


class TestFaissIndexPersistence:
    """Index and metadata must stay aligned across save/load cycles."""

    @staticmethod
    def _vectors(n: int, dim: int = 4):
        import random

        rng = random.Random(11)
        return [[rng.random() for _ in range(dim)] for _ in range(n)]

    @staticmethod
    def _metadata(n: int):
        return [{"segment_id": f"s{i}", "source_text": f"文本{i}"} for i in range(n)]

    def test_round_trip_keeps_metadata_aligned(self, tmp_path):
        from swatl.context.index import FaissIndex

        index = FaissIndex(dimension=4)
        index.add(self._vectors(3), self._metadata(3))
        index.save(tmp_path / "index.faiss")

        loaded = FaissIndex(dimension=4)
        assert loaded.load(tmp_path / "index.faiss") is True
        assert loaded.count == 3
        hits = loaded.query(self._vectors(1, 4)[0], k=3)
        assert {meta["segment_id"] for _i, _s, meta in hits} <= {"s0", "s1", "s2"}

    def test_missing_metadata_is_refused_instead_of_desyncing(self, tmp_path):
        """An index without its metadata cannot be trusted."""
        from swatl.context.index import FaissIndex

        index = FaissIndex(dimension=4)
        index.add(self._vectors(2), self._metadata(2))
        index.save(tmp_path / "index.faiss")
        (tmp_path / "index.json").unlink()

        loaded = FaissIndex(dimension=4)
        assert loaded.load(tmp_path / "index.faiss") is False
        assert loaded.count == 0

    def test_mismatched_metadata_is_refused(self, tmp_path):
        from swatl.context.index import FaissIndex

        index = FaissIndex(dimension=4)
        index.add(self._vectors(3), self._metadata(3))
        index.save(tmp_path / "index.faiss")
        (tmp_path / "index.json").write_text(json.dumps(self._metadata(1)), encoding="utf-8")

        loaded = FaissIndex(dimension=4)
        assert loaded.load(tmp_path / "index.faiss") is False
        assert loaded.count == 0

    def test_remove_works_after_a_save_and_load(self, tmp_path):
        """save() strips the cached vectors, so removal must not rely on them."""
        from swatl.context.index import FaissIndex

        index = FaissIndex(dimension=4)
        index.add(self._vectors(3), self._metadata(3))
        index.save(tmp_path / "index.faiss")

        loaded = FaissIndex(dimension=4)
        assert loaded.load(tmp_path / "index.faiss") is True
        loaded.remove([0])

        assert loaded.count == 2
        assert {m["segment_id"] for m in loaded._metadata} == {"s1", "s2"}
        # The rebuilt index is still queryable.
        assert loaded.query(self._vectors(1, 4)[0], k=2)

    def test_removing_everything_empties_the_index(self, tmp_path):
        from swatl.context.index import FaissIndex

        index = FaissIndex(dimension=4)
        index.add(self._vectors(2), self._metadata(2))
        index.remove([0, 1])
        assert index.is_empty
        assert index.count == 0
