"""Tests for the similarity metrics used by the back-translation check.

The chrF expectations below were verified against sacreBLEU 2.6.0
(``CHRF(char_order=6, word_order=0, beta=2)``); the values are hardcoded here so
the suite does not depend on sacreBLEU being installed.
"""

from __future__ import annotations

import random

import pytest

from swatl.quality.metrics import chrf, levenshtein_distance, levenshtein_similarity


class TestChrf:
    def test_identical_text_scores_one(self):
        assert chrf("红岸基地是一座秘密设施。", "红岸基地是一座秘密设施。") == pytest.approx(1.0)

    def test_close_variant_scores_high(self):
        """One character differs (座 -> 个): still clearly a match."""
        assert chrf("红岸基地是一个秘密设施。", "红岸基地是一座秘密设施。") == pytest.approx(
            0.584710, abs=1e-6
        )

    def test_unrelated_text_scores_low(self):
        assert chrf("你好世界", "今天天气很好") == pytest.approx(0.044643, abs=1e-6)

    def test_wrong_rendering_of_same_name_is_low(self):
        """A different place name must not pass as the same sentence."""
        score = chrf("红色海岸基地是秘密的。", "红岸基地是一座秘密设施。")
        assert score == pytest.approx(0.227679, abs=1e-6)
        assert score < 0.3

    def test_empty_hypothesis_scores_zero(self):
        assert chrf("", "红岸基地是一座秘密设施。") == 0.0

    def test_empty_reference_scores_zero(self):
        """An empty reference must not reward a long hypothesis."""
        assert chrf("红岸基地是一座秘密设施。", "") == 0.0

    def test_both_empty_scores_zero(self):
        assert chrf("", "") == 0.0

    def test_whitespace_is_ignored_by_default(self):
        assert chrf("hello world", "hello world") == pytest.approx(1.0)
        assert chrf("helloworld", "hello world") == pytest.approx(1.0)

    def test_punctuation_and_spacing_differences_tolerated(self):
        score = chrf(
            "叶文洁站在窗前，凝视着远处的红岸基地。", "叶文洁站在窗前,凝视着远处的红岸基地。"
        )
        assert score == pytest.approx(0.774647, abs=1e-6)

    def test_lowercase_option(self):
        assert chrf("HELLO", "hello", lowercase=True) == pytest.approx(1.0)
        assert chrf("HELLO", "hello", lowercase=False) < 1.0

    def test_scores_stay_in_range(self):
        rng = random.Random(1234)
        alphabet = "红岸基地秘密设施宇宙故事abc "
        for _ in range(200):
            a = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 30)))
            b = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 30)))
            assert 0.0 <= chrf(a, b) <= 1.0

    def test_beta_two_favours_recall(self):
        """Dropping reference content must cost more than adding extra words."""
        reference = "the quick brown fox jumps over the lazy dog"
        dropped = "the quick brown fox"
        padded = "the quick brown fox jumps over the lazy dog and then some more words"
        assert chrf(dropped, reference) < chrf(padded, reference)

    def test_symmetric_for_identical_input(self):
        assert chrf("中文文本", "中文文本") == chrf("中文文本", "中文文本")


class TestLevenshtein:
    @staticmethod
    def _naive(a: str, b: str) -> int:
        """Textbook full-matrix implementation, used as the oracle."""
        m, n = len(a), len(b)
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        for i in range(m + 1):
            dp[i][0] = i
        for j in range(n + 1):
            dp[0][j] = j
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if a[i - 1] == b[j - 1]:
                    dp[i][j] = dp[i - 1][j - 1]
                else:
                    dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])
        return dp[m][n]

    def test_matches_naive_implementation(self):
        """The rolling-row version must agree with the textbook algorithm."""
        rng = random.Random(7)
        alphabet = "abc红岸基地"
        for _ in range(300):
            a = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 12)))
            b = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 12)))
            assert levenshtein_distance(a, b) == self._naive(a, b), (a, b)

    def test_handles_long_strings(self):
        """A long paragraph must not blow up memory or time."""
        a = "红岸基地是一座秘密设施。" * 400
        b = "红岸基地是一座秘密设施。" * 400
        assert levenshtein_distance(a, b) == 0
        assert levenshtein_similarity(a, b) == pytest.approx(1.0)

    def test_similarity_bounds(self):
        assert levenshtein_similarity("", "") == 1.0
        assert levenshtein_similarity("a", "") == 0.0
        assert levenshtein_similarity("", "b") == 0.0
        assert levenshtein_similarity("abc", "abc") == 1.0
        assert levenshtein_similarity("abc", "abd") == pytest.approx(2 / 3)

    def test_similarity_is_bounded(self):
        rng = random.Random(99)
        for _ in range(100):
            a = "".join(rng.choice("abcdef") for _ in range(rng.randint(0, 10)))
            b = "".join(rng.choice("abcdef") for _ in range(rng.randint(0, 10)))
            assert 0.0 <= levenshtein_similarity(a, b) <= 1.0
