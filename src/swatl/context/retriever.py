"""High-level context retrieval: fetch, deduplicate, and format for prompt injection."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from swatl.context.embedder import Embedder
from swatl.context.index import FaissIndex

logger = logging.getLogger(__name__)


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
        if self.index.is_empty:
            return []

        # Embed the source text
        vector = self.embedder.embed_one(source_text)
        if not vector:
            return []

        # Apply document filter
        doc_filter = None if self.cross_doc else current_doc

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

        logger.debug(
            "Retrieved %d context items for '%s' (filtered from %d)",
            len(context_items),
            source_text[:40],
            len(results),
        )
        return context_items

    def format_context(
        self,
        context_items: list[RetrievedContext],
    ) -> str:
        """Format retrieved context items into a prompt-friendly string.

        Returns a string like:
            [p-0012] 这个概念来自爱因斯坦的相对论。 → This concept comes from Einstein's theory of relativity.
            [p-0047] 爱因斯坦提出了这一理论。 → Einstein proposed this theory.
        """
        if not context_items:
            return ""

        # Estimate tokens and cap at max_tokens
        lines: list[str] = []
        total_tokens = 0
        for item in context_items:
            line = f"[{item.segment_id}] {item.source_text} → {item.translated_text}"
            # Rough token estimate: 1 char per CJK, 4 chars per English token
            cjk = sum(
                1 for c in item.source_text + item.translated_text if "\u4e00" <= c <= "\u9fff"
            )
            ascii_chars = len(item.source_text + item.translated_text) - cjk
            tokens = cjk + ascii_chars // 4
            if total_tokens + tokens > self.max_tokens:
                break
            lines.append(line)
            total_tokens += tokens

        if not lines:
            return ""

        return (
            "Related context (semantically similar, from earlier in the document):\n"
            + "\n".join(lines)
        )

    def retrieve_and_format(
        self,
        source_text: str,
        current_doc: str | None = None,
        proximity_ids: set[str] | None = None,
    ) -> str:
        """Retrieve context and format it for prompt injection (convenience method)."""
        items = self.retrieve(source_text, current_doc, proximity_ids)
        return self.format_context(items)
