import json
from techtrend.config import Settings
from techtrend.io import write_jsonl
from techtrend.stages.visualize import VisualizeStage
from techtrend.storage import file_digest


def test_dashboard_uses_corpus_counts_and_labels_samples(tmp_path):
    data = tmp_path / "data"
    counts = data / "processed/monthly_activity_00.jsonl"
    write_jsonl(counts, [{"source": "openalex", "field_id": "field1", "field_name": "Engineering", "month": month,
                          "activity_count": count, "collection_status": "ok"}
                         for month, count in [("2016-01", 1000), ("2016-02", 1100)]])
    summary = {"dataset_version": "data", "fields": 26, "expected_months": 120, "openalex_months_ok": 120,
               "crossref_months_ok": 120, "works": 20, "sampled_field_year_strata": 260,
               "expected_field_year_strata": 260, "start_date": "2016-01-01", "end_date": "2025-12-31",
               "monthly_activity_file": "processed/monthly_activity_00.jsonl",
               "derived_sha256": {counts.name: file_digest(counts)}}
    (data / "metadata").mkdir()
    (data / "metadata/preparation_summary_00.json").write_text(json.dumps(summary), encoding="utf-8")
    write_jsonl(data / "interim/works.jsonl", [{"id": "W1", "sample_kind": "seeded_random_field_year",
                                               "publication_date": "2016-01-01", "concepts": [{"id": "T1", "name": "Test", "score": 1}]}])
    result = VisualizeStage(Settings(_env_file=None, data_dir=data, output_dir=tmp_path / "out", weekly_enable=False)).run()
    assert result["status"] == "ok"
    html = (tmp_path / "out/dashboard.html").read_text(encoding="utf-8")
    assert "学科月度文献量（API 汇总）" in html
    assert "样本数量不能代表学科热度" in html
    assert "120 / 120" in html and "Engineering" in html
    assert "概念 S 曲线阶段分布" not in html
