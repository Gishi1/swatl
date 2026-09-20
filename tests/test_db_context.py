"""Tests for wiring curated context databases into translation retrieval."""

from __future__ import annotations

import asyncio

import pytest

from swatl.context.db_context import (
    DB_CONTEXT_LABEL,
    build_db_retriever,
    resolve_embedding_config,
)
from swatl.context.embedder import EmbedderConfig, pick_ollama_embedding_model
from swatl.context_db.model import ContextEntry
from swatl.context_db.store import ContextEntryStore
from swatl.models import Segment, SegmentStatus
from swatl.translate.translator import Translator


class StubEmbedder:
    """Deterministic embedder: similar source texts share a direction.

    Texts are mapped onto two axes so retrieval ordering is predictable
    without a model or a network call.
    """

    def __init__(self, dimension: int = 4) -> None:
        self._dimension = dimension
        self.batch_calls = 0

    @property
    def dimension(self) -> int:
        return self._dimension

    def describe(self) -> str:
        return "stub"

    def is_available(self) -> bool:  # pragma: no cover - parity with Embedder
        return True

    def _vector(self, text: str) -> list[float]:
        # Axis 0: "红岸" topics. Axis 1: "智子" topics. Axis 2: everything else.
        if "红岸" in text or "叶文洁" in text:
            return [1.0, 0.0, 0.0, 0.0]
        if "智子" in text:
            return [0.0, 1.0, 0.0, 0.0]
        return [0.0, 0.0, 1.0, 0.0]

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.batch_calls += 1
        return [self._vector(t) for t in texts]

    def embed_one(self, text: str) -> list[float]:
        return self._vector(text)


@pytest.fixture
def store(tmp_path):
    store = ContextEntryStore(tmp_path / "state")
    store.create_many(
        [
            ContextEntry(source_text="叶文洁", translated_text="Ye Wenjie", tags=["person"]),
            ContextEntry(source_text="红岸基地", translated_text="Red Coast Base", tags=["place"]),
            ContextEntry(source_text="智子", translated_text="Sophon", tags=["tech"]),
        ]
    )
    return store


class TestResolveEmbeddingConfig:
    def test_explicit_backend_wins(self):
        resolution = resolve_embedding_config(backend="openai", model="text-embedding-3-small")
        assert resolution.config.backend == "openai"
        assert resolution.config.model == "text-embedding-3-small"
        assert resolution.explicit is True

    def test_explicit_ollama_uses_requested_model(self):
        resolution = resolve_embedding_config(backend="ollama", model="my-embed")
        assert resolution.config.backend == "ollama"
        assert resolution.config.model == "my-embed"
        assert resolution.config.base_url == "http://127.0.0.1:11434"

    def test_config_file_section_is_used(self):
        cfg = EmbedderConfig(backend="ollama", model="from-file", base_url="http://box:11434")
        resolution = resolve_embedding_config(config_file=cfg)
        assert resolution.config.model == "from-file"
        assert resolution.config.base_url == "http://box:11434"
        assert "config section" in resolution.reason

    def test_environment_variables(self, monkeypatch):
        monkeypatch.setenv("SWATL_EMBEDDING_BACKEND", "openai")
        monkeypatch.setenv("SWATL_EMBEDDING_MODEL", "env-model")
        monkeypatch.setenv("SWATL_EMBEDDING_API_KEY", "k")
        resolution = resolve_embedding_config()
        assert resolution.config.backend == "openai"
        assert resolution.config.model == "env-model"
        assert "environment" in resolution.reason

    def test_auto_detect_ollama(self, monkeypatch):
        from swatl.context import db_context

        monkeypatch.setattr(db_context, "ollama_is_available", lambda url, timeout=1.5: True)
        monkeypatch.setattr(
            db_context, "list_ollama_models", lambda url, timeout=3.0: ["bge-m3:latest"]
        )
        resolution = resolve_embedding_config()
        assert resolution.config.backend == "ollama"
        assert resolution.config.model == "bge-m3:latest"
        assert "auto-detected" in resolution.reason

    def test_ollama_without_embedding_model_explains_itself(self, monkeypatch):
        from swatl.context import db_context

        monkeypatch.setattr(db_context, "ollama_is_available", lambda url, timeout=1.5: True)
        monkeypatch.setattr(
            db_context, "list_ollama_models", lambda url, timeout=3.0: ["llama3:8b"]
        )
        resolution = resolve_embedding_config()
        assert resolution.config is None
        assert "ollama pull bge-m3" in resolution.reason

    def test_nothing_available(self, monkeypatch):
        from swatl.context import db_context

        monkeypatch.setattr(db_context, "ollama_is_available", lambda url, timeout=1.5: False)
        resolution = resolve_embedding_config()
        assert resolution.config is None
        assert "no embedding backend" in resolution.reason
        assert "--embedding-url" in resolution.reason


