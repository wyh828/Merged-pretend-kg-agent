"""DataAnalysisAgent merges multi-source data and performs quality checks.

Pipeline:
1. Load collected records from interim (OpenAlex, CrossRef, GDELT, GitHub)
2. Clean raw records (filter failed, filter None activity_count)
3. Merge by source and create pivot table
4. Detect anomalies (z-score, IQR, consecutive zeros, sudden drops)
5. Fill missing windows (configurable strategy)
6. Standardize cross-source (robust scaling / rank normalization)
7. Smooth signal (optional moving median)
8. Extend pivot with GitHub repo-level signals
9. Save extended pivot and quality report

Outputs:
- pivot_table_extended.jsonl: cleaned + standardized + smoothed pivot
- quality_report.json: coverage, anomalies, issues
- cleaning_log.json: record of cleaning steps applied
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
import pandas as pd

from techtrend.signal.config import PipelineConfig, generate_monthly_windows
from techtrend.signal.processors.normalize import (
    load_jsonl,
    merge_records_by_source,
    create_pivot_table,
    save_records_to_jsonl,
    standardize_pivot,
)
from techtrend.signal.processors.cleaner import (
    clean_records,
    filter_anomalous_pivot_rows,
    fill_missing_windows,
    smooth_signal,
    save_cleaning_log,
)
from techtrend.signal.processors.detector import tag_anomalies_in_pivot, summarize_anomalies
from techtrend.signal.processors.quality_checker import check_data_quality, save_quality_report
from techtrend.signal.agents.base_agent import BaseAgent, AgentResult


class DataAnalysisAgent(BaseAgent):
    def __init__(self, cfg: PipelineConfig) -> None:
        self.cfg = cfg

    def _load_github_signals(self) -> list[dict[str, Any]]:
        """Load latest github_signals_YYYY-MM-DD.jsonl snapshot as a list.

        Signals are topic-specific; a repo may appear under multiple topics,
        so we keep all records rather than deduplicating by repo_id.
        """
        interim = self.cfg.interim_path
        if not interim.exists():
            return []

        # Find latest github_signals file
        candidates = sorted(interim.glob("github_signals_*.jsonl"), reverse=True)
        if not candidates:
            return []

        signals: list[dict[str, Any]] = []
        with open(candidates[0], "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rec = json.loads(line)
                    signals.append(rec)
        return signals

    def _extend_pivot_with_github(
        self,
        pivot: list[dict[str, Any]],
        gh_signals: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Add github_* columns to pivot table.

        GitHub signals are daily snapshots with topic_id; we aggregate them by
        (topic_id, month) to match pivot windows.
        """
        # Group signals by (topic_id, month)
        gh_by_topic_month: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for sig in gh_signals:
            tid = sig.get("topic_id", "unknown")
            date_str = sig.get("created_at", "")
            if date_str:
                month = date_str[:7]  # YYYY-MM
            else:
                month = "unknown"
            gh_by_topic_month.setdefault((tid, month), []).append(sig)

        # Extend pivot
        for row in pivot:
            tid = row.get("topic_id", "")
            month = row.get("window_start", "")
            sigs = gh_by_topic_month.get((tid, month), [])
            if sigs:
                row["github_stars_total"] = sum(s.get("stars_total", 0) for s in sigs)
                row["github_stars_per_day"] = sum(s.get("stars_per_day_lifetime", 0) for s in sigs)
                row["github_forks_total"] = sum(s.get("forks_total", 0) for s in sigs)
                row["github_activity_recent"] = sum(s.get("activity_recent", 0) for s in sigs)
            else:
                row["github_stars_total"] = 0
                row["github_stars_per_day"] = 0
                row["github_forks_total"] = 0
                row["github_activity_recent"] = 0

        return pivot

    def run(self) -> AgentResult:
        try:
            # Step 1: Load collected records
            openalex_path = self.cfg.interim_path / "openalex_records.jsonl"
            crossref_path = self.cfg.interim_path / "crossref_records.jsonl"
            arxiv_path = self.cfg.interim_path / "arxiv_records.jsonl"
            uspto_path = self.cfg.interim_path / "uspto_records.jsonl"
            gdelt_path = self.cfg.interim_path / "gdelt_records.jsonl"
            github_path = self.cfg.interim_path / "github_records.jsonl"

            openalex_recs = load_jsonl(openalex_path) if openalex_path.exists() else []
            crossref_recs = load_jsonl(crossref_path) if crossref_path.exists() else []
            arxiv_recs = load_jsonl(arxiv_path) if arxiv_path.exists() else []
            uspto_recs = load_jsonl(uspto_path) if uspto_path.exists() else []
            gdelt_recs = load_jsonl(gdelt_path) if gdelt_path.exists() else []
            github_recs = load_jsonl(github_path) if github_path.exists() else []

            all_raw = openalex_recs + crossref_recs + arxiv_recs + uspto_recs + gdelt_recs + github_recs

            # Step 2: Clean raw records (filter failed, filter None)
            clean_recs, cleaning_log = clean_records(all_raw)
            cleaning_log["sources"] = {
                "openalex": len(openalex_recs),
                "crossref": len(crossref_recs),
                "arxiv": len(arxiv_recs),
                "uspto": len(uspto_recs),
                "gdelt": len(gdelt_recs),
                "github": len(github_recs),
            }

            # Step 3: Merge and pivot (returns DataFrame)
            merged = merge_records_by_source(
                [r for r in clean_recs if r.get("source") == "openalex"],
                [r for r in clean_recs if r.get("source") == "gdelt"],
                [r for r in clean_recs if r.get("source") == "crossref"],
                [r for r in clean_recs if r.get("source") == "github"],
                [r for r in clean_recs if r.get("source") == "arxiv"],
                [r for r in clean_recs if r.get("source") == "uspto"],
            )
            pivot_df = create_pivot_table(merged)

            # Step 4: Detect anomalies (tag, don't remove yet) - expects list of dicts
            pivot_records = pivot_df.to_dict("records")
            pivot_records = tag_anomalies_in_pivot(pivot_records)
            anomaly_summary = summarize_anomalies(pivot_records)
            cleaning_log["anomalies_detected"] = anomaly_summary["total_anomalies"]

            # Step 5: Filter anomalous rows (expects DataFrame now)
            pivot_df = pd.DataFrame(pivot_records)
            pivot_df, drop_counts = filter_anomalous_pivot_rows(
                pivot_df,
                drop_likely_api_failure=True,
                drop_zscore=False,
                drop_iqr=False,
                drop_sudden_drop=False,
            )
            cleaning_log["rows_dropped"] = drop_counts

            # Step 6: Fill missing windows
            all_windows = [w[0] for w in generate_monthly_windows(self.cfg.start_date, self.cfg.end_date)]
            pivot_df, fill_counts = fill_missing_windows(
                pivot_df, all_windows, strategy="forward_fill",
            )
            cleaning_log["windows_filled"] = fill_counts

            # Step 7: Standardize cross-source (robust scaling)
            pivot_df = standardize_pivot(pivot_df, method="robust")

            # Step 8: Smooth signal (moving median, window=3)
            pivot_df = smooth_signal(pivot_df, window_size=3, method="median")
            
            pivot = pivot_df.to_dict("records")

            # Step 9: Extend with GitHub repo-level signals
            gh_signals = self._load_github_signals()
            pivot = self._extend_pivot_with_github(pivot, gh_signals)

            # Save extended pivot
            pivot_path = self.cfg.processed_path / "pivot_table_extended.jsonl"
            n = save_records_to_jsonl(pivot, pivot_path)

            # Save cleaning log
            cleaning_log["final_pivot_rows"] = n
            cleaning_log_path = self.cfg.reports_path / "cleaning_log.json"
            save_cleaning_log(cleaning_log, cleaning_log_path)

            # Quality check (enhanced with anomaly summary)
            quality = check_data_quality(pivot)
            quality_path = self.cfg.reports_path / "quality_report.json"
            save_quality_report(quality, quality_path)

            return AgentResult(
                ok=True,
                detail={
                    "pivot_records": n,
                    "pivot_path": str(pivot_path),
                    "quality_score": quality["overall_score"],
                    "quality_report_path": str(quality_path),
                    "cleaning_log_path": str(cleaning_log_path),
                    "anomalies_detected": anomaly_summary["total_anomalies"],
                    "rows_dropped": drop_counts["total_dropped"],
                    "windows_filled": fill_counts["filled"],
                },
            )
        except Exception as e:  # noqa: BLE001
            return AgentResult(ok=False, detail={"error": str(e)})
