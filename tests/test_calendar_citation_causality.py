import numpy as np
import pandas as pd

from techtrend.prediction.citations import build_patent_citation_monthly, forward_fact
from techtrend.prediction.evaluation import _regression_fold, leak_check
from techtrend.prediction.kleinberg import build_concept_monthly_counts


def test_calendar_gaps_are_recorded_zero_and_cumulative_carry_forward():
    works = [{"publication_date": date, "concepts": [{"id": "C1"}]}
             for date in ("2022-01-01", "2022-04-01")]
    counts = build_concept_monthly_counts(works)
    assert list(counts.columns) == ["2022-01", "2022-02", "2022-03", "2022-04"]
    assert list(counts.loc["C1"]) == [1, 0, 0, 1]
    assert counts.attrs["missing_record_bins"] == ["2022-02", "2022-03"]
    cumulative = build_patent_citation_monthly(
        [{"head": "p", "time": date} for date in ("2022-01-01", "2022-04-01")],
        min_citations=1, sampling="all")
    assert list(cumulative.loc["p"]) == [1, 1, 1, 2]


def test_future_citation_totals_cannot_change_training_cohort(monkeypatch):
    recorded = []
    class Recorder:
        def __init__(self, **kwargs): pass
        def fit(self, x, y): recorded.append((x.copy(), y.copy()))
        def predict(self, x): return np.ones(len(x))
    monkeypatch.setattr("sklearn.ensemble.HistGradientBoostingRegressor", Recorder)
    dates = pd.period_range("2020-01", periods=20, freq="M").astype(str).tolist()
    facts = [{"head": "old", "time": date} for date in dates]
    changed = facts + [{"head": "future_only", "time": date} for date in dates[16:] for _ in range(200)]
    cfg = {"horizon": 2, "lag": 2, "min_history": 6, "top_k": 1, "purge": 0}
    outputs = [_regression_fold(build_patent_citation_monthly(f, min_citations=1, sampling="all"), dates[16], cfg)
               for f in (facts, changed)]
    assert outputs[0]["selected_entities"] == outputs[1]["selected_entities"] == ["old"]
    np.testing.assert_array_equal(recorded[0][0], recorded[1][0])
    np.testing.assert_array_equal(recorded[0][1], recorded[1][1])


def test_missing_citation_event_date_is_never_backdated_to_publication():
    assert forward_fact({"citing": "new", "cited": "old", "cited_date": "1990-01-01"}) is None


def test_empty_boundary_check_does_not_claim_pass():
    assert leak_check([])["ok"] is None
    assert leak_check([([], [{"head": "h", "tail": "t", "time": "2020-01"}])])["ok"] is None
