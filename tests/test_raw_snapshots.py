from techtrend.io import read_jsonl
from techtrend.stages.collect import _write_raw


def test_repeated_collection_preserves_both_raw_snapshots(tmp_path):
    _write_raw(tmp_path, "test", "2026-10-03", "batch", [{"id": "first"}])
    _write_raw(tmp_path, "test", "2026-10-03", "batch", [{"id": "second"}])
    directory = tmp_path / "test" / "2026-10-03"
    assert read_jsonl(directory / "test_batch_00.jsonl") == [{"id": "first"}]
    assert read_jsonl(directory / "test_batch_01.jsonl") == [{"id": "second"}]
