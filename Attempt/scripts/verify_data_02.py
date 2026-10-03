"""Validate saved API provenance and monthly coverage without network calls."""
import json
import sys
from collections import Counter
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from techtrend.config import Settings
from techtrend.data_preparation import parse_field_counts
from techtrend.io import read_jsonl
from techtrend.storage import file_digest, reserve_snapshot_path


def main() -> int:
    root = Settings().data_dir
    summary_path = sorted((root / "metadata").glob("preparation_summary_*.json"))[-1]
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    errors = []
    raw_paths = list((root / "raw").rglob("*.jsonl"))
    for path in raw_paths:
        metadata = json.loads(path.with_suffix(".metadata.json").read_text(encoding="utf-8"))
        if metadata["sha256"] != file_digest(path) or not metadata.get("original_payload_preserved"):
            errors.append(f"raw_integrity:{path.name}")
        envelope = read_jsonl(path)[0]
        if metadata["source"] == "openalex" and "group_by" in envelope["query"]:
            parse_field_counts(envelope["payload"])
    counts = read_jsonl(root / summary["monthly_activity_file"])
    for month in sorted({r["month"] for r in counts}):
        records = [r for r in counts if r["source"] == "openalex" and r["month"] == month]
        if any(r["collection_status"] != "ok" for r in records):
            errors.append(f"unavailable_month:{month}")
        elif sum(r["activity_count"] for r in records) != records[0]["corpus_total"]:
            errors.append(f"month_count_reconciliation:{month}")
    works = read_jsonl(root / "interim/works.jsonl")
    ids = [w["id"] for w in works]
    if len(ids) != len(set(ids)):
        errors.append("duplicate_work_ids")
    for work in works:
        raw = (root / work["raw_snapshot"]).resolve()
        if not raw.is_relative_to(root) or not raw.exists():
            errors.append(f"missing_raw_provenance:{work['id']}")
        if not summary["start_date"] <= work["publication_date"] <= summary["end_date"]:
            errors.append(f"invalid_work_date:{work['id']}")
    rejected = []
    for path in (root / "interim/quarantine").glob("*.jsonl"):
        rejected.extend(read_jsonl(path))
    report = {"schema_version": "data_validation_02", "verified_at": datetime.now(timezone.utc).isoformat(),
              "dataset_version": root.name, "summary_file": str(summary_path.relative_to(root)),
              "status": "passed" if not errors else "failed", "errors": errors,
              "raw_snapshots_checked": len(raw_paths), "coverage_rows": len(counts),
              "works_checked": len(works), "by_source": dict(Counter(w["source"] for w in works)),
              "quarantined": len(rejected), "rejection_reasons": dict(Counter(r["rejection_reason"] for r in rejected)),
              "historical_as_of_validated": False,
              "checks": ["raw_sha256", "original_response_preservation", "primary_field_count_reconciliation",
                         "unique_work_ids", "raw_provenance_paths", "publication_date_bounds"]}
    path = reserve_snapshot_path(root / "metadata", "data_validation", suffix=".json")
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
