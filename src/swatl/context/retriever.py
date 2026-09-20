"""High-level context retrieval: fetch, deduplicate, and format for prompt injection."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from swatl.context.embedder import Embedder
from swatl.context.index import FaissIndex
from swatl.context.keyword import BM25Index

logger = logging.getLogger(__name__)


KEYWORD_CONTEXT_LABEL = "Related context (keyword match, from the context database)"


@dataclass
class RetrievedContext:
    """A retrieved context item to inject into a translation prompt."""

    segment_id: str
    source_text: str
    translated_text: str
    doc: str
    anchor: str
    similarity: float


@dataclass
class ContextRetriever:
    """Retrieves semantically similar segments and formats them for prompts.

    Integrates the embedder and FAISS index to:
    1. Embed the source text of the current segment
    2. Query the index for nearest neighbors
    3. Deduplicate against an existing context window (proximity)
    4. Format as source → target pairs for injection
    """

    embedder: Embedder
    index: FaissIndex
    k: int = 5  # number of results to retrieve
    min_score: float = 0.2  # minimum cosine similarity threshold
    cross_doc: bool = False  # allow retrieval across documents
    max_tokens: int = 2000  # cap injected context in tokens
    context_label: str = "Related context (semantically similar, from earlier in the document)"

    def retrieve(
        self,
        source_text: str,
        current_doc: str | None = None,
        proximity_ids: set[str] | None = None,
    ) -> list[RetrievedContext]:
        """Retrieve context for a single source text.

        Args:
            source_text: The source text of the segment being translated.
            current_doc: Current document path (e.g. "text/ch01.xhtml").
            proximity_ids: Segment IDs already in the proximity window (to deduplicate).

        Returns:
            List of RetrievedContext objects, sorted by similarity descending.
        """
        return self.retrieve_many([source_text], [current_doc], proximity_ids)[0]

    def retrieve_many(
        self,
        source_texts: list[str],
        current_docs: list[str | None] | None = None,
        proximity_ids: set[str] | None = None,
    ) -> list[list[RetrievedContext]]:
        """Retrieve context for a batch of texts with a single embed call.

        Embedding is the expensive part, so batching it keeps a translation run
        to one embedding request per translation batch instead of one per
        segment.
        """
        if self.index.is_empty or not source_texts:
            return [[] for _ in source_texts]

        vectors = self.embedder.embed(source_texts)
        if len(vectors) != len(source_texts):
            logger.warning(
                "Embedder returned %d vectors for %d texts", len(vectors), len(source_texts)
            )
            return [[] for _ in source_texts]

        docs = current_docs or [None] * len(source_texts)
        return [
            self._query_one(vector, docs[i] if i < len(docs) else None, proximity_ids)
            for i, vector in enumerate(vectors)
        ]

    def _query_one(
        self,
        vector: list[float],
        current_doc: str | None,
        proximity_ids: set[str] | None,
    ) -> list[RetrievedContext]:
        if not vector:
            return []

        # Apply document filter. `cross_doc=False` means "only the current
        # document": when the caller does not say which document that is, no
        # entry can satisfy the constraint, so the search is skipped instead of
        # silently returning hits from every unrelated document.
        if self.cross_doc:
            doc_filter = None
        elif current_doc is None:
            logger.warning(
                "Retrieval is limited to the current document but none was given; "
                "returning no context. Pass current_doc, or build the retriever "
                "with cross_doc=True."
            )
            return []
        else:
            doc_filter = current_doc

        # Query the index
        results = self.index.query(
            vector, k=self.k, doc_filter=doc_filter, min_score=self.min_score
        )

        # Build RetrievedContext objects, deduplicating against proximity_ids
        seen_ids: set[str] = set(proximity_ids or set())
        context_items: list[RetrievedContext] = []
        for faiss_id, score, meta in results:
            seg_id = meta.get("segment_id", f"ctx-{faiss_id}")
            if seg_id in seen_ids:
                continue
            context_items.append(
                RetrievedContext(
                    segment_id=seg_id,
                    source_text=meta.get("source_text", ""),
                    translated_text=meta.get("translated_text", ""),
                    doc=meta.get("doc", ""),
                    anchor=meta.get("anchor", ""),
                    similarity=score,
                )
            )
            seen_ids.add(seg_id)

        return context_items

    def format_context(
        self,
        context_items: list[RetrievedContext],
    ) -> str:
        """Format retrieved context items into a prompt-friendly string."""
        return format_context_items(context_items, self.max_tokens, self.context_label)

    def retrieve_and_format(
        self,
        source_text: str,
        current_doc: str | None = None,
        proximity_ids: set[str] | None = None,
    ) -> str:
        """Retrieve context and format it for prompt injection (convenience method)."""
        items = self.retrieve(source_text, current_doc, proximity_ids)
        return self.format_context(items)

    def retrieve_many_formatted(
        self,
        source_texts: list[str],
        current_docs: list[str | None] | None = None,
        proximity_ids: set[str] | None = None,
    ) -> list[str]:
        """Batch variant of :meth:`retrieve_and_format`."""
        batches = self.retrieve_many(source_texts, current_docs, proximity_ids)
        return [self.format_context(items) for items in batches]


def format_context_items(
    context_items: list[RetrievedContext],
    max_tokens: int,
    context_label: str,
) -> str:
    """Render retrieved items as prompt text, capped at *max_tokens*.

    Returns a string like:
        [p-0012] 这个概念来自爱因斯坦的相对论。 → This concept comes from Einstein's theory of relativity.
        [p-0047] 爱因斯坦提出了这一理论。 → Einstein proposed this theory.
    """
    if not context_items:
        return ""

    lines: list[str] = []
    total_tokens = 0
    for item in context_items:
        line = f"[{item.segment_id}] {item.source_text} → {item.translated_text}"
        # Rough token estimate: 1 token per CJK char, 4 ASCII chars per token.
        text = item.source_text + item.translated_text
        cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        ascii_chars = len(text) - cjk
        tokens = cjk + ascii_chars // 4
        if total_tokens + tokens > max_tokens:
            break
        lines.append(line)
        total_tokens += tokens

    if not lines:
        return ""

    return context_label + ":\n" + "\n".join(lines)


@dataclass
class KeywordRetriever:
    """Context retrieval by BM25 keyword overlap, with no embedding backend.

    Same public surface as :class:`ContextRetriever`, so the translator does not
    care which one it holds. ``similarity`` carries a BM25 score, which is
    unbounded rather than a 0-1 cosine value.
    """

    index: BM25Index
    k: int = 5
    cross_doc: bool = True
    max_tokens: int = 2000
    context_label: str = KEYWORD_CONTEXT_LABEL

    def retrieve(
        self,
        source_text: str,
        current_doc: str | None = None,
        proximity_ids: set[str] | None = None,
    ) -> list[RetrievedContext]:
        """Retrieve context for a single source text."""
        return self.retrieve_many([source_text], [current_doc], proximity_ids)[0]

    def retrieve_many(
        self,
        source_texts: list[str],
        current_docs: list[str | None] | None = None,
        proximity_ids: set[str] | None = None,
    ) -> list[list[RetrievedContext]]:
        """Retrieve context for a batch of texts."""
        if self.index.is_empty or not source_texts:
            return [[] for _ in source_texts]

        docs = current_docs or [None] * len(source_texts)
        return [
            self._query_one(text, docs[i] if i < len(docs) else None, proximity_ids)
            for i, text in enumerate(source_texts)
        ]

    def _query_one(
        self,
        text: str,
        current_doc: str | None,
        proximity_ids: set[str] | None,
    ) -> list[RetrievedContext]:
        if not text.strip():
            return []

        if self.cross_doc:
            doc_filter = None
        elif current_doc is None:
            logger.warning(
                "Retrieval is limited to the current document but none was given; "
                "returning no context. Pass current_doc, or build the retriever "
                "with cross_doc=True."
            )
            return []
        else:
            doc_filter = current_doc

        seen_ids: set[str] = set(proximity_ids or set())
        context_items: list[RetrievedContext] = []
        for _index, score, meta in self.index.query(text, k=self.k, doc_filter=doc_filter):
            segment_id = meta.get("segment_id", "")
            if segment_id in seen_ids:
                continue
            context_items.append(
                RetrievedContext(
                    segment_id=segment_id,
                    source_text=meta.get("source_text", ""),
                    translated_text=meta.get("translated_text", ""),
                    doc=meta.get("doc", ""),
                    anchor=meta.get("anchor", ""),
                    similarity=score,
                )
            )
            seen_ids.add(segment_id)

        return context_items

    def format_context(self, context_items: list[RetrievedContext]) -> str:
        """Format retrieved context items into a prompt-friendly string."""
        return format_context_items(context_items, self.max_tokens, self.context_label)

    def retrieve_and_format(
        self,
        source_text: str,
        current_doc: str | None = None,
        proximity_ids: set[str] | None = None,
    ) -> str:
        """Retrieve context and format it for prompt injection."""
        return self.format_context(self.retrieve(source_text, current_doc, proximity_ids))

    def retrieve_many_formatted(
        self,
        source_texts: list[str],
        current_docs: list[str | None] | None = None,
        proximity_ids: set[str] | None = None,
    ) -> list[str]:
        """Batch variant of :meth:`retrieve_and_format`."""
        batches = self.retrieve_many(source_texts, current_docs, proximity_ids)
        return [self.format_context(items) for items in batches]
