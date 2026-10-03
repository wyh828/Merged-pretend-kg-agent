"""Offline causal workflow on synthetic multi-year fixtures, without API/LLM calls."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from techtrend.config import Settings
from techtrend.io import write_jsonl
from techtrend.stages.extract import ExtractStage
from techtrend.stages.align import AlignStage
from techtrend.stages.evaluate import EvaluateStage
from techtrend.stages.collaborate import CollaborateStage
from techtrend.stages.report import ReportStage
from techtrend.stages.visualize import VisualizeStage


def main() -> None:
    index = 0
    while True:
        directory = ROOT / "output" / "validation_01" / f"causal_workflow_{index:02d}"
        try:
            directory.mkdir(parents=True, exist_ok=False)
            break
        except FileExistsError:
            index += 1
    settings = Settings(_env_file=None, data_dir=directory / "fixture_data", output_dir=directory / "reports",
                        cache_dir=ROOT / "Data/Datasets/technology_trends_01/cache",
                        llm_api_key=None, eval_n_splits=1, eval_min_train=1,
                        eval_test_months=3, eval_step_months=3, eval_embargo_months=1,
                        eval_purge_months=1, tkg_embedding_dim=8, tkg_epochs=1, tkg_neg_samples=1,
                        rotate_embedding_dim=8, rotate_epochs=1, tkg_min_cooccur=1, tkg_max_entities=20,
                        forecast_horizon=3, forecast_lag=3, burst_future_months=3,
                        openalex_concept_ids="", weekly_enable=False, schedule_enable=False, notify_enable=False)
    works = []
    for month in range(60):
        date = f"{2020 + month // 12:04d}-{month % 12 + 1:02d}-01"
        for j in range(2 + month % 5):
            concepts = [{"id": "https://openalex.org/C101", "name": "Synthetic A", "score": 1.0},
                        {"id": "https://openalex.org/C102", "name": "Synthetic B", "score": 1.0}]
            if month % 3:
                concepts.append({"id": "https://openalex.org/C103", "name": "Synthetic C", "score": 1.0})
            works.append({"id": f"https://openalex.org/W{month:03d}{j}", "source": "synthetic_fixture",
                          "title": "Synthetic validation, not research evidence", "publication_date": date,
                          "concepts": concepts, "referenced_works": [], "authorships": []})
    write_jsonl(settings.data_dir / "interim" / "works.jsonl", works)
    results = []
    for cls in (ExtractStage, AlignStage, EvaluateStage, CollaborateStage, ReportStage, VisualizeStage):
        result = cls(settings).run()
        results.append(result)
        assert result["status"] == "ok", result
    metrics = json.loads((settings.output_dir / "eval_metrics.json").read_text(encoding="utf-8"))
    assert metrics["task_folds"]["links"] == 1
    assert metrics["task_folds"]["activity"] == 1 and metrics["task_folds"]["ranking"] == 1
    assert metrics["preprocessing_audit"][0]["fit_on"] == "train_only"
    assert (settings.output_dir / "dashboard.html").is_file()
    summary = {"checked_at": datetime.now(timezone.utc).isoformat(), "data_kind": "synthetic_validation",
               "history_months": 60, "records": len(works), "protocol_version": "causal_01",
               "stages": [{"stage": r["stage"], "status": r["status"]} for r in results],
               "task_folds": metrics["task_folds"], "dashboard": str(settings.output_dir / "dashboard.html"),
               "limitations": ["synthetic_only; not_prediction_accuracy_evidence", "no_live_research_source_calls",
                               "source_historical_availability_unverified", "patent_data_not_in_fixture"]}
    (directory / "verification_summary_01.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
