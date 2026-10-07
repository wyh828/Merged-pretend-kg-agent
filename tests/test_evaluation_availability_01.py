from types import SimpleNamespace

from techtrend.config import Settings
from techtrend.io import write_jsonl
from techtrend.pipeline import Pipeline
from techtrend.stages.evaluate import EvaluateStage


def test_report_does_not_claim_complete_validation_when_data_unavailable():
    from techtrend.stages.evaluate import _render_report
    report = _render_report({"leak_ok": None, "protocol_version": "causal_01"})
    assert "四指标齐备" not in report and "无泄漏、可复现" not in report
    assert "历史字段可得性" in report and "未验证" in report


def test_no_citation_file_replaces_stale_success_with_unavailable(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    settings.output_dir.mkdir()
    result = EvaluateStage._run_citation_metrics(settings, None, {})
    assert result["status"] == "skipped" and result["n_folds"] == 0
    assert (settings.output_dir / "citation_metrics.json").exists()


def test_long_calendar_but_no_training_samples_cannot_claim_success(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    settings.output_dir.mkdir()
    write_jsonl(settings.patent_citations_file,
                [{"head": "p", "time": "2000-01-01"}, {"head": "p", "time": "2002-01-01"}])
    ev = SimpleNamespace(backtest_regression=lambda *args: {"n_folds": 0})
    result = EvaluateStage._run_citation_metrics(settings, ev, {})
    assert result["n_months"] == 25
    assert result["status"] == "skipped" and "purge" in result["reason"]


def test_pipeline_stops_after_failure(monkeypatch, tmp_path):
    called = []
    class FakeStage:
        def __init__(self, name, status): self.name, self.status = name, status
        def run(self):
            called.append(self.name)
            return {"stage": self.name, "status": self.status}
    monkeypatch.setattr("techtrend.pipeline.get_default_stages",
                        lambda settings: [FakeStage("extract", "error"), FakeStage("report", "ok")])
    result = Pipeline(Settings(_env_file=None, output_dir=tmp_path)).run()
    assert called == ["extract"] and len(result) == 1


def test_daily_failure_cannot_publish_previous_results(monkeypatch, tmp_path):
    from techtrend.orchestration import runbook
    called = []
    def execute(name):
        called.append(name)
        return {"status": "error" if name == "collect" else "ok", "sources": {"test": "error"}}
    pool = [SimpleNamespace(name=n, run=lambda n=n: execute(n)) for n in runbook.ALL_STAGES]
    monkeypatch.setattr(runbook, "get_default_stages", lambda _: pool)
    monkeypatch.setattr(runbook, "_append_manifest", lambda *_: None)
    result = runbook.run_daily(Settings(_env_file=None, output_dir=tmp_path))
    assert called == ["collect"] and result["status"] == "error"
    assert result["stages"]["report"] == "skipped"
