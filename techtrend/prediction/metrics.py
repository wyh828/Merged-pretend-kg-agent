"""评估指标：排名（precision@k / recall@k）+ TKG 过滤排名（mrr/hits）+ 回归（mae/rmse/mape）。

`ranked` 与 `truth` 均为一组可哈希的 ID（概念 ID 列表）；`ranked` 有序（按预测置信度降序）。
"""
import math


def _top_k(ranked, k: int) -> set:
    return set(list(ranked)[:k])


def precision_at_k(ranked, truth, k: int) -> float:
    top = _top_k(ranked, k)
    if not top:
        return 0.0
    return len(top & set(truth)) / len(top)


def recall_at_k(ranked, truth, k: int) -> float:
    truth = set(truth)
    if not truth:
        return 0.0
    return len(_top_k(ranked, k) & truth) / len(truth)


def mrr_at(ranks: list[int]) -> float:
    """1/rank 均值（rank 从 1 起）。"""
    if not ranks:
        return 0.0
    return sum(1.0 / r for r in ranks) / len(ranks)


def hits_at(ranks: list[int], k: int) -> float:
    """rank ≤ k 的比例。"""
    if not ranks:
        return 0.0
    return sum(1 for r in ranks if r <= k) / len(ranks)


def mae(actual, pred) -> float:
    """平均绝对误差。"""
    n = len(actual)
    if n == 0:
        return 0.0
    return sum(abs(a - p) for a, p in zip(actual, pred)) / n


def rmse(actual, pred) -> float:
    """均方根误差。"""
    n = len(actual)
    if n == 0:
        return 0.0
    return (sum((a - p) ** 2 for a, p in zip(actual, pred)) / n) ** 0.5


def mape(actual, pred) -> float:
    """平均绝对百分比误差（0 真值跳过，防除零）。"""
    pairs = [(a, p) for a, p in zip(actual, pred) if a != 0]
    if not pairs:
        return 0.0
    return sum(abs(a - p) / abs(a) for a, p in pairs) / len(pairs)


# ---------------------------------------------------------------------------
# 排序类指标（阶段 2 合并，来自 pretend-agent scoring.py 的 calculate_spearman_rho /
# calculate_ndcg_at_k 与 evaluate_ranking 的 top1_lift 公式）
# ---------------------------------------------------------------------------
def spearman_rho(pred_scores: dict, true_scores: dict) -> float:
    """Spearman 秩相关：预测分排序 vs 真值排序的单调相关性，[-1,1]。

    pred_scores / true_scores 均为 {id: 数值}（值越大越靠前）。
    """
    common = [t for t in pred_scores if t in true_scores]
    n = len(common)
    if n < 2:
        return 0.0

    sorted_pred = sorted(common, key=lambda t: pred_scores[t], reverse=True)
    pred_ranks = {t: r for r, t in enumerate(sorted_pred, start=1)}
    sorted_true = sorted(common, key=lambda t: true_scores[t], reverse=True)
    true_ranks = {t: r for r, t in enumerate(sorted_true, start=1)}

    d_sq = sum((pred_ranks[t] - true_ranks[t]) ** 2 for t in common)
    return 1.0 - (6.0 * d_sq) / (n * (n**2 - 1))


def ndcg_at_k(ranked: list, relevance: dict, k: int) -> float:
    """NDCG@K：位置折扣的排序命中质量（关注头部）。

    ranked 有序（预测降序）；relevance 为 {id: 真值分}（分级相关度，2**rel-1 增益）。
    """
    if not ranked or not relevance:
        return 0.0
    k = min(k, len(ranked))
    dcg = sum(
        (2.0 ** max(relevance.get(t, 0.0), 0.0) - 1.0) / math.log2(i + 2)
        for i, t in enumerate(ranked[:k])
    )
    ideal = sorted(relevance, key=lambda t: relevance[t], reverse=True)[:k]
    idcg = sum(
        (2.0 ** max(relevance.get(t, 0.0), 0.0) - 1.0) / math.log2(i + 2)
        for i, t in enumerate(ideal)
    )
    if idcg <= 1e-9:
        return 1.0 if dcg <= 1e-9 else 0.0
    return dcg / idcg


def top1_lift(ranked: list, relevance: dict) -> float | None:
    """Top-1 Lift：榜首真值 / 全池真值均值，>1 表示有正向选技术能力。"""
    if not ranked or not relevance:
        return None
    top1 = relevance.get(ranked[0], 0.0)
    mean = sum(relevance.get(r, 0.0) for r in ranked) / len(ranked)
    if mean <= 0:
        return None
    return top1 / mean
