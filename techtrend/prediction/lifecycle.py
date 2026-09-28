"""S 曲线生命周期阶段分类（P6，目标④）—— 概念级 + 专利级共用。

把 [citations.py](techtrend/prediction/citations.py) 里专利专用的 `s_curve_stage` 抽出泛化：
输入任意「单调不减累积序列」（专利累积被引 / 概念累积活动量），输出
emerging / growth / mature / declining 四阶段。

关键修正（承 PROJECT_PLAN §P4_P3_RESULT 与 P6_PLAN §6.1）：
原版 `if total < 0.2 * max(x)` 在累积序列上恒为假（`total == x[-1] == max(x)`），
emerging 分支永远走不到 → 实测只出 mature/declining 两类。新版改为：
  1. 序列箱数 < min_history → emerging（历史太短，无法判阶段）
  2. 累积终点 < 全样本 emerging_quantile 分位 → emerging（相对同侪仍小）
并重写 declining 判据：近 growth_window 月增量为 0（近期停止增长），
而非旧版「全程无增长」（`x[-1] <= x[0]`）。

诚实边界：阶段标签是启发式，不是监督真值；样本量小（专利 top-N 已截断）时分位不稳，
报告须注明「阶段标签是启发式」。
"""
import logging
from typing import Iterable

import pandas as pd

log = logging.getLogger(__name__)

STAGES = ("emerging", "growth", "mature", "declining")


def s_curve_stage(
    series: Iterable[float],
    growth_window: int = 6,
    emerging_threshold: float | None = None,
    min_history: int = 12,
) -> str:
    """单条「累积」序列 → S 曲线阶段标签（目标④）。

    - emerging  箱数 < min_history，或（给定阈值时）累积终点 < emerging_threshold
    - growth    近期增速 > 历史增速（二阶导 > 0，加速上升）
    - mature    近期增速 > 0 但 ≤ 历史增速（减速仍增长，饱和）
    - declining 近 growth_window 月增量为 0（已停止增长）
    """
    x = [float(v) for v in series if v is not None and float(v) == float(v)]
    if len(x) < 3:
        return "emerging"
    total = x[-1]
    if total <= 0:
        return "emerging"
    if len(x) < min_history:
        return "emerging"
    if emerging_threshold is not None and total < emerging_threshold:
        return "emerging"

    w = min(growth_window, len(x) - 1)
    recent_growth = x[-1] - x[-w - 1]
    hist_growth = x[-w - 1] - x[0]

    if recent_growth <= 0:
        return "declining"
    if hist_growth <= 0:
        # 历史无增长、近期才起量 → 二次起飞，判 growth
        return "growth"
    if recent_growth > hist_growth:
        return "growth"
    return "mature"


def s_curve_stages(
    monthly: pd.DataFrame,
    growth_window: int = 6,
    emerging_quantile: float = 0.2,
    min_history: int = 12,
) -> pd.Series:
    """累积矩阵（index=实体，columns=升序时间箱）→ 每实体阶段标签。

    `emerging_quantile` 对全样本终点分布取分位作 emerging 阈值（样本级，
    单条 `s_curve_stage` 的 `emerging_threshold` 由这里算出后传入）。
    """
    if monthly.empty:
        return pd.Series(dtype=str)
    totals = monthly.iloc[:, -1].astype(float)
    threshold = float(totals.quantile(emerging_quantile)) if len(totals) else None
    return monthly.apply(
        lambda row: s_curve_stage(
            row.to_numpy(dtype=float),
            growth_window=growth_window,
            emerging_threshold=threshold,
            min_history=min_history,
        ),
        axis=1,
    )


def concept_lifecycle_stages(
    monthly: pd.DataFrame,
    growth_window: int = 6,
    emerging_quantile: float = 0.2,
    min_history: int = 12,
) -> pd.Series:
    """概念级 S 曲线（P6 主演示路径）：概念月度活动量 → 累积 → 逐概念阶段标签。

    `monthly` 是 concept × 时间箱 的**活动量**矩阵（由
    [kleinberg.py](techtrend/prediction/kleinberg.py) `build_concept_monthly_counts` 产出），
    本函数先 `cumsum` 成累积序列再判阶段。
    """
    if monthly.empty:
        return pd.Series(dtype=str)
    cumulative = monthly.cumsum(axis=1)
    return s_curve_stages(
        cumulative,
        growth_window=growth_window,
        emerging_quantile=emerging_quantile,
        min_history=min_history,
    )


def mean_stage_curves(cumulative: pd.DataFrame, stages: pd.Series) -> pd.DataFrame:
    """每个阶段一条「归一化累积」均值曲线（供 S 曲线形状叠加图）。

    输入：`cumulative`（index=实体，columns=升序时间箱，值=单调不减累积量）、
    `stages`（index=实体，值=阶段标签）。每个实体按自身终点归一化（max→1），
    在阶段内求均值 → DataFrame(index=阶段, columns=时间箱, 值∈[0,1])。
    无样本的阶段整行跳过；STAGES 固定顺序（emerging→growth→mature→declining）。
    """
    curves: dict[str, pd.Series] = {}
    for st in STAGES:
        idx = stages.index[stages == st]
        if len(idx) == 0:
            continue
        sub = cumulative.reindex(index=idx.intersection(cumulative.index)).dropna(how="all")
        if sub.empty:
            continue
        rowmax = sub.max(axis=1).replace(0, 1.0)
        norm = sub.div(rowmax, axis=0).fillna(0.0)
        curves[st] = norm.mean(axis=0)
    if not curves:
        return pd.DataFrame()
    return pd.DataFrame(curves).T


__all__ = [
    "STAGES",
    "s_curve_stage",
    "s_curve_stages",
    "concept_lifecycle_stages",
    "mean_stage_curves",
]
