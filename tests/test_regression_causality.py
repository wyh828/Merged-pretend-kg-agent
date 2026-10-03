import numpy as np
import pandas as pd

from techtrend.prediction.regression import run_regression
from techtrend.prediction.evaluation import _regression_fold, purge_label_overlap


def _record_model(monkeypatch):
    snapshots = []
    class Model:
        def __init__(self, **kwargs): pass
        def fit(self, x, y):
            snapshots.append((x.copy(), y.copy()))
            return self
        def predict(self, x): return x.mean(axis=1)
    monkeypatch.setattr("sklearn.ensemble.HistGradientBoostingRegressor", Model)
    return snapshots


def _fixture():
    columns = pd.period_range("2020-01", periods=30, freq="M").astype(str)
    frame = pd.DataFrame([np.arange(1, 31), np.ones(30)], index=["past", "future"], columns=columns)
    return frame


def test_holdout_cannot_change_regression_selection_labels_or_recent_baseline(monkeypatch):
    snapshots = _record_model(monkeypatch)
    frame = _fixture()
    first = run_regression(frame, horizon=6, min_history=12, top_k=1, lag=3)
    changed = frame.copy()
    changed.iloc[1, -6:] = 1e9
    changed.iloc[0, -6:] = 1e6
    second = run_regression(changed, horizon=6, min_history=12, top_k=1, lag=3)
    assert first["forecasts"][0]["entity_id"] == second["forecasts"][0]["entity_id"] == "past"
    assert first["forecasts"][0]["recent_mean"] == second["forecasts"][0]["recent_mean"]
    assert first["forecasts"][0]["forecast"] == second["forecasts"][0]["forecast"]
    np.testing.assert_array_equal(snapshots[0][0], snapshots[1][0])
    np.testing.assert_array_equal(snapshots[0][1], snapshots[1][1])


def test_walk_forward_selection_is_fitted_per_origin(monkeypatch):
    snapshots = _record_model(monkeypatch)
    frame = _fixture()
    cfg = dict(horizon=3, lag=3, min_history=12, top_k=1, purge=2)
    first = _regression_fold(frame, "2021-07", cfg)
    frame.loc["future", "2021-07":] = 1e9
    second = _regression_fold(frame, "2021-07", cfg)
    assert first["selected_entities"] == second["selected_entities"] == ["past"]
    np.testing.assert_array_equal(snapshots[0][1], snapshots[1][1])


def test_purge_uses_exclusive_label_boundary():
    assert purge_label_overlap([(5, 1), (6, 1)], horizon=3, test_start_idx=10, purge=2) == [(5, 1)]
