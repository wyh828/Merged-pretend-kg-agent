import json
import pytest
from techtrend.config import Settings
from techtrend.data_preparation import DataPreparation, months_between, parse_field_counts, validate_works
from techtrend.sources.openalex import OpenAlexClient
from techtrend.sources.crossref import CrossrefClient


def test_complete_months_and_leap_year_boundaries():
    assert len(months_between("2016-01-01", "2025-12-31")) == 120
    assert months_between("2020-02-01", "2020-02-29") == ["2020-02"]
    with pytest.raises(ValueError):
        months_between("2020-01-02", "2020-02-29")


def test_truncated_groups_and_error_payloads_are_not_zero():
    for payload in [{}, {"meta": {"count": 3}, "group_by": [{"key": "unknown", "count": 1}]}]:
        with pytest.raises(ValueError):
            parse_field_counts(payload)
    rows, total = parse_field_counts({"meta": {"count": 0}, "group_by": []})
    assert rows == [] and total == 0


def test_dates_are_quarantined_without_inventing_precision():
    records = [{"id": "a", "publication_date": "2016"},
               {"id": "b", "publication_date": "2016-02-30"},
               {"id": "c", "publication_date": "2026-01-01"},
               {"id": "d", "publication_date": "2016-06-01"}]
    accepted, rejected = validate_works(records, "2016-01-01", "2016-12-31", True)
    assert [r["id"] for r in accepted] == ["d"] and len(rejected) == 3


def test_preparation_preserves_raw_reconciles_and_resumes_without_network(tmp_path, monkeypatch):
    calls = []
    def openalex(self, params):
        calls.append("openalex")
        if "group_by" in params:
            return {"meta": {"count": 3}, "group_by": [
                {"key": "https://openalex.org/fields/1", "key_display_name": "Engineering", "count": 2},
                {"key": "https://openalex.org/fields/unknown", "key_display_name": "Unknown", "count": 1}]}
        return {"meta": {"count": 2}, "results": [{"id": "W1", "publication_date": "2016-01-01",
                "topics": [{"id": "T1", "display_name": "Engineering", "score": 1}], "referenced_works": ["W0"]}]}
    def crossref(self, params):
        calls.append("crossref")
        return {"message": {"total-results": 5, "items": [{"DOI": "10.1/test", "title": ["Test"],
                "published": {"date-parts": [[2016, 1, 2]]}}]}}
    monkeypatch.setattr(OpenAlexClient, "_get_page", openalex)
    monkeypatch.setattr(CrossrefClient, "_get_page", crossref)
    settings = Settings(_env_file=None, data_dir=tmp_path, collection_start_date="2016-01-01", collection_end_date="2016-01-31")
    result = DataPreparation(settings).run()
    assert result["works"] == 2 and result["openalex_months_ok"] == 1
    assert result["sampled_field_year_strata"] == 1
    assert result["historical_as_of_evaluation_ready"] is False
    assert len(calls) == 4
    repeat = DataPreparation(settings).run()
    assert repeat["requests_this_run"] == 0 and len(calls) == 4
    assert repeat["works"] == 2
    assert len(list((tmp_path / "metadata").glob("preparation_summary_*.json"))) == 2
    envelope = json.loads(next((tmp_path / "raw").rglob("registry*.jsonl")).read_text())
    assert envelope["payload"]["meta"]["count"] == 3


def test_failed_month_is_missing_not_zero(tmp_path, monkeypatch):
    def openalex(self, params):
        if params.get("filter", "").endswith("2016-01-31") and "group_by" in params:
            return {"meta": {"count": 3}, "group_by": [{"key": "https://openalex.org/fields/1", "count": 3}]}
        raise RuntimeError("temporary failure")
    monkeypatch.setattr(OpenAlexClient, "_get_page", openalex)
    monkeypatch.setattr(CrossrefClient, "_get_page", lambda *_: (_ for _ in ()).throw(RuntimeError("failure")))
    result = DataPreparation(Settings(_env_file=None, data_dir=tmp_path,
                                     collection_start_date="2016-01-01", collection_end_date="2016-01-31")).run()
    rows = [json.loads(line) for line in (tmp_path / result["monthly_activity_file"]).read_text().splitlines()]
    crossref = next(r for r in rows if r["source"] == "crossref")
    assert crossref["activity_count"] is None and crossref["collection_status"] == "failed"
    assert result["full_scale_forecasting_ready"] is False
