from techtrend.prediction.temporal import fit_graph_scope, apply_graph_scope
from techtrend.prediction import evaluation as ev


def fact(head, tail, time):
    return dict(head=head, tail=tail, relation="r", time=time)


def test_test_edges_do_not_supply_training_support_or_degree():
    train = [fact("a", "b", "2020-01"), fact("a", "b", "2020-02"), fact("c", "d", "2020-01")]
    scope = fit_graph_scope(train, min_support=2, max_entities=2)
    future = [fact("c", "d", "2021-01")] * 100
    assert apply_graph_scope(train, scope, training=True) == train[:2]
    assert apply_graph_scope(future, scope) == []
    assert scope["entities"] == {"a", "b"}


def test_new_links_between_past_entities_remain_test_targets():
    train = [fact("a", "b", "2020-01"), fact("b", "c", "2020-01")]
    scope = fit_graph_scope(train)
    novel = [fact("a", "c", "2021-01")]
    assert apply_graph_scope(novel, scope) == novel


def test_walkforward_training_unchanged_after_future_perturbation(monkeypatch):
    observed = []
    def fold(train, test, cfg):
        observed.append(list(train))
        return {"tkg_mrr": .1}
    monkeypatch.setattr(ev, "_tkg_fold", fold)
    train = [fact("a", "b", "2020-01"), fact("a", "b", "2020-02"), fact("c", "d", "2020-01")]
    cfg = dict(n_splits=1, test_months=1, step_months=1, embargo_months=0, mode="expanding", rolling_window_months=24, min_train=1, min_support=2, max_entities=2)
    base = train + [fact("a", "b", "2021-01")]
    ev.backtest_tkg(base, cfg)
    ev.backtest_tkg(base + [fact("c", "d", "2021-01")] * 100, cfg)
    assert observed[0] == observed[1] == train[:2]
