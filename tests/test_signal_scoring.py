"""techtrend.prediction.signal（阶段 1 合并：相对份额动量信号）最小回归。

覆盖：EMA / robust 归一化 / safe-growth 的数学正确性，以及「加速扩张的黑马
> 平稳领跑的成熟概念」的排名性质。运行（仓库根目录）：
    F:\\Predictive agents\\.venv\\Scripts\\python.exe -m pytest tests/test_signal_scoring.py -v
"""
from __future__ import annotations

import pandas as pd

from techtrend.prediction.signal import (
    _ema,
    _robust_normalize,
    _safe_growth,
    concept_share_momentum,
    share_momentum_rank,
)


def test_ema_known_value() -> None:
    # span=3 → α=0.5；[0, 10] 的 EMA = 0*0.5 + 10*0.5 = 5
    assert _ema([0.0, 10.0], span=3) == 5.0


def test_ema_empty_returns_zero() -> None:
    assert _ema([], span=3) == 0.0


def test_safe_growth_monotonic() -> None:
    assert _safe_growth(10.0, 5.0) > 0.0
    assert _safe_growth(5.0, 10.0) < 0.0


def test_robust_normalize_range_and_monotonic() -> None:
    out = _robust_normalize({"a": 1.0, "b": 10.0, "c": 100.0})
    assert all(0.0 <= v <= 1.0 for v in out.values())
    assert out["c"] > out["b"] > out["a"]


def test_robust_normalize_constant_returns_half() -> None:
    out = _robust_normalize({"a": 5.0, "b": 5.0})
    assert out == {"a": 0.5, "b": 0.5}


def test_robust_normalize_no_overflow_on_extreme_skew() -> None:
    # 极端偏态：紧聚簇 + 一个远低于中位数的离群值 → z 极负 → 修复前 math.exp 溢出
    values = {f"x{i}": float(i) for i in range(1, 101)}  # 1..100
    values["neg_outlier"] = -1e12
    out = _robust_normalize(values)
    assert all(0.0 <= v <= 1.0 for v in out.values())
    assert out["neg_outlier"] < 1e-6


def test_concept_share_momentum_scores_in_unit_interval() -> None:
    df = pd.DataFrame(
        [
            [100] * 12,
            [1, 2, 5, 10, 20, 40, 80, 120, 160, 200, 250, 300],
        ],
        index=["mature", "emerging"],
        columns=[f"m{i}" for i in range(12)],
    )
    scores = concept_share_momentum(df)
    assert set(scores) == {"mature", "emerging"}
    assert all(0.0 <= v <= 1.0 for v in scores.values())


def test_share_momentum_rank_prefers_accelerating_emerging() -> None:
    # mature 稳定领跑但零动量；emerging 份额在末端加速扩张 → 应排更前
    df = pd.DataFrame(
        [
            [100] * 12,
            [1, 2, 5, 10, 20, 40, 80, 120, 160, 200, 250, 300],
        ],
        index=["mature", "emerging"],
        columns=[f"m{i}" for i in range(12)],
    )
    ranked = share_momentum_rank(df, top_k=2)
    assert ranked[0] == "emerging"
    assert len(ranked) == 2
