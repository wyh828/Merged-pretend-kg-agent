import pytest
from scipy.stats import spearmanr
from techtrend.prediction.metrics import spearman_rho, top1_lift
from techtrend.prediction.fusion import zscore_rank
from techtrend.orchestration.collab import cross_examine


def test_tied_spearman_matches_reference_and_constant_is_undefined():
    x = {"a": 1, "b": 1, "c": 2, "d": 3}
    y = {"a": 3, "b": 2, "c": 2, "d": 1}
    assert spearman_rho(x, y) == pytest.approx(spearmanr(list(x.values()), list(y.values())).statistic)
    assert spearman_rho({"a": 1, "b": 1}, {"a": 1, "b": 2}) is None


def test_lift_uses_entire_evaluation_pool():
    assert top1_lift(["a"], {"a": 10, "b": 2, "c": 3}) == 2


def test_tied_normalized_scores_and_missing_route_are_not_arbitrary():
    assert zscore_rank({"a": 1, "b": 1}) == {"a": .5, "b": .5}
    rows, _ = cross_examine({"a": 3, "b": 1}, {})
    assert rows[0]["consensus"] == 1.
