"""Versioned local snapshots and provenance; never inspect credentials."""
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def reserve_snapshot_path(directory: Path, stem: str) -> Path:
    """Reserve a new numbered file exclusively; the caller fills this empty file."""
    directory.mkdir(parents=True, exist_ok=True)
    index = 0
    while True:
        path = directory / f"{stem}_{index:02d}.jsonl"
        try:
            path.open("x", encoding="utf-8").close()
            return path
        except FileExistsError:
            index += 1


def file_digest(path: Path) -> str:
    """SHA-256 without loading large datasets into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_snapshot_metadata(path: Path, *, source: str, row_count: int,
                            dataset_version: str, source_url: str | None = None,
                            query: dict | None = None) -> None:
    """Write an exclusive sidecar for a normalized snapshot, with observed time.

    Callers pass explicit non-secret query parameters. No historical public
    availability or license is inferred from the collection timestamp.
    """
    payload = {"schema_version": "normalized_snapshot_01", "source": source,
               "source_url": source_url, "query": query or {},
               "collected_at": datetime.now(timezone.utc).isoformat(),
               "dataset_version": dataset_version, "file": path.name,
               "rows": row_count, "sha256": file_digest(path),
               "historical_available_at": None, "license": None,
               "coverage": "unverified", "original_payload_preserved": False,
               "processing": ["source_client_normalization"],
               "limitations": ["not_a_point_in_time_historical_snapshot"]}
    with path.with_suffix(".metadata.json").open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)


def snapshot_outputs(output_dir: Path, reason: str) -> Path | None:
    """Preserve current reports before rerun; numbered archives are immutable.

    Copy root report files and the chart folder, excluding logs, manifests,
    caches, test directories and prior archives. Failure stops the caller.
    """
    output_dir = Path(output_dir)
    if not output_dir.exists():
        return None
    files = sorted(p for p in output_dir.iterdir() if p.is_file()
                   and p.suffix in {".json", ".csv", ".md", ".html", ".svg", ".pt"}
                   and not p.name.startswith("."))
    charts = output_dir / "charts"
    if not files and not charts.exists():
        return None
    index = 0
    while True:
        archive = output_dir / "history" / f"artifacts_{index:02d}"
        try:
            archive.mkdir(parents=True, exist_ok=False)
            break
        except FileExistsError:
            index += 1
    checksums = {}
    for path in files:
        shutil.copy2(path, archive / path.name)
        checksums[path.name] = file_digest(path)
    if charts.exists():
        shutil.copytree(charts, archive / "charts")
    with (archive / "snapshot_manifest.json").open("x", encoding="utf-8") as stream:
        json.dump({"reason": reason, "copied_at": datetime.now(timezone.utc).isoformat(),
                   "sha256": checksums}, stream, ensure_ascii=False, indent=2)
    return archive
