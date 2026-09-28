"""Kleinberg 突发检测（Kleinberg 2002 两状态自动机，自实现纯 Python/numpy）。

- 输入：某实体随时间分箱的频次序列（如 concept × month 计数）。
- 两状态：state 0 = 基线速率 p0（= 总计数/箱数），state 1 = 突发速率 s·p0。
- 发射代价用 Poisson 负对数似然；状态切换代价 τ = γ·ln(n)。
- 用 Viterbi 动态规划求最优状态序列，再把连续 state-1 段合并为突发区间。
"""
import logging
import math
from typing import Iterable

import pandas as pd

from techtrend.extraction.structured import short_id

log = logging.getLogger(__name__)

_INF = float("inf")


def _poisson_cost(d: float, rate: float) -> float:
    """-ln P(count=d | rate)，Poisson。rate<=0 时：d==0 代价 0，否则 +inf。"""
    if rate <= 0:
        return 0.0 if d == 0 else _INF
    return rate - d * math.log(rate) + math.lgamma(d + 1)


def kleinberg_bursts(series: Iterable[float], s: float = 2.0, gamma: float = 1.0) -> list[dict]:
    """检测突发区间。返回 [{"start", "end", "weight"}]，start/end 为箱下标（含端点）。"""
    x = [float(v) for v in series]
    n = len(x)
    if n == 0:
        return []
    total = sum(x)
    if total <= 0:
        return []
    p0 = total / n
    p1 = s * p0
    rates = (p0, p1)
    tau = gamma * math.log(n) if n > 1 else 0.0

    # Viterbi 前向
    cost = [[_INF] * n for _ in range(2)]
    prev = [[-1] * n for _ in range(2)]
    for state in (0, 1):
        cost[state][0] = _poisson_cost(x[0], rates[state])
    for t in range(1, n):
        for j in (0, 1):
            emit = _poisson_cost(x[t], rates[j])
            for i in (0, 1):
                trans = 0.0 if i == j else tau
                c = cost[i][t - 1] + trans + emit
                if c < cost[j][t]:
                    cost[j][t] = c
                    prev[j][t] = i

    # 回溯
    path = [0] * n
    path[-1] = 0 if cost[0][-1] <= cost[1][-1] else 1
    for t in range(n - 1, 0, -1):
        path[t - 1] = prev[path[t]][t]

    # 合并连续 state-1 段
    bursts: list[dict] = []
    i = 0
    while i < n:
        if path[i] == 1:
            start = i
            while i < n and path[i] == 1:
                i += 1
            end = i - 1
            bursts.append(
                {"start": start, "end": end, "weight": float(max(x[start : end + 1]))}
            )
        else:
            i += 1
    return bursts


def _bin(date: str, mode: str = "month") -> str:
    """把 publication_date 归到分箱：month → YYYY-MM；day → YYYY-MM-DD。"""
    if mode == "day":
        return date[:10]
    return date[:7]


def build_concept_monthly_counts(works: Iterable[dict], mode: str = "month") -> pd.DataFrame:
    """concept × 时间箱 频次矩阵。index=concept 短 ID，columns=升序时间箱。"""
    records: list[tuple[str, str]] = []
    for w in works:
        date = w.get("publication_date")
        if not date:
            continue
        b = _bin(date, mode)
        for c in w.get("concepts") or []:
            cid = short_id(c.get("id"))
            if cid:
                records.append((cid, b))
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records, columns=["concept", "bin"])
    counts = df.pivot_table(index="concept", columns="bin", aggfunc="size", fill_value=0)
    return counts.reindex(sorted(counts.columns), axis=1)


def concept_names(works: Iterable[dict]) -> dict[str, str]:
    """concept 短 ID → 显示名。"""
    names: dict[str, str] = {}
    for w in works:
        for c in w.get("concepts") or []:
            cid = short_id(c.get("id"))
            if cid and c.get("name"):
                names.setdefault(cid, c["name"])
    return names


def detect_top_bursts(
    df: pd.DataFrame, top_k: int, s: float = 2.0, gamma: float = 1.0
) -> pd.DataFrame:
    """对每个 concept 的时序跑 Kleinberg，按最大突发权重降序取 top_k。

    返回 DataFrame：[concept, weight, n_bursts]。
    """
    rows: list[tuple[str, float, int]] = []
    for cid in df.index:
        series = df.loc[cid].to_numpy(dtype=float)
        bursts = kleinberg_bursts(series, s=s, gamma=gamma)
        weight = max((b["weight"] for b in bursts), default=0.0)
        rows.append((str(cid), weight, len(bursts)))
    rows.sort(key=lambda r: r[1], reverse=True)
    return pd.DataFrame(rows[:top_k], columns=["concept", "weight", "n_bursts"])


def future_growth(df: pd.DataFrame, future_months: int) -> dict[str, float]:
    """ground truth 增速：未来窗口相对历史窗口的频次增速（concept_id → growth）。

    growth = 未来月均 - 历史月均（历史为空的新概念月均按 0 计，故新兴概念可上榜）。
    作为排序类指标（Spearman/NDCG/Top-1 Lift）的真值相关度；与 future_growth_top_k 同口径。
    """
    cols = list(df.columns)
    if len(cols) <= future_months:
        return {}
    hist = df[cols[:-future_months]]
    fut = df[cols[-future_months:]]
    growth = fut.mean(axis=1) - hist.mean(axis=1)
    return {str(c): float(growth[c]) for c in growth.index}


def future_activity(df: pd.DataFrame, future_months: int) -> dict[str, float]:
    """ground truth 未来活跃度：最后 future_months 月的月均频次（concept_id → activity）。

    非负，作排序类指标（Spearman/NDCG/Top-1 Lift）的真值相关度（与她「未来活跃度」同口径）；
    与 `future_growth`（增速，用于 p@k/r@k 的 top-k 真值）并列，两者是同一窗口的两种真值表达。
    """
    cols = list(df.columns)
    if len(cols) <= future_months:
        return {}
    fut = df[cols[-future_months:]]
    return {str(c): float(fut.loc[c].mean()) for c in fut.index}


def future_growth_top_k(df: pd.DataFrame, future_months: int, top_k: int) -> list[str]:
    """ground truth：未来窗口（最后 future_months 月）相对历史的频次增速 top-k。

    growth = 未来月均 - 历史月均（历史为空的新概念月均按 0 计，故新兴概念可进入 top-k）。
    返回按 growth 降序的 concept ID 列表（前 top_k）。
    """
    growth = future_growth(df, future_months)
    ranked = sorted(growth, key=lambda c: growth[c], reverse=True)
    return ranked[:top_k]
