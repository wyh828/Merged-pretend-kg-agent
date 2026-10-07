import json
from techtrend.config import Settings
from techtrend.stages import collect
from techtrend.sources.openalex import OpenAlexClient


def test_capped_stage_resumes_without_advancing_date_or_losing_raw(monkeypatch, tmp_path):
    requests = []
    def get_page(self, params):
        requests.append(params)
        first = params["cursor"] == "*"
        return {"meta": {"count": 3, "next_cursor": "remaining" if first else None},
                "results": [{"id": "W1" if first else "W2", "publication_date": "2016-01-01"}]}
    monkeypatch.setattr(OpenAlexClient, "_get_page", get_page)
    settings = Settings(_env_file=None, data_dir=tmp_path, collect_sources="openalex",
                        openalex_max_works=1, openalex_concept_ids="",
                        collection_start_date="2016-01-01", collection_end_date="2025-12-31")
    assert collect.CollectStage(settings).run()["status"] == "ok"
    assert not (tmp_path / ".openalex_cursor").exists()
    assert collect.CollectStage(settings).run()["status"] == "ok"
    assert requests[1]["cursor"] == "remaining"
    assert (tmp_path / ".openalex_cursor").read_text() == "2025-12-31"
    pages = list((tmp_path / "raw/openalex").rglob("*.jsonl"))
    assert len(pages) == 2
    assert json.loads(pages[0].read_text())["payload"]["meta"]["count"] == 3


def test_in_batch_duplicate_ids_are_not_appended(tmp_path):
    path = tmp_path / "interim/works.jsonl"
    assert collect._append_dedup(path, [{"id": "W1"}, {"id": "W1"}]) == 1


def test_large_batch_id_index_avoids_rereading_and_updates_after_append(tmp_path, monkeypatch):
    monkeypatch.setattr(collect, "read_jsonl", lambda *_: (_ for _ in ()).throw(AssertionError("index reread")))
    known = {"W0"}
    assert collect._append_dedup(tmp_path / "works.jsonl", [{"id": "W0"}, {"id": "W1"}], known) == 1
    assert known == {"W0", "W1"}
