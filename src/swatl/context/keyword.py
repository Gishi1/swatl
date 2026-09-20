"""Keyword retrieval (BM25) for context databases, with no embedding backend.

Embedding-based retrieval gives better matches, but it needs a running model:
the default backend asks for Ollama plus a `bge-m3` pull (about 1.2 GB). When
none is available, this module keeps the context feature useful by scoring
entries against the query with BM25 — a well-understood lexical ranking function
that needs nothing but the standard library.

Scoring is Okapi BM25 (``k1 = 1.5``, ``b = 0.75``) with Lucene's non-negative
idf form, ``idf = ln(1 + (N - df + 0.5) / (df + 0.5))``. The plain
``ln((N - df + 0.5) / (df + 0.5))`` form goes negative whenever a term appears
in more than half the documents, and in a small database that is *every* term —
with a single stored entry it scored the only relevant entry below zero and the
match was discarded. Adding one inside the logarithm keeps idf positive and
still ranks rare terms above common ones.

Chinese has no word delimiters, so tokens are built without a dictionary: a run
of CJK characters becomes its character bigrams (a single character if the run
is one character long) and a run of Latin letters or digits becomes one
lower-cased word. Single CJK characters are far too common to discriminate, and
bigrams are the standard tokenizer-free compromise.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

# CJK ideographs, kana and hangul: text that is written without spaces.
_CJK_RE = re.compile("[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]")

# Scoring parameters (Okapi defaults).
DEFAULT_K1 = 1.5
DEFAULT_B = 0.75

# Hits scoring below this fraction of the best hit are dropped: BM25 scores have
# no absolute scale, so a fixed cut-off would behave differently on every corpus.
RELEVANCE_RATIO = 0.15


def tokenize(text: str) -> list[str]:
    """Split *text* into BM25 terms, handling languages without word breaks."""
    tokens: list[str] = []
    latin: list[str] = []
    cjk: list[str] = []

    def flush_latin() -> None:
        if latin:
            tokens.append("".join(latin).lower())
            latin.clear()

    def flush_cjk() -> None:
        if not cjk:
            return
        run = "".join(cjk)
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
        cjk.clear()

    for char in text:
        if _CJK_RE.match(char):
            flush_latin()
            cjk.append(char)
        elif char.isalnum():
            flush_cjk()
            latin.append(char)
        else:
            flush_latin()
            flush_cjk()
    flush_latin()
    flush_cjk()
    return tokens


@dataclass
class BM25Index:
    """A BM25 index over stored context entries."""

    k1: float = DEFAULT_K1
    b: float = DEFAULT_B
    _doc_freqs: list[Counter] = field(default_factory=list, repr=False)
    _doc_lengths: list[int] = field(default_factory=list, repr=False)
    _idf: dict[str, float] = field(default_factory=dict, repr=False)
    _metadata: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _average_length: float = 0.0

    def __init__(
        self,
        documents: list[list[str]] | None = None,
        metadata: list[dict[str, Any]] | None = None,
        *,
        k1: float = DEFAULT_K1,
        b: float = DEFAULT_B,
    ) -> None:
        self.k1 = k1
        self.b = b
        self._doc_freqs = []
        self._doc_lengths = []
        self._idf = {}
        self._metadata = list(metadata or [])
        self._average_length = 0.0
        if documents:
            self._build(documents)

    # ── Construction ────────────────────────────────────────────────────

    def _build(self, documents: list[list[str]]) -> None:
        document_frequency: Counter = Counter()
        total_length = 0

        for document in documents:
            frequencies = Counter(document)
            self._doc_freqs.append(frequencies)
            self._doc_lengths.append(len(document))
            total_length += len(document)
            document_frequency.update(frequencies.keys())

        corpus_size = len(documents)
        self._average_length = total_length / corpus_size if corpus_size else 0.0

        for term, frequency in document_frequency.items():
            # The "+ 1" keeps this positive for every term, including one that
            # appears in every document (see the module docstring).
            self._idf[term] = math.log(1 + (corpus_size - frequency + 0.5) / (frequency + 0.5))

    @classmethod
    def from_entries(cls, entries: list[dict[str, Any]]) -> BM25Index:
        """Build an index over entries with ``source_text``/``translated_text``."""
        documents = [
            tokenize(f"{entry.get('source_text', '')} {entry.get('translated_text', '')}")
            for entry in entries
        ]
        return cls(documents, entries)

    # ── Query ───────────────────────────────────────────────────────────

    @property
    def size(self) -> int:
        return len(self._doc_freqs)

    @property
    def is_empty(self) -> bool:
        return not self._doc_freqs or self._average_length == 0

    def query(
        self,
        text: str,
        k: int = 5,
        doc_filter: str | None = None,
    ) -> list[tuple[int, float, dict[str, Any]]]:
        """Return up to *k* ``(index, score, metadata)`` hits, best first.

        Hits below :data:`RELEVANCE_RATIO` of the best score are dropped: BM25
        has no absolute scale, so a fixed threshold would mean something
        different on every corpus.
        """
        if self.is_empty:
            return []

        terms = tokenize(text)
        if not terms:
            return []

        scores = [0.0] * len(self._doc_freqs)
        for term in terms:
            idf = self._idf.get(term)
            if idf is None:
                continue
            for index, frequencies in enumerate(self._doc_freqs):
                frequency = frequencies.get(term)
                if not frequency:
                    continue
                length_norm = (
                    1 - self.b + self.b * (self._doc_lengths[index] / self._average_length)
                )
                scores[index] += (
                    idf * (frequency * (self.k1 + 1)) / (frequency + self.k1 * length_norm)
                )

        ranked = sorted(
            ((index, score) for index, score in enumerate(scores) if score > 0),
            key=lambda pair: pair[1],
            reverse=True,
        )
        if not ranked:
            return []

        cutoff = ranked[0][1] * RELEVANCE_RATIO
        hits: list[tuple[int, float, dict[str, Any]]] = []
        for index, score in ranked:
            if score < cutoff:
                break
            meta = self._metadata[index] if index < len(self._metadata) else {}
            if doc_filter is not None and meta.get("doc") != doc_filter:
                continue
            hits.append((index, score, meta))
            if len(hits) >= k:
                break
        return hits
