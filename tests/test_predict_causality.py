import json
from techtrend.config import Settings
from techtrend.io import write_jsonl
from techtrend.stages.predict import PredictStage
from techtrend.orchestration.collab import link_agent_scores, score_cache_payload


def test_fusion_tkg_receives_only_common_history_and_replaces_stale_cache(monkeypatch, tmp_path):
    settings = Settings(data_dir=tmp_path / "data", output_dir=tmp_path / "output", burst_future_months=2)
    works = [{"id": str(i), "publication_date": f"2020-{i:02d}-01", "concepts": [{"id": "C1"}]} for i in range(1, 7)]
    triples = [{"head": "a", "tail": "b", "relation": "r", "time": "2020-02-01"}, {"head": "a", "tail": "new", "relation": "r", "time": "2020-05-01"}]
    write_jsonl(settings.data_dir / "interim/works.jsonl", works)
    write_jsonl(settings.data_dir / "interim/triples.jsonl", triples)
    seen = []
    monkeypatch.setattr(PredictStage, "_run_tkg", lambda self, s, data, out: seen.extend(data) or {"_tkg_scores": {}})
    for method in ("_run_kleinberg", "_run_share_signal", "_run_rotate", "_run_forecast", "_run_fusion"):
        monkeypatch.setattr(PredictStage, method, lambda *_args, **_kwargs: {})
    result = PredictStage(settings).run()
    assert result["status"] == "ok"
    assert seen == triples[:1]
    cached = json.loads((settings.output_dir / "tkg_scores.json").read_text(encoding="utf-8"))
    assert cached["scores"] == {}
    assert result["fusion_as_of"] == "2020-05"


def test_cached_scores_require_matching_data_and_configuration(tmp_path):
    settings = Settings(output_dir=tmp_path)
    triples = []
    path = tmp_path / "tkg_scores.json"
    path.write_text(json.dumps(score_cache_payload({"a": .5}, triples, settings)), encoding="utf-8")
    assert link_agent_scores(triples, settings) == {"a": .5}
    settings.tkg_edge_source = "directed"
    assert link_agent_scores(triples, settings) == {}
