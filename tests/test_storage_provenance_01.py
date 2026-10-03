import json

from techtrend.stages.collect import _write_raw
from techtrend.storage import file_digest, snapshot_outputs


def test_metadata_records_observation_but_does_not_invent_historical_availability(tmp_path):
    path = _write_raw(tmp_path / "dataset_01" / "raw", "test", "2026-10-03", "part", [{"id": "a"}],
                      source_url="https://example.test/source", query={"from_date": "2015-01-01"})
    metadata = json.loads(path.with_suffix(".metadata.json").read_text())
    assert metadata["sha256"] == file_digest(path) and metadata["rows"] == 1
    assert metadata["dataset_version"] == "dataset_01"
    assert metadata["historical_available_at"] is None and metadata["coverage"] == "unverified"
    assert metadata["query"] == {"from_date": "2015-01-01"}
    assert metadata["original_payload_preserved"] is False


def test_prior_results_survive_multiple_reruns(tmp_path):
    path = tmp_path / "eval_metrics.json"
    path.write_text('{"result": 1}')
    first = snapshot_outputs(tmp_path, "evaluate")
    path.write_text('{"result": 2}')
    second = snapshot_outputs(tmp_path, "evaluate")
    assert json.loads((first / path.name).read_text())["result"] == 1
    assert json.loads((second / path.name).read_text())["result"] == 2
    assert first != second
