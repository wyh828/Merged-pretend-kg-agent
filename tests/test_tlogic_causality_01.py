from techtrend.prediction.tlogic import mine_rules, score_candidates


def test_mined_labels_produce_scores_and_symmetry_uses_incoming_edge():
    train = [{"head": "a", "relation": "uses", "tail": "b", "time": "2020-01-01"},
             {"head": "b", "relation": "uses", "tail": "a", "time": "2021-01-01"}]
    rules = mine_rules(train, min_support=1, min_confidence=0)
    graph = {"edge_time": {(f["head"], f["relation"], f["tail"]): f["time"] for f in train}}
    assert score_candidates("a", "uses", rules, graph, "2022-01-01")["b"] > 0
    # Direction matters: known a -> b alone implies b -> a, never a -> b.
    symmetry = [{"label": "symmetry[uses]", "confidence": 0.7}]
    assert score_candidates("a", "uses", symmetry, {"edge_time": {("a", "uses", "b"): "2020"}}, "2022") == {}


def test_both_body_edges_must_precede_query_and_future_edits_do_not_change_score():
    rules = [{"label": "transitivity[uses,improves]", "confidence": 0.5}]
    past = {("a", "uses", "b"): "2020", ("b", "improves", "c"): "2021"}
    assert score_candidates("a", "uses", rules, {"edge_time": past}, "2022") == {"c": 0.5}
    changed = dict(past, **{})
    changed[("a", "uses", "future")] = "2030"
    changed[("future", "improves", "leaked")] = "2020"
    assert score_candidates("a", "uses", rules, {"edge_time": changed}, "2022") == {"c": 0.5}
    assert score_candidates("a", "uses", rules, {"edge_time": past}, "2021") == {}


def test_implication_matches_target_relation_and_keeps_legacy_single_relation_graph():
    rules = [{"label": "implication[improves->uses]", "confidence": 0.4}]
    graph = {"edge_time": {("a", "improves", "b"): "2020"}}
    assert score_candidates("a", "uses", rules, graph, "2022") == {"b": 0.4}
    assert score_candidates("a", "targets", rules, graph, "2022") == {}
    legacy = {"out": {"a": {"b": "2020"}, "b": {"c": "2020"}}}
    assert score_candidates("a", "r", [{"label": "transitivity", "confidence": 0.6}], legacy, "2021") == {"c": 0.6}
