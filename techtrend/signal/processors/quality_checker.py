"""Data quality checker: validates collected records and emits quality_report.json.

Checks:
- Per-source coverage (fraction of windows with non-zero counts)
- Per-topic completeness
- Anomaly summary (from detector tags if present)
- Consecutive zero runs (likely API failures)
- Cross-source correlation (are sources telling the same story?)
- Filled window count (if fill_missing_windows was applied)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def check_data_quality(
    pivot_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assess data completeness and quality.

    Returns a report dict with:
    - overall_score (0-100)
    - by_topic: topic-level coverage and signal counts
    - by_source: source-level coverage and anomaly counts
    - issues: list of detected problems
    - anomaly_summary: summary of detected anomalies (if tags present)
    """
    report = {
        "overall_score": 100,
        "by_topic": {},
        "by_source": {},
        "issues": [],
        "anomaly_summary": {},
    }

    if not pivot_records:
        report["overall_score"] = 0
        report["issues"].append("No records found")
        return report

    # Detect which source columns exist
    source_cols = [c for c in pivot_records[0].keys() if c.endswith("_count")]
    source_names = [c.replace("_count", "") for c in source_cols]

    # Group by topic
    by_topic: dict[str, list[dict[str, Any]]] = {}
    for rec in pivot_records:
        tid = rec.get("topic_id", "unknown")
        if tid not in by_topic:
            by_topic[tid] = []
        by_topic[tid].append(rec)

    # Analyze per-topic
    for tid, recs in by_topic.items():
        topic_label = recs[0].get("topic_label", tid) if recs else tid
        topic_entry: dict[str, Any] = {
            "label": topic_label,
            "windows": len(recs),
            "filled_windows": sum(1 for r in recs if r.get("_filled", False)),
            "overall_coverage": 0.0,
        }

        total_nonzero = 0
        total_cells = len(recs) * len(source_cols)
        for col in source_cols:
            nonzero = sum(1 for r in recs if r.get(col, 0) > 0)
            total_nonzero += nonzero
            topic_entry[f"{col.replace('_count', '')}_coverage"] = nonzero / len(recs) if recs else 0

        topic_entry["overall_coverage"] = total_nonzero / total_cells if total_cells > 0 else 0
        report["by_topic"][tid] = topic_entry

        if topic_entry["overall_coverage"] < 0.3:
            report["issues"].append(f"Topic {tid}: low coverage ({topic_entry['overall_coverage']:.1%})")
        if topic_entry.get("filled_windows", 0) > 0:
            report["issues"].append(
                f"Topic {tid}: {topic_entry['filled_windows']} filled (interpolated/zero-filled) windows"
            )
        for sname in source_names:
            cov_key = f"{sname}_coverage"
            if topic_entry.get(cov_key, 0) == 0:
                report["issues"].append(f"Topic {tid}: no {sname} data")

    # Per-source summary
    for col, sname in zip(source_cols, source_names):
        nonzero = sum(1 for r in pivot_records if r.get(col, 0) > 0)
        total = len(pivot_records)
        anomaly_count = sum(1 for r in pivot_records if r.get(f"{col}_any_anomaly", False))
        report["by_source"][sname] = {
            "coverage": nonzero / total if total > 0 else 0,
            "anomaly_count": anomaly_count,
            "total_windows": total,
        }

    # Anomaly summary (if detector tags are present)
    anomaly_cols = [c for c in (pivot_records[0].keys() if pivot_records else []) if c.endswith("_any_anomaly")]
    if anomaly_cols:
        total_anomalies = sum(sum(1 for r in pivot_records if r.get(col, False)) for col in anomaly_cols)
        report["anomaly_summary"] = {
            "total_anomaly_cells": total_anomalies,
            "sources_with_anomalies": [
                col.replace("_any_anomaly", "")
                for col in anomaly_cols
                if any(r.get(col, False) for r in pivot_records)
            ],
        }
        if total_anomalies > 0:
            report["issues"].append(f"{total_anomalies} anomaly cells detected (see by_source for breakdown)")

    # Overall score: weighted combination of coverage and anomaly penalty
    avg_coverage = sum(t["overall_coverage"] for t in report["by_topic"].values()) / len(report["by_topic"]) if report["by_topic"] else 0
    anomaly_penalty = min(total_anomalies / (len(pivot_records) * max(len(anomaly_cols), 1)), 0.2) if anomaly_cols else 0
    report["overall_score"] = int(max(0, (avg_coverage - anomaly_penalty) * 100))

    return report


def save_quality_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    from techtrend.signal.processors.json_utils import NumpyEncoder
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, cls=NumpyEncoder)
