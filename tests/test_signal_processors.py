"""techtrend.signal.processors 最小冒烟测试（阶段 0 合并验收）。

针对当前 API 编写：detector/cleaner 用 list 入参，normalize 的
create_pivot_table / standardize_pivot 用 pandas.DataFrame 入参。

注：上游 pretend-agent 的 Attempt/tests/test_processors.py 已过时——它引用了
已重构进 standardize_pivot 的 robust_scale/rank_normalize/log1p_normalize，并把
list 传给现在只接受 DataFrame 的函数。本文件按现状重写为可运行的最小回归。

运行（仓库根目录）：
    py -3.12 -m pytest tests/test_signal_processors.py -v
"""

from __future__ import annotations

import pandas as pd

from techtrend.signal.processors.cleaner import clean_records, filter_failed_records
from techtrend.signal.processors.detector import (
    detect_consecutive_zeros,
    detect_iqr_outliers,
    detect_sudden_drop,
    detect_zscore_outliers,
    summarize_anomalies,
    tag_anomalies_in_pivot,
)
from techtrend.signal.processors.normalize import create_pivot_table, standardize_pivot


# ---------------------------------------------------------------------------
# detector
# ---------------------------------------------------------------------------

def test_zscore_outlier_detection() -> None:
    values = [10, 12, 11, 10, 13, 500, 11, 10]
    # 默认 threshold=3.0（滚动 z 分数，log1p 变换）：500 的滚窗 z≈35 必被标出，
    # 而 13 相对前 4 个紧密聚簇值 z≈2.56，低于 3.0 不标，保证只有 500 一个异常。
    outliers = detect_zscore_outliers(values, threshold=3.0)
    assert outliers[5] is True  # the 500 spike
    assert sum(outliers) == 1


def test_zscore_no_outliers_in_constant_series() -> None:
    values = [5, 5, 5, 5, 5]
    assert not any(detect_zscore_outliers(values))


def test_iqr_outlier_detection() -> None:
    values = [1, 2, 3, 4, 5, 6, 7, 8, 100]
    outliers = detect_iqr_outliers(values, k=1.5)
    assert outliers[-1] is True  # 100 is an outlier
    assert not outliers[0]


def test_consecutive_zeros_flagged() -> None:
    values = [10, 0, 0, 0, 10, 0, 10]
    tags = detect_consecutive_zeros(values, min_consecutive=3)
    assert tags[1:4] == ["likely_api_failure"] * 3
    assert tags[0] == ""
    assert tags[5] == ""  # single zero, not flagged


def test_sudden_drop_detected() -> None:
    values = [10, 20, 30, 40, 0, 10]
    tags = detect_sudden_drop(values, min_nonzero_before=3)
    assert tags[4] == "sudden_drop"
    assert tags[0] == ""


def test_tag_anomalies_in_pivot() -> None:
    pivot = [
        {"topic_id": "ai", "window_start": "2026-01", "crossref_count": 10, "gdelt_count": 100},
        {"topic_id": "ai", "window_start": "2026-02", "crossref_count": 12, "gdelt_count": 110},
        {"topic_id": "ai", "window_start": "2026-03", "crossref_count": 11, "gdelt_count": 105},
        {"topic_id": "ai", "window_start": "2026-04", "crossref_count": 5000, "gdelt_count": 120},
        {"topic_id": "ai", "window_start": "2026-05", "crossref_count": 10, "gdelt_count": 130},
    ]
    tagged = tag_anomalies_in_pivot(pivot, zscore_threshold=1.5)
    assert "crossref_count_zscore_outlier" in tagged[0]
    assert tagged[3]["crossref_count_zscore_outlier"] is True  # 5000 spike
    assert summarize_anomalies(tagged)["total_anomalies"] > 0


# ---------------------------------------------------------------------------
# cleaner
# ---------------------------------------------------------------------------

def test_filter_failed_records() -> None:
    records = [
        {"source": "crossref", "topic_id": "ai", "window_start": "2026-01", "activity_count": 10, "collection_status": "ok"},
        {"source": "crossref", "topic_id": "ai", "window_start": "2026-02", "activity_count": None, "collection_status": "failed"},
        {"source": "gdelt", "topic_id": "ai", "window_start": "2026-01", "activity_count": 100, "collection_status": "ok"},
    ]
    ok, failed = filter_failed_records(records)
    assert len(ok) == 2
    assert len(failed) == 1
    assert failed[0]["collection_status"] == "failed"


def test_clean_records_log() -> None:
    records = [
        {"source": "crossref", "topic_id": "ai", "activity_count": 10, "collection_status": "ok"},
        {"source": "crossref", "topic_id": "ai", "activity_count": None, "collection_status": "failed"},
        {"source": "gdelt", "topic_id": "ai", "activity_count": 100, "collection_status": "ok"},
    ]
    clean, log = clean_records(records)
    assert len(clean) == 2
    assert log["input_count"] == 3
    assert log["ok_count"] == 2
    assert log["failed_count"] == 1
    assert log["failed_by_source"]["crossref"] == 1


# ---------------------------------------------------------------------------
# normalize
# ---------------------------------------------------------------------------

def test_create_pivot_table() -> None:
    records = [
        {"topic_id": "ai", "topic_label": "AI", "window_start": "2026-01", "window_end": "2026-02", "source": "crossref", "activity_count": 10},
        {"topic_id": "ai", "topic_label": "AI", "window_start": "2026-01", "window_end": "2026-02", "source": "gdelt", "activity_count": 100},
    ]
    df = create_pivot_table(records)
    assert "crossref_count" in df.columns
    assert "gdelt_count" in df.columns
    assert int(df.iloc[0]["crossref_count"]) == 10
    assert int(df["gdelt_count"].sum()) == 100


def test_standardize_pivot_robust() -> None:
    # 同一窗口两条记录，robust 标准化后应得到对称的 ±1.0
    df = pd.DataFrame([
        {"topic_id": "ai", "window_start": "2026-01", "crossref_count": 10},
        {"topic_id": "robotics", "window_start": "2026-01", "crossref_count": 30},
    ])
    result = standardize_pivot(df, method="robust")
    assert "crossref_count_std" in result.columns
    assert list(result["crossref_count_std"]) == [-1.0, 1.0]


def test_standardize_pivot_rank() -> None:
    df = pd.DataFrame([
        {"topic_id": "ai", "window_start": "2026-01", "crossref_count": 10},
        {"topic_id": "robotics", "window_start": "2026-01", "crossref_count": 30},
    ])
    result = standardize_pivot(df, method="rank")
    assert "crossref_count_std" in result.columns
    assert result["crossref_count_std"].iloc[0] == 0.0
    assert result["crossref_count_std"].iloc[1] == 1.0
