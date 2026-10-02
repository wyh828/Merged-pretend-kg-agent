"""专利前向引用图 + 引用时序（P0-1 / P1-2 共用）。

把「后向引用对」（citing→cited，来自 PatentsView bulk / BigQuery / 本地 USPTO XML
三源同构）反转聚合为前向引用事实（cited, "cited_by", citing, time=citing_date），
仅供目标③回归真值 + 目标④ S 曲线使用：

1. **前向引用事实流**（原料，落 data/interim/patent_citations.jsonl）：
   (cited, "cited_by", citing, time=citing_date)。注意：专利引用图是时态 DAG + 单事件边，
   经 P2-1 实测不能作为 TKG 边源（copy 无史可复、test 尾部被转导协议整体剔除），
   故已从 tkg_edge_source 移除，仅服务 P1-2 引用时序。

2. **专利累积前向引用时序矩阵**（目标③回归真值 + 目标④ S 曲线）：
   patent × month，值 = 截至该月累计被引用次数（替换「月度活动量」代理信号）。

3. **S 曲线阶段标签**（目标④）：基于累积引用曲线的增速/二阶导分类
   emerging / growth / mature / declining。
"""
import logging
from collections import defaultdict
from typing import Iterable

import pandas as pd

from techtrend.prediction.lifecycle import s_curve_stage, s_curve_stages

log = logging.getLogger(__name__)

CITATION_RELATION = "cited_by"


# ---------------------------------------------------------------------------
# 前向引用事实流（P1-2 引用时序的原料）
# ---------------------------------------------------------------------------
def forward_fact(
    e: dict,
    min_time: str | None = None,
    max_time: str | None = None,
) -> dict | None:
    """单个后向引用对 {"citing","citing_date","cited","cited_date"} → 前向事实 dict。

    返回 {"head": cited, "relation": "cited_by", "tail": citing, "time": citing_date,
    "head_date": cited_date, "source": "patent_citation"}；应跳过时返回 None
    （缺端点、自引、无时间、或时间越界）。
    """
    cited = e.get("cited")
    citing = e.get("citing")
    if not cited or not citing or cited == citing:
        return None
    time = (e.get("citing_date") or "") or (e.get("cited_date") or "")
    if not time:
        return None
    if min_time is not None and time < min_time:
        return None
    if max_time is not None and time > max_time:
        return None
    return {
        "head": cited,
        "relation": CITATION_RELATION,
        "tail": citing,
        "time": time,
        "head_date": e.get("cited_date") or "",
        "source": "patent_citation",
    }


def build_forward_citation_edges(
    backward_edges: Iterable[dict],
    min_time: str | None = None,
    max_time: str | None = None,
) -> list[dict]:
    """后向引用对 → 前向引用事实流。

    后向对 {"citing","citing_date","cited","cited_date"} → 前向事实
    {"head": cited, "relation": "cited_by", "tail": citing, "time": citing_date,
     "head_date": cited_date, "source": "patent_citation"}。

    - time 取 citing_date（引用发生时刻）；缺失时用 cited_date 兜底（非精确但可排序）。
    - min_time/max_time 过滤 time 边界（如 max_time=今天 滤未来坏数据）。
    """
    facts: list[dict] = []
    n_input = 0
    for e in backward_edges:
        n_input += 1
        f = forward_fact(e, min_time=min_time, max_time=max_time)
        if f is not None:
            facts.append(f)
    log.info(
        "build_forward_citation_edges：%d 条后向对 → %d 条前向引用事实", n_input, len(facts)
    )
    return facts


# ---------------------------------------------------------------------------
# 累积前向引用时序（P1-2：目标③真值 + 目标④ S 曲线）
# ---------------------------------------------------------------------------
def _sample_patents(
    totals: dict[str, int],
    eligible: set[str],
    sampling: str,
    n_bins: int,
    per_bin: int,
    max_patents: int,
) -> set[str]:
    """在 eligible（已过 min_citations 滤噪）上选样，返回保留的专利 ID 集合。

    - stratified：按 log10(总被引+1) 等宽分 n_bins 箱，每箱按总被引降序取 per_bin 个，
      低被引箱也保底覆盖（修正「top-N 总被引」系统性排除 emerging/growth 的选样偏）。
    - top_total：旧行为，总被引 top-max_patents。
    """
    if not eligible:
        return set()
    if sampling == "stratified":
        import math

        buckets: list[list[str]] = [[] for _ in range(n_bins)]
        log_vals = {p: math.log10(totals[p] + 1) for p in eligible}
        lo, hi = min(log_vals.values()), max(log_vals.values())
        width = (hi - lo) / n_bins if hi > lo else 1.0
        for p, lv in log_vals.items():
            idx = min(n_bins - 1, int((lv - lo) / width))
            buckets[idx].append(p)
        kept: set[str] = set()
        for bucket in buckets:
            bucket.sort(key=lambda p: (-totals[p], p))
            kept.update(bucket[:per_bin])
        return kept
    # top_total（旧行为，保留对照）
    return set(sorted(eligible, key=lambda p: (-totals[p], p))[:max_patents])


def build_patent_citation_monthly(
    facts: Iterable[dict],
    mode: str = "month",
    min_citations: int = 2,
    max_patents: int = 5000,
    sampling: str = "stratified",
    n_bins: int = 5,
    per_bin: int = 2000,
) -> pd.DataFrame:
    """前向引用事实流 → patent × 时间箱 累积被引矩阵。

    每个事实 = 一次「Y 在 time 被引用」事件；对每个被引专利 Y，按时间箱累计引用次数。
    index=被引专利 ID，columns=升序时间箱，值=截至该箱的累积被引次数（单调不减）。

    min_citations：只保留总被引 ≥ N 的专利（滤掉只被引 1 次的噪声，S 曲线需足够数据点）。
    sampling：选样策略（承 P6_PLAN §6.2 / P4_P3_RESULT §5）——
      "stratified"（分层，默认）让低被引箱也保底覆盖、全谱阶段可观测；"top_total" 旧行为。
    max_patents：仅 "top_total" 模式生效（stratified 的上限为 n_bins × per_bin）。
    """
    def _bin(t: str) -> str:
        if not t:
            return ""
        return t[:10] if mode == "day" else t[:7]

    cited_bins: dict[str, list[str]] = defaultdict(list)
    for f in facts:
        h = f.get("head")
        time = f.get("time") or ""
        if not h or not time:
            continue
        b = _bin(time)
        if b:
            cited_bins[h].append(b)

    if not cited_bins:
        return pd.DataFrame()

    # 选样：先按 min_citations 滤噪声，再分层（stratified）或 top-N（top_total）
    totals = {p: len(bins) for p, bins in cited_bins.items()}
    eligible = {p for p, c in totals.items() if c >= min_citations}
    kept = _sample_patents(totals, eligible, sampling, n_bins, per_bin, max_patents)

    # 累积计数
    rows: dict[str, dict[str, int]] = {}
    for p in kept:
        cum: dict[str, int] = {}
        for b in sorted(cited_bins[p]):
            cum[b] = cum.get(b, 0) + 1
        # 转累积
        acc = 0
        series: dict[str, int] = {}
        for b in sorted(cum):
            acc += cum[b]
            series[b] = acc
        rows[p] = series

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame.from_dict(rows, orient="index")
    return df.reindex(sorted(df.columns), axis=1).ffill(axis=1).fillna(0)


# S 曲线阶段分类（目标④）已泛化到 prediction/lifecycle.py（P6），
# `s_curve_stage` / `s_curve_stages` 于文件顶部 re-export 保持向后兼容。