class TestPickOllamaModel:
    def test_prefers_bge_m3(self):
        assert pick_ollama_embedding_model(["llama3:8b", "bge-m3:latest"]) == "bge-m3:latest"

    def test_falls_back_through_the_preference_list(self):
        assert pick_ollama_embedding_model(["nomic-embed-text:latest"]) == "nomic-embed-text:latest"

    def test_no_embedding_model(self):
        assert pick_ollama_embedding_model(["qwen3:0.6b", "llama3:8b"]) is None


class TestBuildDbRetriever:
    def test_empty_database_returns_none(self, tmp_path):
        empty = ContextEntryStore(tmp_path / "empty")
        assert build_db_retriever(empty, EmbedderConfig(), embedder=StubEmbedder()) is None

    def test_retrieves_the_relevant_entry(self, store):
        retriever = build_db_retriever(store, EmbedderConfig(), embedder=StubEmbedder())
        assert retriever is not None
        assert retriever.cross_doc is True  # curated entries apply book-wide
        assert retriever.context_label == DB_CONTEXT_LABEL

        results = retriever.retrieve("叶文洁站在红岸基地的窗前")
        sources = [r.source_text for r in results]
        # The two 红岸-related entries clear the similarity threshold; the
        # unrelated 智子 entry scores zero and is filtered out.
        assert "叶文洁" in sources
        assert "红岸基地" in sources
        assert "智子" not in sources

    def test_formatted_context_uses_the_curated_label(self, store):
        retriever = build_db_retriever(store, EmbedderConfig(), embedder=StubEmbedder())
        text = retriever.retrieve_and_format("智子锁死了基础物理")
        assert text.startswith(DB_CONTEXT_LABEL)
        assert "Sophon" in text

    def test_batch_retrieval_embeds_once(self, store):
        embedder = StubEmbedder()
        retriever = build_db_retriever(store, EmbedderConfig(), embedder=embedder)
        embedder.batch_calls = 0
        formatted = retriever.retrieve_many_formatted(["叶文洁", "智子", "无关的句子"], None, set())
        assert len(formatted) == 3
        assert embedder.batch_calls == 1  # one call for the whole batch
        assert "Ye Wenjie" in formatted[0]
        assert "Sophon" in formatted[1]

    def test_embedder_failure_propagates_for_the_caller_to_handle(self, store):
        class Broken:
            def embed(self, texts):
                raise ConnectionError("ollama is down")

        with pytest.raises(ConnectionError):
            build_db_retriever(store, EmbedderConfig(), embedder=Broken())


class RecordingProvider:
    """Captures the retrieved context handed to each translation call."""

    name = "recording"
    provider_type = "recording"
    cost_per_token_in = 0.0
    cost_per_token_out = 0.0

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def translate(
        self,
        segments,
        glossary=None,
        target_lang="en",
        context=None,
        retrieved_contexts=None,
        system_prompt=None,
    ):
        self.calls.append({"ids": [s.id for s in segments], "retrieved": retrieved_contexts})
        for seg in segments:
            seg.translated = f"[{seg.id}]"
            seg.status = SegmentStatus.TRANSLATED
        return segments

    async def proofread(self, segments, glossary=None):
        return segments

    async def test(self):
        return {"ok": True}


