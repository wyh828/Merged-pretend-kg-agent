from techtrend.config import Settings
from techtrend.stages import collect


def test_partial_source_failure_is_reported_and_other_source_continues(monkeypatch, tmp_path):
    def fail(*_): raise RuntimeError("test failure")
    monkeypatch.setattr(collect, "_HANDLERS", {"bad": fail, "good": lambda *_: 3})
    result = collect.CollectStage(Settings(data_dir=tmp_path, collect_sources="bad,good")).run()
    assert result["status"] == "error"
    assert result["sources"] == {"bad": "error", "good": 3}


def test_unknown_source_is_configuration_failure(tmp_path):
    result = collect.CollectStage(Settings(data_dir=tmp_path, collect_sources="unknown-test")).run()
    assert result["status"] == "error"
