"""Text similarity metrics for the back-translation quality check.

The back-translation check translates a finished English segment back into the
source language and compares the result with the original source text. A high
similarity means the round trip preserved the meaning; a low one means
something was dropped, invented or mistranslated.

Two metrics are provided:

``chrf``
    Character n-gram F-score (Popović, 2015) with ``beta = 2``, the standard
    metric for this job and the default. It is character-based, so it works for
    languages without word delimiters (Chinese) without a tokenizer, and it is
    tolerant of the word-order and morphology differences that make raw edit
    distance misleading. This is a direct port of the reference implementation
    in sacreBLEU (Apache-2.0), restricted to character n-grams; results were
    validated against sacreBLEU itself.

``levenshtein_similarity``
    Normalised edit distance. Kept as a cheaper, coarser alternative.

Both return a score in ``0.0 … 1.0``; the chrF literature usually quotes the
same number scaled to ``0 … 100``.
"""

from __future__ import annotations

from collections import Counter

__all__ = [
    "chrf",
    "cosine_similarity",
    "levenshtein_distance",
    "levenshtein_similarity",
]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors, in ``0 … 1`` for non-negative data.

    Embeddings from the supported backends are L2-normalised, so this is a dot
    product; the norms are still divided out so an unnormalised vector from a
    custom endpoint cannot produce a score outside the documented range.
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# Character n-gram order and recall weight from Popović (2015); these are the
# sacreBLEU defaults (`chrF2`, orders 1-6).
DEFAULT_CHAR_ORDER = 6
DEFAULT_BETA = 2.0

_EPS = 1e-16


def _char_ngrams(text: str, max_order: int, include_whitespace: bool = False) -> list[Counter]:
    """Count character n-grams of orders ``1 … max_order`` in *text*.

    Whitespace is stripped first unless *include_whitespace* is set, matching
    sacreBLEU: the score should not depend on how a gateway happened to space
    its output.
    """
    if not include_whitespace:
        text = "".join(text.split())
    return [
        Counter(text[i : i + n] for i in range(len(text) - n + 1)) for n in range(1, max_order + 1)
    ]


def _match_statistics(hypothesis: Counter, reference: Counter) -> tuple[int, int, int]:
    """Return ``(hypothesis_count, reference_count, match_count)`` for one order.

    An n-gram cannot match anything when the reference has no n-grams at all,
    so the hypothesis count is reported as zero in that case — this is what
    keeps the score at 0 for an empty reference rather than rewarding a long
    translation for matching an empty string.
    """
    hypothesis_count = sum(hypothesis.values()) if reference else 0
    match_count = 0
    for ngram, count in hypothesis.items():
        if ngram in reference:
            match_count += min(count, reference[ngram])
    return hypothesis_count, sum(reference.values()), match_count


def chrf(
    hypothesis: str,
    reference: str,
    *,
    char_order: int = DEFAULT_CHAR_ORDER,
    beta: float = DEFAULT_BETA,
    lowercase: bool = False,
    include_whitespace: bool = False,
) -> float:
    """Character n-gram F-score between *hypothesis* and *reference*, in ``0 … 1``.

    ``beta = 2`` weights recall twice as heavily as precision, so dropping
    source content is punished harder than adding extra words — the failure
    mode that matters when the hypothesis is a back-translation.

    Orders where either side has no n-grams are skipped and the remaining
    orders are averaged (sacreBLEU's "effective order" smoothing), so a
    two-character segment is not scored as if it had failed to produce 6-grams.
    """
    if lowercase:
        hypothesis = hypothesis.lower()
        reference = reference.lower()

    hypothesis_ngrams = _char_ngrams(hypothesis, char_order, include_whitespace)
    reference_ngrams = _char_ngrams(reference, char_order, include_whitespace)

    factor = beta**2
    average_precision = 0.0
    average_recall = 0.0
    effective_order = 0

    for hyp, ref in zip(hypothesis_ngrams, reference_ngrams, strict=True):
        n_hyp, n_ref, n_match = _match_statistics(hyp, ref)
        if n_hyp > 0 and n_ref > 0:
            average_precision += n_match / n_hyp
            average_recall += n_match / n_ref
            effective_order += 1

    if effective_order == 0:
        return 0.0

    average_precision /= effective_order
    average_recall /= effective_order

    denominator = factor * average_precision + average_recall
    if denominator <= _EPS:
        return 0.0

    return ((1 + factor) * average_precision * average_recall) / denominator


def levenshtein_distance(a: str, b: str) -> int:
    """Edit distance between *a* and *b* in O(min(len(a), len(b))) memory.

    Only two rows of the dynamic-programming table are ever alive. The previous
    implementation materialised the whole ``len(a) x len(b)`` matrix, which for
    a 2000-character paragraph meant four million Python ints per comparison.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    # Keep the inner loop over the shorter string.
    if len(a) < len(b):
        a, b = b, a

    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,  # deletion
                    current[j - 1] + 1,  # insertion
                    previous[j - 1] + (char_a != char_b),  # substitution / match
                )
            )
        previous = current

    return previous[-1]


def levenshtein_similarity(a: str, b: str) -> float:
    """Normalised edit similarity in ``0 … 1`` (1.0 means identical)."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return 1.0 - levenshtein_distance(a, b) / max(len(a), len(b))
