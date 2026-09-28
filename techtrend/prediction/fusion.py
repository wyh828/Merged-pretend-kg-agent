"""多信号融合（目标①集成）：Kleinberg 突发 + TKG 分 + 回归增速 → 加权排名。

三路信号各自秩归一（处理缺失：缺省 0），再按权重加权求和排序 top_k，验证融合是否
改善新兴技术识别（对比 Kleinberg 单独 precision@k=0）。
"""
import logging

log = logging.getLogger(__name__)


def parse_weights(spec: str) -> dict[str, float]:
    """解析 "burst=0.3,tkg=0.4,forecast=0.3" → {name: weight}。"""
    weights: dict[str, float] = {}
    for part in (spec or "").split(","):
        part = part.strip()
        if "=" in part:
            name, val = part.split("=", 1)
            try:
                weights[name.strip()] = float(val.strip())
            except ValueError:
                log.warning("融合权重解析失败，忽略：%s", part)
    return weights


def zscore_rank(scores: dict[str, float]) -> dict[str, float]:
    """按秩归一到 [0,1]（处理缺失：调用方对缺失信号取 0）。

    最高分 → 1.0，最低分 → 0.0，等距按排名线性映射（对离群值鲁棒）。
    """
    if not scores:
        return {}
    items = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    n = len(items)
    if n == 1:
        return {items[0][0]: 1.0}
    return {e: (n - 1 - i) / (n - 1) for i, (e, _) in enumerate(items)}


def fuse(
    burst: dict[str, float],
    tkg: dict[str, float],
    forecast: dict[str, float],
    weights: dict[str, float],
    top_k: int,
    names: dict[str, str] | None = None,
) -> list[dict]:
    """三路信号秩归一后加权求和 → 排序 top_k。

    返回 [{"entity","name","score","burst","tkg","forecast"}]（各分已秩归一）。
    """
    names = names or {}
    n_burst = zscore_rank(burst)
    n_tkg = zscore_rank(tkg)
    n_forecast = zscore_rank(forecast)

    entities = set(n_burst) | set(n_tkg) | set(n_forecast)
    rows = []
    for e in entities:
        b = n_burst.get(e, 0.0)
        tk = n_tkg.get(e, 0.0)
        f = n_forecast.get(e, 0.0)
        score = (
            weights.get("burst", 0.0) * b
            + weights.get("tkg", 0.0) * tk
            + weights.get("forecast", 0.0) * f
        )
        rows.append(
            {"entity": e, "name": names.get(e, ""), "score": score, "burst": b, "tkg": tk, "forecast": f}
        )
    rows.sort(key=lambda r: r["score"], reverse=True)
    top = rows[:top_k]
    log.info("融合：%d 个实体参与，top-%d = %s", len(rows), len(top), [r["entity"] for r in top[:5]])
    return top
