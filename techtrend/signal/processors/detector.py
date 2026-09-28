"""Anomaly detection for activity count time series.

Detects suspiciously high, suspiciously low, and consecutive-zero patterns in
per-source activity counts. Anomalies are *tagged* on the records, not removed;
downstream code decides whether to filter based on the tags and configuration.

Detection methods:
- Z-score outlier: |z| > threshold (default 3.0) on log-transformed counts
- IQR outlier: value < Q1 - k*IQR or value > Q3 + k*IQR (default k=1.5)
- Consecutive zeros: N or more consecutive zero-count windows (default 3),
  flagged as "likely_api_failure" rather than genuine zero activity
- Sudden drop: value drops to 0 after a sustained non-zero run
"""

from __future__ import annotations

import math
from typing import Any


def _log1p_safe(value: float) -> float:
    """Log1p that treats negatives as zero."""
    return math.log1p(max(value, 0.0))


def detect_zscore_outliers(
    values: list[float],
    threshold: float = 3.0,
    window: int = 6,
) -> list[bool]:
    """Flag values whose rolling z-score (on log1p transform) exceeds threshold.

    Args:
        values: List of numeric activity counts.
        threshold: Absolute z-score threshold (default 3.0).
        window: Number of past periods to compute rolling statistics.

    Returns:
        List of booleans, True where the value is an outlier.
    """
    n = len(values)
    log_vals = [_log1p_safe(v) for v in values]
    outliers = [False] * n

    for i in range(n):
        start = max(0, i - window)
        past = log_vals[start:i]
        
        if len(past) < 2:
            outliers[i] = False
            continue
            
        mean = sum(past) / len(past)
        variance = sum((v - mean) ** 2 for v in past) / len(past)
        std = math.sqrt(variance)
        if std < 1e-9:
            outliers[i] = False
        else:
            outliers[i] = abs((log_vals[i] - mean) / std) > threshold

    return outliers