class TestTranslatorInjection:
    def _segments(self, n: int):
        return [
            Segment(
                id=f"p-{i:04d}",
                doc="text/ch01.xhtml",
                anchor=f".//p[{i}]",
                tag="p",
                source_text="叶文洁站在红岸基地的窗前。" if i % 2 else "智子锁死了基础物理。",
            )
            for i in range(1, n + 1)
        ]

    def test_retrieved_context_reaches_the_provider(self, store):
        retriever = build_db_retriever(store, EmbedderConfig(), embedder=StubEmbedder())
        provider = RecordingProvider()
        translator = Translator(provider, "zh", "en", batch_size=4, context_retriever=retriever)
        asyncio.run(translator.translate_all(self._segments(4), None))

        assert len(provider.calls) == 1
        retrieved = provider.calls[0]["retrieved"]
        assert len(retrieved) == 4
        assert all(r and r.startswith(DB_CONTEXT_LABEL) for r in retrieved)

    def test_batches_are_embedded_in_one_call(self, store):
        """Two batches of four must embed twice, not eight times."""
        embedder = StubEmbedder()
        retriever = build_db_retriever(store, EmbedderConfig(), embedder=embedder)
        provider = RecordingProvider()
        translator = Translator(provider, "zh", "en", batch_size=4, context_retriever=retriever)

        embedder.batch_calls = 0
        asyncio.run(translator.translate_all(self._segments(8), None))
        assert len(provider.calls) == 2
        assert embedder.batch_calls == 2

    def test_without_a_retriever_nothing_is_injected(self):
        provider = RecordingProvider()
        translator = Translator(provider, "zh", "en", batch_size=4)
        asyncio.run(translator.translate_all(self._segments(2), None))
        assert provider.calls[0]["retrieved"] == [None, None]

    def test_retriever_failure_does_not_lose_segments(self, store):
        """A broken retriever must not silently drop a batch to failed."""

        class FlakyRetriever:
            def retrieve_many_formatted(self, texts, docs, proximity_ids):
                raise RuntimeError("embedding backend died")

        provider = RecordingProvider()
        translator = Translator(provider, "zh", "en", batch_size=4, retry_max=1)
        translator.context_retriever = FlakyRetriever()
        result = asyncio.run(translator.translate_all(self._segments(2), None))

        # The translator retries the batch, and with retry_max=1 it gives up and
        # marks the segments failed rather than crashing the run.
        assert all(seg.status == SegmentStatus.FAILED for seg in result)


ollama_available = pytest.mark.skipif(
    not __import__("swatl.context", fromlist=["ollama_is_available"]).ollama_is_available(),
    reason="no Ollama server reachable",
)


