import pytest

from techtrend.config import Settings
from techtrend.io import read_jsonl
from techtrend.stages.collect import _collect_patent_citations


def test_legacy_future_top_n_rejected_before_any_network(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, patent_citation_source="patentsview",
                        patent_citation_max_patents=1)
    with pytest.raises(ValueError, match="top-N"):
        _collect_patent_citations(settings, tmp_path / "interim", tmp_path / "raw")


def test_missing_export_is_failure_not_zero_success(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, patent_citation_source="bigquery")
    with pytest.raises(FileNotFoundError):
        _collect_patent_citations(settings, tmp_path / "interim", tmp_path / "raw")


def test_streaming_bulk_preserves_prior_snapshot_and_all_patents(monkeypatch, tmp_path):
    import techtrend.sources.patentsview as pv
    class LocalBulk:
        def __init__(self, *args): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def download(self, filename): return tmp_path / filename
    monkeypatch.setattr(pv, "PatentsViewBulkClient", LocalBulk)
    monkeypatch.setattr(pv, "parse_patent_dates", lambda *args: {})
    records = [{"citing": "x", "cited": "old", "citing_date": "2000-01-01"},
               {"citing": "y", "cited": "new", "citing_date": "2024-01-01"}]
    monkeypatch.setattr(pv, "iter_citation_tsv", lambda *args: iter(records))
    settings = Settings(_env_file=None, data_dir=tmp_path, patent_citation_source="patentsview")
    for _ in range(2):
        assert _collect_patent_citations(settings, tmp_path / "interim", tmp_path / "raw") == 2
    snapshots = list((tmp_path / "raw" / "patent_citations").rglob("*.jsonl"))
    assert len(snapshots) == 2
    assert {f["head"] for f in read_jsonl(snapshots[0])} == {"old", "new"}
