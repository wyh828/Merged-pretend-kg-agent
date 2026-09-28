"""预测层（P3）：Kleinberg 突发 + RotatE 链接预测 + TKG 外推 + 回归 + 融合。"""
from techtrend.prediction.kleinberg import (
    build_concept_monthly_counts,
    detect_top_bursts,
    future_growth_top_k,
    kleinberg_bursts,
)
from techtrend.prediction.metrics import (
    hits_at,
    mae,
    mape,
    mrr_at,
    precision_at_k,
    recall_at_k,
    rmse,
)
from techtrend.prediction.rotatE import (
    build_triples_factory,
    random_split,
    run_rotate,
    temporal_split,
)

__all__ = [
    # Kleinberg
    "kleinberg_bursts",
    "build_concept_monthly_counts",
    "detect_top_bursts",
    "future_growth_top_k",
    # 指标
    "precision_at_k",
    "recall_at_k",
    "mrr_at",
    "hits_at",
    "mae",
    "rmse",
    "mape",
    # RotatE 静态基线
    "build_triples_factory",
    "temporal_split",
    "random_split",
    "run_rotate",
]