@ollama_available
class TestOllamaIntegration:
    """Exercises the real embedding backend when a local Ollama is running.

    Skipped elsewhere, so the suite still passes on a machine without one.
    """

    def test_embeddings_are_dense_and_normalised(self, store):
        from swatl.context import list_ollama_models, pick_ollama_embedding_model

        model = pick_ollama_embedding_model(list_ollama_models())
        assert model, "no embedding model installed on the Ollama server"

        from swatl.context.embedder import Embedder

        embedder = Embedder(EmbedderConfig(backend="ollama", model=model))
        vectors = embedder.embed(["你好世界", "Hello world"])
        assert len(vectors) == 2
        assert len(vectors[0]) == embedder.dimension > 0
        norm = sum(v * v for v in vectors[0]) ** 0.5
        assert abs(norm - 1.0) < 1e-6  # normalised for cosine search

    def test_retrieval_ranks_the_relevant_entry_first(self, tmp_path):
        """The stub proves wiring; this proves real semantic ranking."""
        from swatl.context import list_ollama_models, pick_ollama_embedding_model
        from swatl.context.embedder import Embedder

        model = pick_ollama_embedding_model(list_ollama_models())
        if not model:
            pytest.skip("no embedding model installed on the Ollama server")

        db = ContextEntryStore(tmp_path / "state")
        db.create_many(
            [
                ContextEntry(source_text="红岸基地", translated_text="Red Coast Base"),
                ContextEntry(source_text="叶文洁", translated_text="Ye Wenjie"),
                ContextEntry(source_text="智子", translated_text="Sophon"),
                ContextEntry(
                    source_text="低温超导材料", translated_text="low-temperature superconductor"
                ),
            ]
        )
        embedder = Embedder(EmbedderConfig(backend="ollama", model=model, dimension=0))
        retriever = build_db_retriever(db, EmbedderConfig(), embedder=embedder, min_score=0.0)

        top = retriever.retrieve("智子锁死了人类的基础物理研究")[0]
        assert top.source_text == "智子"
        assert top.translated_text == "Sophon"


class TestProofreaderSkipsMTModels:
    """A translation-only model must not be marked as having proofread."""

    def test_proofread_all_is_a_no_op_for_plain_providers(self, caplog):
        from swatl.proofread.proofreader import Proofreader
        from swatl.providers.openai_compat import OpenAICompatible

        provider = OpenAICompatible("https://mt/v1", "hy-mt2", mode="plain")
        segments = [
            Segment(
                id="p-0001",
                doc="d",
                anchor=".//p[1]",
                tag="p",
                source_text="中文",
                translated="Red Coast Base",
                status=SegmentStatus.TRANSLATED,
            )
        ]
        with caplog.at_level("WARNING"):
            result = asyncio.run(Proofreader(provider).proofread_all(segments))

        assert result[0].status == SegmentStatus.TRANSLATED  # unchanged, not "proofread"
        assert result[0].translated == "Red Coast Base"
        assert any("cannot proofread" in r.message for r in caplog.records)


class TestProofreaderDoesNotClaimFailedWork:
    """A failed proofread must not be recorded as a successful one.

    The provider returns the segment untouched when the HTTP request fails, so
    the original (truthy) translation used to satisfy the success check and the
    segment was marked PROOFREAD although nothing had been proofread.
    """

    @staticmethod
    def _seg() -> Segment:
        return Segment(
            id="p-0001",
            doc="d",
            anchor=".//p[1]",
            tag="p",
            source_text="红岸基地",
            translated="Red Coast Base",
            status=SegmentStatus.TRANSLATED,
        )

    def test_provider_failure_keeps_the_segment_translated(self):
        from swatl.proofread.proofreader import Proofreader

        class FailingProvider:
            mode = "json"
            model = "chat"

            async def proofread(self, segments, glossary=None):
                # Mirrors OpenAICompatible: unchanged text, status untouched.
                return list(segments)

        seg = self._seg()
        result = asyncio.run(Proofreader(FailingProvider(), retry_max=1).proofread_all([seg]))

        assert result[0].status == SegmentStatus.TRANSLATED
        assert result[0].translated == "Red Coast Base"

    def test_successful_proofread_is_marked(self):
        from swatl.proofread.proofreader import Proofreader

        class ImprovingProvider:
            mode = "json"
            model = "chat"

            async def proofread(self, segments, glossary=None):
                out = []
                for seg in segments:
                    seg.translated = seg.translated + "."
                    seg.status = SegmentStatus.PROOFREAD
                    out.append(seg)
                return out

        seg = self._seg()
        result = asyncio.run(Proofreader(ImprovingProvider()).proofread_all([seg]))

        assert result[0].status == SegmentStatus.PROOFREAD
        assert result[0].translated == "Red Coast Base."
