from techtrend.config import Settings
from techtrend.stages.visualize import VisualizeStage
from techtrend.viz.dashboard import render


def test_reports_are_embedded_safely():
    html = render(reports=[{"title": "report", "body": "<script>bad()</script>"}])
    assert "&lt;script&gt;bad()&lt;/script&gt;" in html
    assert '<script>bad()</script>' not in html


def test_missing_metrics_never_produce_model_verdict():
    heroes = VisualizeStage._build_heroes({}, {})
    assert "未验证" in heroes[1]["sub"]
    assert "未优于" not in heroes[1]["sub"]


def test_empty_checkout_dashboard_integrates_plans_and_report(tmp_path):
    out = tmp_path / "output"
    out.mkdir()
    (out / "report.md").write_text("test analysis body", encoding="utf-8")
    settings = Settings(data_dir=tmp_path / "data", output_dir=out)
    result = VisualizeStage(settings).run()
    assert result["status"] == "ok"
    html = (out / "dashboard.html").read_text(encoding="utf-8")
    assert "test analysis body" in html
    for name in ("COMPARISON_REPORT.md", "MERGE_PLAN.md", "REPORT_OUTLINE.md"):
        assert name in html
    assert "本地回测尚未完成" in html


def test_populated_dashboard_uses_saved_results_and_english_chart_names(tmp_path):
    import json
    import pandas as pd
    out = tmp_path / "output"
    out.mkdir()
    pd.DataFrame([{"entity": "C1", "name": "example", "score": .8}]).to_csv(out / "fusion_ranking.csv", index=False)
    (out / "eval_metrics.json").write_text(json.dumps({"tkg_mrr_mean": .4, "rotate_mrr_mean": .3}), encoding="utf-8")
    (out / "collab_consensus.json").write_text(json.dumps([{"concept": "C1", "verdict": "agree", "consensus": .8}]), encoding="utf-8")
    settings = Settings(data_dir=tmp_path / "data", output_dir=out)
    result = VisualizeStage(settings).run()
    assert result["status"] == "ok" and result["n_charts"] == 1
    html = (out / "dashboard.html").read_text(encoding="utf-8")
    assert "example" in html and "协同共识" in html
    assert list((out / "charts").glob("*.svg"))[0].name == "chart_00.svg"
