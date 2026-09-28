import json
import math
import pandas as pd
from pathlib import Path
from typing import Any


def save_records_to_jsonl(
    records: list[dict[str, Any]],
    output_path: Path,
) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    from techtrend.signal.processors.json_utils import NumpyEncoder
    with open(output_path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False, cls=NumpyEncoder) + "\n")
    return len(records)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def merge_records_by_source(
    openalex_records: list[dict[str, Any]],
    gdelt_records: list[dict[str, Any]],
    crossref_records: list[dict[str, Any]] | None = None,
    github_records: list[dict[str, Any]] | None = None,
    arxiv_records: list[dict[str, Any]] | None = None,
    uspto_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if crossref_records is None:
        crossref_records = []
    if github_records is None:
        github_records = []
    if arxiv_records is None:
        arxiv_records = []
    if uspto_records is None:
        uspto_records = []
    merged = openalex_records + crossref_records + arxiv_records + uspto_records + gdelt_records + github_records
    merged.sort(key=lambda r: (r["topic_id"], r["window_start"], r["source"]))
    return merged


def _safe_count(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def build_feature_matrix(
    records: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    by_topic: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        tid = rec["topic_id"]
        if tid not in by_topic:
            by_topic[tid] = []
        by_topic[tid].append(rec)

    for tid in by_topic:
        by_topic[tid].sort(key=lambda r: (r["window_start"], r["source"]))

    return by_topic


def create_pivot_table(
    records: list[dict[str, Any]],
) -> pd.DataFrame:
    df = pd.DataFrame(records)
    if df.empty:
        return pd.DataFrame(columns=[
            "topic_id", "topic_label", "window_start",
            "openalex_count", "crossref_count", "arxiv_count", 
            "uspto_count", "gdelt_count", "github_count"
        ])
    
    df["activity_count"] = pd.to_numeric(df["activity_count"], errors="coerce").fillna(0)
    
    pivot = df.pivot_table(
        index=["topic_id", "topic_label", "window_start", "window_end"],
        columns="source",
        values="activity_count",
        aggfunc="sum",
        fill_value=0
    ).reset_index()
    
    rename_cols = {col: f"{col}_count" for col in pivot.columns if col not in ["topic_id", "topic_label", "window_start", "window_end"]}
    pivot = pivot.rename(columns=rename_cols)
    
    for src in ["openalex", "crossref", "arxiv", "uspto", "gdelt", "github"]:
        col = f"{src}_count"
        if col not in pivot.columns:
            pivot[col] = 0
            
    return pivot.sort_values(["topic_id", "window_start"])


# ---------------------------------------------------------------------------
# Cross-source standardization methods (Pandas)
# ---------------------------------------------------------------------------

def standardize_pivot(
    pivot: pd.DataFrame,
    source_columns: list[str] | None = None,
    method: str = "robust",
) -> pd.DataFrame:
    if source_columns is None:
        source_columns = [c for c in pivot.columns if c.endswith("_count")]

    if pivot.empty:
        for col in source_columns:
            pivot[f"{col}_std"] = 0.0
        return pivot

    def _apply_method(group: pd.Series) -> pd.Series:
        n = len(group)
        if n == 0:
            return pd.Series(0.5, index=group.index)
        
        if method == "robust":
            median = group.median()
            q1 = group.quantile(0.25)
            q3 = group.quantile(0.75)
            iqr = q3 - q1
            if iqr < 1e-9:
                return pd.Series(0.0, index=group.index)
            return ((group - median) / iqr).round(4)
        elif method == "rank":
            if n <= 1:
                return pd.Series(0.5, index=group.index)
            ranks = group.rank(method="average") - 1
            return (ranks / (n - 1)).round(4)
        elif method == "log1p":
            import numpy as np
            log_vals = np.log1p(np.maximum(group, 0.0))
            lo, hi = log_vals.min(), log_vals.max()
            if hi - lo < 1e-9:
                return pd.Series(0.5, index=group.index)
            return ((log_vals - lo) / (hi - lo)).round(4)
        elif method == "minmax":
            lo, hi = group.min(), group.max()
            if hi - lo < 1e-9:
                return pd.Series(0.5, index=group.index)
            return ((group - lo) / (hi - lo)).round(4)
        else:
            raise ValueError(f"Unknown standardization method: {method!r}")

    for col in source_columns:
        pivot[f"{col}_std"] = pivot.groupby("window_start")[col].transform(_apply_method)

    return pivot
