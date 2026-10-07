from argparse import Namespace
from types import SimpleNamespace

import main
from techtrend.config import Settings


def test_single_stage_failure_has_nonzero_exit(monkeypatch, tmp_path):
    stage = SimpleNamespace(name="evaluate", run=lambda: {"status": "error"})
    monkeypatch.setattr(main, "get_default_stages", lambda _: [stage])
    assert main.run_full(Namespace(list=False, stage="evaluate"), Settings(_env_file=None, output_dir=tmp_path)) == 1


def test_full_failure_has_nonzero_exit(monkeypatch):
    monkeypatch.setattr(main, "get_default_stages", lambda _: [])
    monkeypatch.setattr(main, "Pipeline", lambda _: SimpleNamespace(run=lambda: [{"status": "ok"}, {"status": "error"}]))
    assert main.run_full(Namespace(list=False, stage=None), None) == 1
