"""Tests for BM25 keyword retrieval — the no-embedding fallback."""

from __future__ import annotations

from swatl.context.keyword import RELEVANCE_RATIO, BM25Index, tokenize
from swatl.context.retriever import KeywordRetriever, format_context_items


class TestTokenize:
    def test_latin_words_are_lowercased(self):
        assert tokenize("Red Coast Base") == ["red", "coast", "base"]

    def test_cjk_becomes_character_bigrams(self):
        assert tokenize("红岸基地") == ["红岸", "岸基", "基地"]

    def test_single_cjk_character_stays_one_token(self):
        assert tokenize("红") == ["红"]

    def test_mixed_script_and_digits(self):
        tokens = tokenize("红岸基地 Red Coast 2024")
        assert "红岸" in tokens
        assert "red" in tokens
        assert "2024" in tokens

    def test_punctuation_separates_tokens(self):
        assert tokenize("宇宙，很大。") == tokenize("宇宙 很大")

    def test_empty_text_has_no_tokens(self):
        assert tokenize("") == []
        assert tokenize("   ，。！ ") == []


class TestBM25Index:
    ENTRIES = [
        {
            "segment_id": "c1",
            "doc": "ch01.xhtml",
            "source_text": "红岸基地是一座秘密设施。",
            "translated_text": "Red Coast Base is a secret facility.",
        },
        {
            "segment_id": "c2",
            "doc": "ch01.xhtml",
            "source_text": "叶文洁站在窗前，凝视着远处的红岸基地。",
            "translated_text": "Ye Wenjie stood by the window, gazing at Red Coast Base.",
        },
        {
            "segment_id": "c3",
            "doc": "ch02.xhtml",
            "source_text": "宇宙很大，生活更大。",
            "translated_text": "The universe is vast, but life is vaster.",
        },
    ]

    def _index(self) -> BM25Index:
        return BM25Index.from_entries(self.ENTRIES)

    def test_empty_index_returns_nothing(self):
        assert BM25Index().is_empty
        assert BM25Index().query("红岸基地") == []

    def test_exact_term_overlap_ranks_first(self):
        hits = self._index().query("宇宙很大，生活更大。", k=3)
        assert hits
        assert hits[0][2]["segment_id"] == "c3"

    def test_cjk_query_matches_by_bigram(self):
        """A reworded query still shares bigrams with the stored entry."""
        hits = self._index().query("叶文洁凝视着红岸基地的方向", k=3)
        assert hits[0][2]["segment_id"] in {"c1", "c2"}
        assert "叶文洁" in hits[0][2]["source_text"] or "红岸基地" in hits[0][2]["source_text"]

    def test_english_query_matches_translation_text(self):
        hits = self._index().query("the universe is vast", k=3)
        assert hits[0][2]["segment_id"] == "c3"

    def test_unrelated_query_returns_nothing(self):
        assert self._index().query("completely unrelated words here") == []

    def test_doc_filter_restricts_results(self):
        hits = self._index().query("红岸基地 宇宙 生活 更大", k=3, doc_filter="ch02.xhtml")
        assert [h[2]["segment_id"] for h in hits] == ["c3"]

    def test_k_limits_results(self):
        assert len(self._index().query("红岸基地 宇宙 生活 更大", k=1)) == 1

    def test_scores_are_descending(self):
        hits = self._index().query("红岸基地 宇宙 生活 更大", k=3)
        assert [h[1] for h in hits] == sorted([h[1] for h in hits], reverse=True)

    def test_weak_hits_are_dropped(self):
        """A hit far below the best score is noise, not context."""
        index = BM25Index.from_entries(
            [
                {"segment_id": "strong", "source_text": "红岸基地秘密设施"},
                {"segment_id": "weak", "source_text": "红岸基地"},
                {"segment_id": "other", "source_text": "完全不相关的其他内容"},
            ]
        )
        hits = index.query("红岸基地秘密设施", k=3)
        best = hits[0][1]
        assert all(score >= best * RELEVANCE_RATIO for _i, score, _m in hits)
        assert hits[0][2]["segment_id"] == "strong"


class TestKeywordRetriever:
    ENTRIES = TestBM25Index.ENTRIES

    def _retriever(self, **kwargs) -> KeywordRetriever:
        return KeywordRetriever(index=BM25Index.from_entries(self.ENTRIES), **kwargs)

    def test_retrieve_returns_related_entry(self):
        items = self._retriever().retrieve("宇宙很大，生活更大。")
        assert items
        assert items[0].source_text == "宇宙很大，生活更大。"
        assert items[0].translated_text == "The universe is vast, but life is vaster."

    def test_proximity_ids_are_deduplicated(self):
        items = self._retriever().retrieve("宇宙很大，生活更大。", proximity_ids={"c3"})
        assert all(item.segment_id != "c3" for item in items)

    def test_cross_doc_false_needs_a_document(self):
        """Without a document there is nothing to restrict to."""
        retriever = self._retriever(cross_doc=False)
        assert retriever.retrieve("红岸基地") == []

    def test_cross_doc_false_filters_by_document(self):
        retriever = self._retriever(cross_doc=False)
        items = retriever.retrieve("红岸基地 宇宙 生活", current_doc="ch02.xhtml")
        assert [item.doc for item in items] == ["ch02.xhtml"]

    def test_empty_query_returns_nothing(self):
        assert self._retriever().retrieve("") == []

    def test_retrieve_many_matches_batch_shape(self):
        batches = self._retriever().retrieve_many(["宇宙很大，生活更大。", "无关内容"])
        assert len(batches) == 2
        assert batches[0]
        assert batches[1] == []

    def test_formatted_output_is_prompt_ready(self):
        formatted = self._retriever().retrieve_and_format("宇宙很大，生活更大。")
        assert formatted.startswith("Related context")
        assert "[c3] 宇宙很大，生活更大。 → The universe is vast" in formatted

    def test_many_formatted_returns_one_string_per_text(self):
        formatted = self._retriever().retrieve_many_formatted(["宇宙很大", "红岸基地"])
        assert len(formatted) == 2
        assert all(isinstance(entry, str) for entry in formatted)


class TestContextFormatting:
    def test_empty_items_format_to_empty_string(self):
        assert format_context_items([], 100, "label") == ""

    def test_token_cap_stops_the_list(self):
        from swatl.context.retriever import RetrievedContext

        items = [
            RetrievedContext(
                segment_id=f"s{i}",
                source_text="中" * 50,
                translated_text="word " * 10,
                doc="d",
                anchor="a",
                similarity=1.0,
            )
            for i in range(10)
        ]
        # One item costs ~62 tokens (50 CJK chars + 50 ASCII chars), so a cap of
        # 100 admits exactly one and stops.
        formatted = format_context_items(items, max_tokens=100, context_label="L")
        assert formatted.startswith("L:")
        assert formatted.count("[s") == 1

    def test_items_fitting_the_cap_are_all_included(self):
        from swatl.context.retriever import RetrievedContext

        items = [
            RetrievedContext(
                segment_id="s1",
                source_text="短",
                translated_text="short",
                doc="d",
                anchor="a",
                similarity=1.0,
            )
        ]
        assert format_context_items(items, max_tokens=100, context_label="L").count("[s1]") == 1
