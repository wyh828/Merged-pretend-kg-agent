from types import SimpleNamespace

from techtrend.config import Settings
from techtrend.stages import get_default_stages
from techtrend.orchestration import runbook


def test_default_and_daily_orders_match():
    assert tuple(s.name for s in get_default_stages(Settings())) == runbook.ALL_STAGES
    assert runbook.ALL_STAGES.index("report") > runbook.ALL_STAGES.index("collaborate")


def test_daily_collaboration_and_review_gate(monkeypatch, tmp_path):
    calls = []
    def execute(name):
        calls.append(name)
        return {"status": "ok", "sources": {"test": 1}}
    pool = [SimpleNamespace(name=n, run=lambda n=n: execute(n)) for n in runbook.ALL_STAGES]
    monkeypatch.setattr(runbook, "get_default_stages", lambda _: pool)
    monkeypatch.setattr(runbook, "_append_manifest", lambda *_: None)
    settings = Settings(output_dir=tmp_path)
    monkeypatch.setattr(runbook, "_review_checkpoint", lambda *_: True)
    assert runbook.run_daily(settings)["status"] == "ok"
    assert tuple(calls) == runbook.ALL_STAGES
    calls.clear()
    monkeypatch.setattr(runbook, "_review_checkpoint", lambda *_: False)
    assert runbook.run_daily(settings)["status"] == "error"
    assert "notify" not in calls and "report" not in calls
