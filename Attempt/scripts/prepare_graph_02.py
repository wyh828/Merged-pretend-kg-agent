"""Preserve each graph preparation state; optionally load the configured Neo4j."""
import argparse
import json
import shutil
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from techtrend.config import Settings
from techtrend.io import read_jsonl
from techtrend.stages.extract import ExtractStage
from techtrend.stages.align import AlignStage
from techtrend.stages.build_graph import BuildGraphStage
from techtrend.storage import file_digest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--load-database", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    if settings.llm_api_key:
        raise ValueError("This preparation script requires structural extraction without LLM calls")
    root = settings.data_dir
    summary_path = sorted((root / "metadata").glob("preparation_summary_*.json"))[-1]
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if not summary.get("graph_seed_ready"):
        raise ValueError("Complete seed coverage is required before graph preparation")
    index = 0
    while (archive := root / "processed" / f"graph_preparation_{index:02d}").exists():
        index += 1
    archive.mkdir(parents=True, exist_ok=False)
    for name in ("nodes.jsonl", "triples.jsonl", "alignment.jsonl"):
        path = root / "interim" / name
        if path.exists():
            shutil.copy2(path, archive / f"previous_{name}")
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "dataset_version": root.name,
                "input_works_sha256": file_digest(root / "interim/works.jsonl"), "stages": []}
    stages = [ExtractStage(settings), AlignStage(settings)]
    if args.load_database:
        stages.append(BuildGraphStage(settings))
    for stage in stages:
        before = len(read_jsonl(root / "interim/triples.jsonl")) if stage.name == "align" else None
        result = stage.run()
        if stage.name == "align" and len(read_jsonl(root / "interim/triples.jsonl")) != before:
            result.update(status="error", reason="alignment_dropped_triples")
        manifest["stages"].append(result)
        (archive / "manifest_00.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if result["status"] != "ok":
            return 1
        for name in ("nodes.jsonl", "triples.jsonl", "alignment.jsonl"):
            path = root / "interim" / name
            if path.exists() and stage.name != "build_graph":
                shutil.copy2(path, archive / f"{stage.name}_{name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
