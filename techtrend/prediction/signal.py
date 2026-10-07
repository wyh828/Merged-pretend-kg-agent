"""Concept 级「相对注意力份额 + EMA/MACD 动量」信号（阶段 1 合并，来自 pretend-agent）。

把她的「相对份额 + 动量」从 5–6 个粗粒度主题，适配到 545+ Concept 细粒度：
对每个 concept 的月度频次序列，先做**份额相对化**（share_t = (count_t+1)/(Total_t+N)，
解决「头部成熟概念永远霸榜」），再对份额序列求 EMA(3)/EMA(6) 的 MACD 动量，
作为「谁的注意力份额在加速扩张」的信号——这正是 Kleinberg 突发失效时（p@k=0）
用来救目标①新兴识别的替换信号。

与 :mod:`techtrend.prediction.kleinberg` 并列：两者输入同构（concept × 月频次矩阵），
输出同为 `{concept_id: score}`，可做消融对照。

忠实复用她 `scoring.py` 的数学：`_calculate_ema` / `_robust_normalize`；差异仅在
「per (source, topic) 循环」被替换为「per concept 单序列」（我的 works.jsonl 概念
已跨 6 源合并，无需再按源分桶）。
"""
import logging
import math
import statistics

import pandas as pd

log = logging.getLogger(__name__)

# 与她的 scoring.py 默认特征权重一致（可经 weights 参数覆盖）
DEFAULT_WEIGHTS = {
    "ema_short": 0.25,        # 绝对活跃度动量（短期 EMA）
    "macd": 0.30,             # 绝对 MACD（短-长 EMA 差）
    "relative_growth": 0.20,  # 相对份额动量（share MACD / share 长 EMA）★核心
    "stability": 0.125,       # -波动率（log 增长 std，越低越稳）
    "persistence": 0.125,     # 近 12 月有活跃的月份占比
}


def _ema(series: list[float], span: int) -> float:
    """EMA（span 对应 α=2/(span+1)），空序列返回 0。"""
    if not series:
        return 0.0
    alpha = 2.0 / (span + 1.0)
    ema = float(series[0])
    for val in series[1:]:
        ema = val * alpha + ema * (1.0 - alpha)
    return ema


def _safe_growth(current: float, previous: float) -> float:
    return math.log1p(max(current, 0.0)) - math.log1p(max(previous, 0.0))


def _robust_normalize(values: dict[str, float]) -> dict[str, float]:
    """Median/IQR + sigmoid 缩放到 [0,1]（忠实自她 scoring.py，对离群值鲁棒）。"""
    if not values:
        return {}
    vals = sorted(values.values())
    n = len(vals)
    if n < 2:
        return {k: 0.5 for k in values}

    q1 = vals[n // 4]
    q3 = vals[(n * 3) // 4]
    iqr = q3 - q1
    median = vals[n // 2]

    if math.isclose(iqr, 0.0):
        low, high = vals[0], vals[-1]
        if math.isclose(low, high):
            return {k: 0.5 for k in values}
        return {k: (v - low) / (high - low) for k, v in values.items()}

    result = {}
    for k, v in values.items():
        z = (v - median) / (iqr / 1.34896)  # 1.34896 ≈ 标准正态 IQR
        # 数值稳定性：真实数据中频次分布重尾（大量 0 / 少数巨值）会使 IQR 极小、z 爆炸，
        # sigmoid 在 |z|>35 已饱和到 0/1，先截断防 math.exp 溢出（忠实原数学，只补稳定性）。
        z = max(-35.0, min(35.0, z))
        result[k] = 1.0 / (1.0 + math.exp(-z))
    return result


def concept_share_momentum(
    df: pd.DataFrame,
    *,
    laplace: float = 1.0,
    ema_short_span: int = 3,
    ema_long_span: int = 6,
    min_months: int = 3,
    weights: dict[str, float] | None = None,
) -> dict[str, float]:
    """Concept 级「相对份额 + EMA/MACD 动量」打分。

    参数：
        df         concept × 月频次矩阵（列 = 升序时间箱；与 Kleinberg 输入同构）。
        laplace    Laplace 平滑：share_t = (count_t+laplace)/(Total_t+laplace*N)。
        weights    特征权重（缺省用 DEFAULT_WEIGHTS）。

    返回 `{concept_id: score}`，score 为 robust 归一化后的加权组合，越高表示
    「该 concept 的相对注意力份额正在加速扩张」。序列过短（< min_months）的 concept
    跳过（缺省 0，由融合的秩归一处理）。
    """
    weights = weights or DEFAULT_WEIGHTS
    weight_total = sum(weights.values())
    if weight_total <= 0:
        raise ValueError("特征权重之和必须为正")

    if df is None or df.empty or df.shape[1] < min_months:
        return {}
    # A full matrix can contain entities appearing only after a backtest origin.
    # They must not change Laplace denominators or normalization of past scores.
    df = df.loc[df.sum(axis=1) > 0]
    if df.empty:
        return {}

    # 每月总活跃量（跨全部 concept），用于份额相对化
    totals = df.sum(axis=0)
    n_concepts = df.shape[0]

    features: dict[str, dict[str, float]] = {k: {} for k in weights}
    for cid in df.index:
        series = [float(v) for v in df.loc[cid].to_numpy()]
        if len(series) < min_months:
            continue
        cid = str(cid)

        # 相对份额序列（头部霸榜解法）
        share_values = [
            (c + laplace) / (tot + laplace * n_concepts)
            for c, tot in zip(series, totals.to_numpy())
        ]

        # 绝对 EMA/MACD
        ema_short = _ema(series, ema_short_span)
        ema_long = _ema(series, ema_long_span)
        macd = ema_short - ema_long

        # 相对份额动量（★核心信号）
        share_ema_short = _ema(share_values, ema_short_span)
        share_ema_long = _ema(share_values, ema_long_span)
        share_macd = share_ema_short - share_ema_long
        relative_growth = (share_macd / (share_ema_long + 1e-6)) if share_ema_long > 0 else 0.0

        # 波动率（log 增长的 std）与持久性（近 12 月活跃占比）
        growths = [_safe_growth(series[i], series[i - 1]) for i in range(1, len(series))]
        volatility = statistics.stdev(growths) if len(growths) > 1 else 0.0
        recent = series[-12:]
        persistence = sum(v > 0 for v in recent) / len(recent)

        features["ema_short"][cid] = ema_short
        features["macd"][cid] = macd
        features["relative_growth"][cid] = relative_growth
        features["stability"][cid] = -volatility  # 越低波动越稳 → 取负
        features["persistence"][cid] = persistence

    if not features["ema_short"]:
        return {}

    normalized = {k: _robust_normalize(v) for k, v in features.items()}
    ids = list(features["ema_short"].keys())
    scores: dict[str, float] = {}
    for cid in ids:
        scores[cid] = sum(weights[k] * normalized[k][cid] for k in weights) / weight_total
    return scores


def share_momentum_rank(
    df: pd.DataFrame,
    top_k: int,
    *,
    weights: dict[str, float] | None = None,
) -> list[str]:
    """按相对份额动量降序取 top-k concept ID（与 `kleinberg.detect_top_bursts` 同构）。"""
    scores = concept_share_momentum(df, weights=weights)
    ranked = sorted(scores, key=lambda c: scores[c], reverse=True)
    return ranked[:top_k]
