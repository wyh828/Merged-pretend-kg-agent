"""DataCollectionAgent orchestrates multi-source collection and persistence.

Config-driven: iterates sources enabled in ``sources.yaml`` and dispatches to
the registered :class:`~data_collectors.base.SourceCollector`. Per-source
failures are captured in the report without aborting the whole run. Collected
records are persisted to interim JSONL, one file per source.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from techtrend.signal.config import PipelineConfig, ensure_dirs
from techtrend.signal.processors.normalize import save_records_to_jsonl
from techtrend.signal.agents.base_agent import BaseAgent, AgentResult

# Importing the collector modules registers them with the registry.
import techtrend.signal.data_collectors.crossref  # noqa: F401
import techtrend.signal.data_collectors.arxiv     # noqa: F401
import techtrend.signal.data_collectors.uspto     # noqa: F401
import techtrend.signal.data_collectors.gdelt      # noqa: F401
import techtrend.signal.data_collectors.github     # noqa: F401
from techtrend.signal.data_collectors.base import get_collector_class as get_collector, _COLLECTORS as registered_sources


@dataclass
class AgentOptions:
    sources_cfg_path: Path


class DataCollectionAgent(BaseAgent):
    def __init__(self, cfg: PipelineConfig, opts: AgentOptions) -> None:
        self.cfg = cfg
        self.opts = opts

    def _load_sources_cfg(self) -> dict[str, Any]:
        with open(self.opts.sources_cfg_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def run(self) -> AgentResult:
        ensure_dirs(self.cfg)
        raw_cfg = self._load_sources_cfg()
        http_settings = raw_cfg.get("http", {})
        sources_cfg = raw_cfg.get("sources", {})

        report = {
            "dataset": self.cfg.dataset_name,
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "registered_sources": list(registered_sources.keys()),
            "by_topic": [],
            "by_source": {},
        }

        # Accumulate records by source for batch persistence
        records_by_source: dict[str, list[dict[str, Any]]] = {}

        for source_name, source_cfg in sources_cfg.items():
            if not source_cfg.get("enabled", False):
                report["by_source"][source_name] = {"enabled": False}
                continue
            print(f"  -> Collecting source: {source_name}...")
            try:
                collector_cls = get_collector(source_name)
                collector = collector_cls()
            except ValueError as exc:
                print(f"     error: {exc}")
                report["by_source"][source_name] = {"enabled": True, "error": str(exc)}
                continue

            try:
                recs = asyncio.run(collector.collect(self.cfg, http_settings, source_cfg))
            except Exception as exc:  # noqa: BLE001 - one source failing must not abort others
                print(f"     exception: {exc}")
                report["by_source"][source_name] = {
                    "enabled": True,
                    "error": str(exc),
                    "records": 0,
                    "failed": 0,
                }
                continue

            records_by_source[source_name] = recs
            ok_count = sum(1 for r in recs if r.get("collection_status") == "ok")
            failed_count = sum(1 for r in recs if r.get("collection_status") != "ok")
            print(f"     done: {len(recs)} records (ok: {ok_count}, failed: {failed_count})")
            report["by_source"][source_name] = {
                "enabled": True,
                "records": len(recs),
                "ok": ok_count,
                "failed": failed_count,
            }

        # Build per-topic summary from all collected records
        topic_summary: dict[str, dict[str, Any]] = {}
        for source_name, recs in records_by_source.items():
            for rec in recs:
                tid = rec.get("topic_id", "unknown")
                if tid not in topic_summary:
                    topic_summary[tid] = {
                        "topic_id": tid,
                        "topic_label": rec.get("topic_label", tid),
                        "sources": {},
                    }
                src_entry = topic_summary[tid]["sources"].setdefault(source_name, {"ok": 0, "failed": 0})
                if rec.get("collection_status") == "ok":
                    src_entry["ok"] += 1
                else:
                    src_entry["failed"] += 1
                    src_entry.setdefault("errors", []).append(rec.get("error", "unknown"))
        report["by_topic"] = list(topic_summary.values())

        # Persist collected records to interim, one file per source
        for source_name, recs in records_by_source.items():
            if recs:
                out_path = self.cfg.interim_path / f"{source_name}_records.jsonl"
                save_records_to_jsonl(recs, out_path)

        report["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        out = self.cfg.reports_path / "collection_report.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        from techtrend.signal.processors.json_utils import NumpyEncoder
        with open(out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, cls=NumpyEncoder)

        return AgentResult(ok=True, detail={"report_path": str(out)})
