"""Processors package: normalization, cleaning, anomaly detection, quality checks."""

from techtrend.signal.processors.normalize import (
    save_records_to_jsonl,
    load_jsonl,
    merge_records_by_source,
    create_pivot_table,
    standardize_pivot,
)
from techtrend.signal.processors.cleaner import (
    filter_failed_records,
    filter_anomalous_pivot_rows,
    fill_missing_windows,
    smooth_signal,
    clean_records,
    save_cleaning_log,
)
from techtrend.signal.processors.detector import (
    detect_zscore_outliers,
    detect_iqr_outliers,
    detect_consecutive_zeros,
    detect_sudden_drop,
    tag_anomalies_in_pivot,
    summarize_anomalies,
)
from techtrend.signal.processors.quality_checker import (
    check_data_quality,
    save_quality_report,
)
