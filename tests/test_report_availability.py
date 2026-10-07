import json
from techtrend.config import Settings
from techtrend.stages.report import ReportStage, _render_four_goals


def test_evaluation_report_does_not_require_old_baseline(tmp_path):
    (tmp_path / "eval_metrics.json").write_text(json.dumps({"p_at_k_mean": .2}), encoding="utf-8")
    result = ReportStage(Settings(output_dir=tmp_path, llm_api_key=None)).run()
    assert result["status"] == "ok"
    body = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "0.2000" in body and "未验证" in body


def test_absent_report_inputs_are_explicit(tmp_path):
    assert ReportStage(Settings(output_dir=tmp_path)).run()["status"] == "skipped"
    assert "未优于" not in _render_four_goals({}, {})
