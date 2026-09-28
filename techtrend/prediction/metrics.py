"""评估指标：排名（precision@k / recall@k）+ TKG 过滤排名（mrr/hits）+ 回归（mae/rmse/mape）。

`ranked` 与 `truth` 均为一组可哈希的 ID（概念 ID 列表）；`ranked` 有序（按预测置信度降序）。
"""


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
