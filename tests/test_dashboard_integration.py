from techtrend.config import Settings
from techtrend.stages.visualize import VisualizeStage
from techtrend.viz.dashboard import render


def test_reports_are_embedded_safely():
    html = render(reports=[{"title": "report", "body": "<script>bad()</script>"}])
    assert "&lt;script&gt;bad()&lt;/script&gt;" in html
    assert '<script>bad()</script>' not in html


def test_missing_current_patent_data_cannot_display_old_curves(tmp_path):
    import json
    import pandas as pd
    out = tmp_path / "out"
    out.mkdir()
    pd.DataFrame([{"patent": "old", "stage": "growth"}]).to_csv(out / "s_curve_stages.csv", index=False)
    pd.DataFrame([[1, 2]], index=["growth"], columns=["2000-01", "2000-02"]).to_csv(out / "s_curve_curves.csv")
    (out / "citation_metrics.json").write_text(json.dumps({"status": "skipped", "n_patents": 0}))
    result = VisualizeStage(Settings(_env_file=None, data_dir=tmp_path / "data", output_dir=out)).run()
    assert result["status"] == "ok" and result["n_charts"] == 0


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
    assert "尚未生成此报告。" not in next(
        report["body"] for report in VisualizeStage._read_reports(out, out / "weekly_report.md")
        if report["title"] == "COMPARISON_REPORT.md"
    )
    assert "Resources/reports/COMPARISON_REPORT.md" in html
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
