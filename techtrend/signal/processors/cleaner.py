import json
import math
import pandas as pd
from pathlib import Path
from typing import Any


def filter_failed_records(
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ok: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for rec in records:
        if rec.get("collection_status", "ok") != "ok" or rec.get("activity_count") is None:
            failed.append(rec)
        else:
            ok.append(rec)
    return ok, failed


def filter_anomalous_pivot_rows(
    pivot: pd.DataFrame,
    source_columns: list[str] | None = None,
    drop_zscore: bool = False,
    drop_iqr: bool = False,
    drop_likely_api_failure: bool = True,
    drop_sudden_drop: bool = False,
) -> tuple[pd.DataFrame, dict[str, int]]:
    if source_columns is None:
        source_columns = [c for c in pivot.columns if c.endswith("_count")]

    drop_counts = {
        "zscore": 0,
        "iqr": 0,
        "likely_api_failure": 0,
        "sudden_drop": 0,
        "total_dropped": 0,
    }
    
    active_source_columns = [c for c in source_columns if c in pivot.columns and pivot[c].sum() > 0]
    if not active_source_columns:
        return pivot, drop_counts

    drop_mask = pd.Series(False, index=pivot.index)

    if drop_zscore:
        cols = [f"{c}_zscore_outlier" for c in active_source_columns if f"{c}_zscore_outlier" in pivot.columns]
        if cols:
            mask = pivot[cols].any(axis=1)
            drop_counts["zscore"] = mask.sum()
            drop_mask |= mask

    if drop_iqr:
        cols = [f"{c}_iqr_outlier" for c in active_source_columns if f"{c}_iqr_outlier" in pivot.columns]
        if cols:
            mask = pivot[cols].any(axis=1)
            drop_counts["iqr"] = mask.sum()
            drop_mask |= mask

    if drop_likely_api_failure:
        cols = [f"{c}_zero_tag" for c in active_source_columns if f"{c}_zero_tag" in pivot.columns]
        if cols:
            mask = (pivot[cols] == "likely_api_failure").all(axis=1)
            drop_counts["likely_api_failure"] = mask.sum()
            drop_mask |= mask

    if drop_sudden_drop:
        cols = [f"{c}_zero_tag" for c in active_source_columns if f"{c}_zero_tag" in pivot.columns]
        if cols:
            mask = (pivot[cols] == "sudden_drop").all(axis=1)
            drop_counts["sudden_drop"] = mask.sum()
            drop_mask |= mask

    drop_counts["total_dropped"] = drop_mask.sum()
    cleaned = pivot[~drop_mask].copy()

    return cleaned, drop_counts


def fill_missing_windows(
    pivot: pd.DataFrame,
    all_windows: list[str],
    source_columns: list[str] | None = None,
    strategy: str = "zero_fill",
) -> tuple[pd.DataFrame, dict[str, int]]:
    if source_columns is None:
        source_columns = [c for c in pivot.columns if c.endswith("_count")]

    if not all_windows or pivot.empty:
        return pivot, {"filled": 0, "by_strategy": {strategy: 0}}

    topic_ids = pivot["topic_id"].unique()
    
    # Create complete multi-index of all (topic_id, window_start)
    multi_idx = pd.MultiIndex.from_product(
        [topic_ids, all_windows], names=["topic_id", "window_start"]
    )
    
    # Set index to match and reindex
    pivot_indexed = pivot.set_index(["topic_id", "window_start"])
    filled_count = len(multi_idx) - len(pivot_indexed)
    
    # Identify the topic_label mapping
    topic_labels = pivot[["topic_id", "topic_label"]].drop_duplicates().set_index("topic_id")["topic_label"]
    
    pivot_reindexed = pivot_indexed.reindex(multi_idx)
    
    # Restore topic_label
    pivot_reindexed["topic_label"] = pivot_reindexed.index.get_level_values("topic_id").map(topic_labels)
    pivot_reindexed["_filled"] = pivot_reindexed[source_columns[0]].isna()
    
    # Groupby topic_id to fill values
    for col in source_columns:
        if strategy == "zero_fill":
            pivot_reindexed[col] = pivot_reindexed[col].fillna(0)
        elif strategy == "forward_fill":
            pivot_reindexed[col] = pivot_reindexed.groupby("topic_id")[col].ffill().fillna(0)
        else:
            pivot_reindexed[col] = pivot_reindexed[col].fillna(0)
            
    # For any remaining columns, just forward fill
    other_cols = [c for c in pivot_reindexed.columns if c not in source_columns and c not in ["topic_label", "_filled"]]
    for col in other_cols:
        pivot_reindexed[col] = pivot_reindexed.groupby("topic_id")[col].ffill()

    result = pivot_reindexed.reset_index()
    
    fill_counts = {"filled": filled_count, "by_strategy": {strategy: filled_count}}
    return result, fill_counts


def smooth_signal(
    pivot: pd.DataFrame,
    source_columns: list[str] | None = None,
    window_size: int = 3,
    method: str = "median",
) -> pd.DataFrame:
    if source_columns is None:
        source_columns = [c for c in pivot.columns if c.endswith("_count")]

    if pivot.empty:
        return pivot

    pivot = pivot.sort_values(["topic_id", "window_start"])

    for col in source_columns:
        if method == "median":
            smoothed = pivot.groupby("topic_id")[col].rolling(window=window_size, center=False, min_periods=1).median()
        else:
            smoothed = pivot.groupby("topic_id")[col].rolling(window=window_size, center=False, min_periods=1).mean()
        
        # rolling returns multi-index (topic_id, original_index)
        # we can align back to the original dataframe
        pivot[f"{col}_smoothed"] = smoothed.reset_index(level=0, drop=True).round(2)

    return pivot


def clean_records(
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    ok, failed = filter_failed_records(records)
    log = {
        "input_count": len(records),
        "ok_count": len(ok),
        "failed_count": len(failed),
        "failed_by_source": {},
    }
    for rec in failed:
        src = rec.get("source", "unknown")
        log["failed_by_source"][src] = log["failed_by_source"].get(src, 0) + 1
    return ok, log


def save_cleaning_log(log: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    from techtrend.signal.processors.json_utils import NumpyEncoder
    with open(path, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2, cls=NumpyEncoder)