def detect_iqr_outliers(
    values: list[float],
    k: float = 1.5,
    window: int = 6,
) -> list[bool]:
    """Flag values outside Q1 - k*IQR and Q3 + k*IQR based on a rolling window.

    Args:
        values: List of numeric activity counts.
        k: IQR multiplier (default 1.5).
        window: Number of past periods to compute rolling statistics.

    Returns:
        List of booleans, True where the value is an outlier.
    """
    n = len(values)
    outliers = [False] * n

    for i in range(n):
        start = max(0, i - window)
        past = values[start:i]
        
        m = len(past)
        if m < 4:
            outliers[i] = False
            continue
            
        sorted_vals = sorted(past)
        q1 = sorted_vals[m // 4]
        q3 = sorted_vals[3 * m // 4]
        iqr = q3 - q1
        if iqr < 1e-9:
            outliers[i] = False
        else:
            lower = q1 - k * iqr
            upper = q3 + k * iqr
            outliers[i] = values[i] < lower or values[i] > upper

    return outliers


def detect_consecutive_zeros(
    values: list[float],
    min_consecutive: int = 3,
) -> list[str]:
    """Flag runs of consecutive zeros as likely API failures.

    Args:
        values: List of numeric activity counts.
        min_consecutive: Minimum consecutive zeros to flag (default 3).

    Returns:
        List of tags: "likely_api_failure" for zeros in a long run, "" otherwise.
    """
    n = len(values)
    tags: list[str] = [""] * n
    i = 0
    while i < n:
        if values[i] == 0:
            run_start = i
            while i < n and values[i] == 0:
                i += 1
            run_len = i - run_start
            if run_len >= min_consecutive:
                for j in range(run_start, i):
                    tags[j] = "likely_api_failure"
        else:
            i += 1
    return tags


def detect_sudden_drop(
    values: list[float],
    min_nonzero_before: int = 3,
) -> list[str]:
    """Flag a sudden drop to zero after a sustained non-zero run.

    Args:
        values: List of numeric activity counts.
        min_nonzero_before: Minimum consecutive non-zero values before the drop.

    Returns:
        List of tags: "sudden_drop" at the drop point, "" otherwise.
    """
    n = len(values)
    tags: list[str] = [""] * n
    nonzero_run = 0
    for i in range(n):
        if values[i] > 0:
            nonzero_run += 1
        else:
            if nonzero_run >= min_nonzero_before:
                tags[i] = "sudden_drop"
            nonzero_run = 0
    return tags


def tag_anomalies_in_pivot(
    pivot: list[dict[str, Any]],
    source_columns: list[str] | None = None,
    zscore_threshold: float = 3.0,
    iqr_k: float = 1.5,
    min_consecutive_zeros: int = 3,
    min_nonzero_before_drop: int = 3,
) -> list[dict[str, Any]]:
    """Tag anomaly flags on each pivot row for each source column.

    Adds the following keys to each row:
    - ``{col}_zscore_outlier``: bool
    - ``{col}_iqr_outlier``: bool
    - ``{col}_zero_tag``: str ("likely_api_failure", "sudden_drop", or "")
    - ``{col}_any_anomaly``: bool (True if any of the above)

    Args:
        pivot: List of pivot table dicts (sorted by topic_id, window_start).
        source_columns: Column names to check (default: all *_count columns).
        zscore_threshold: Z-score threshold for outlier detection.
        iqr_k: IQR multiplier for outlier detection.
        min_consecutive_zeros: Min consecutive zeros to flag as API failure.
        min_nonzero_before_drop: Min non-zero run before a sudden drop.

    Returns:
        The same pivot list with anomaly tags added in-place.
    """
    if source_columns is None:
        source_columns = [
            c for c in (pivot[0].keys() if pivot else [])
            if c.endswith("_count")
        ]

    # Group rows by topic_id to detect anomalies within each topic's series
    by_topic: dict[str, list[dict[str, Any]]] = {}
    for row in pivot:
        tid = row.get("topic_id", "unknown")
        by_topic.setdefault(tid, []).append(row)

    for tid, rows in by_topic.items():
        for col in source_columns:
            values = [float(row.get(col, 0)) for row in rows]
            z_outliers = detect_zscore_outliers(values, zscore_threshold)
            iqr_outliers = detect_iqr_outliers(values, iqr_k)
            zero_tags = detect_consecutive_zeros(values, min_consecutive_zeros)
            drop_tags = detect_sudden_drop(values, min_nonzero_before_drop)

            for i, row in enumerate(rows):
                row[f"{col}_zscore_outlier"] = z_outliers[i]
                row[f"{col}_iqr_outlier"] = iqr_outliers[i]
                zero_tag = zero_tags[i]
                drop_tag = drop_tags[i]
                tag = zero_tag or drop_tag
                row[f"{col}_zero_tag"] = tag
                row[f"{col}_any_anomaly"] = z_outliers[i] or iqr_outliers[i] or bool(tag)

    return pivot


def summarize_anomalies(pivot: list[dict[str, Any]]) -> dict[str, Any]:
    """Produce a summary of detected anomalies for the quality report.

    Args:
        pivot: Pivot table with anomaly tags (output of tag_anomalies_in_pivot).

    Returns:
        Dict with per-source, per-topic anomaly counts.
    """
    source_columns = [
        c for c in (pivot[0].keys() if pivot else [])
        if c.endswith("_any_anomaly")
    ]

    summary: dict[str, Any] = {
        "total_anomalies": 0,
        "by_source": {},
        "by_topic": {},
    }

    for row in pivot:
        tid = row.get("topic_id", "unknown")
        topic_entry = summary["by_topic"].setdefault(tid, {"anomalies": 0, "total": 0})
        topic_entry["total"] += 1
        for col in source_columns:
            source_name = col.replace("_any_anomaly", "")
            src_entry = summary["by_source"].setdefault(source_name, {"anomalies": 0, "total": 0})
            src_entry["total"] += 1
            if row.get(col, False):
                src_entry["anomalies"] += 1
                topic_entry["anomalies"] += 1
                summary["total_anomalies"] += 1

    return summary
