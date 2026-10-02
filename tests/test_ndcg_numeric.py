import math
import pytest
from techtrend.prediction.metrics import ndcg_at_k


def test_ndcg_handles_large_activity_counts_without_changing_gain():
    relevance = {"a": 2000., "b": 1000.}
    assert ndcg_at_k(["a", "b"], relevance, 2) == pytest.approx(1.)
    assert ndcg_at_k(["b", "a"], relevance, 2) == pytest.approx(1 / math.log2(3))


def test_scaled_gain_matches_original_formula_in_finite_range():
    relevance = {"a": 150., "b": 151., "c": 149.}
    ranked = ["a", "c", "b"]
    def dcg(order):
        return sum((2 ** relevance[t] - 1) / math.log2(i + 2) for i, t in enumerate(order))
    expected = dcg(ranked) / dcg(["b", "a", "c"])
    assert ndcg_at_k(ranked, relevance, 3) == pytest.approx(expected)
