"""各图 SVG（P6）：把数据 DataFrame/Series 转成图（对应四目标）。

- 目标① 融合榜单（横向条）+ 突发热点
- 目标② walk-forward 每折 MRR 折线（CyGNet / copy-only / RotatE）
- 目标③ 概念趋势折线 + 预测值标注（forecast vs actual 散点）
- 目标④ S 曲线各阶段归一化累积曲线叠加 + 阶段分布柱状

全部只读 pandas 数据、输出 SVG 字符串；颜色走 [svg.py](techtrend/viz/svg.py) 的 CSS 变量。
"""
from __future__ import annotations

from typing import Mapping, Sequence

import pandas as pd

from techtrend.prediction.lifecycle import STAGES
from techtrend.viz.svg import color, col_chart, hbar_chart, line_chart

# 折线图系列数上限 6（dataviz skill 系列数阶梯：>7 折成表格/小倍数）；
# trend_top_svg 由调用方按 min(top_k, 6) 传入，避免 20 条线挤成一团。
_LEFT, _RIGHT, _TOP, _BOTTOM = 56, 20, 30, 44
_FONT = "system-ui, -apple-system, 'Segoe UI', sans-serif"


def trend_top_svg(
    monthly: pd.DataFrame,
    top_k: int = 6,
    names: Mapping[str, str] | None = None,
) -> str:
    """目标③：top-k 概念月度活动量趋势折线。"""
    if monthly.empty:
        return ""
    names = names or {}
    totals = monthly.sum(axis=1)
    top = totals.sort_values(ascending=False).head(top_k).index
    series: list[tuple[str, list[float]]] = []
    for c in top:
        label = names.get(str(c), str(c))
        series.append((label, monthly.loc[c].to_numpy(dtype=float).tolist()))
    roles = [f"series-{i+1}" for i in range(len(series))]
    return line_chart(
        series, [str(x) for x in monthly.columns],
        title=f"目标③ 概念月度活动量（top {len(series)}）",
        roles=roles,
    )


def s_curve_overlay_svg(curves: pd.DataFrame) -> str:
    """目标④：每个阶段一条「归一化累积」均值曲线（形状对比）。

    `curves`：index=阶段（emerging/growth/mature/declining），columns=时间箱，
    值∈[0,1]，由 [lifecycle.py](techtrend/prediction/lifecycle.py) `mean_stage_curves` 产出
    （专利级由 evaluate 持久化为 s_curve_curves.csv；概念级由 visualize 实时聚合）。
    """
    if curves.empty:
        return ""
    series: list[tuple[str, list[float]]] = []
    roles: list[str] = []
    for st in curves.index:
        series.append((str(st), curves.loc[st].to_numpy(dtype=float).tolist()))
        roles.append(f"stage-{st}")
    return line_chart(
        series, [str(x) for x in curves.columns],
        title="目标④ S 曲线各阶段归一化累积曲线（形状）",
        yfmt=lambda v: f"{v:.2f}", roles=roles,
    )


def stage_dist_svg(dist: Mapping[str, int]) -> str:
    """目标④：阶段分布柱状。"""
    items = [(st, int(dist.get(st, 0)), f"stage-{st}") for st in STAGES if st in dist]
    if not items:
        return ""
    return col_chart(items, title="目标④ S 曲线阶段分布（实体数）")


def walkforward_folds_svg(folds: Sequence[dict]) -> str:
    """目标②：walk-forward 每折 filtered MRR（CyGNet / copy-only / RotatE）。"""
    folds = [f for f in folds if f.get("tkg_mrr") is not None]
    if not folds:
        return ""
    xlabels = [
        f"{f.get('train_end', '')}→{f.get('test_start', '')}" for f in folds
    ]
    series = [
        ("CyGNet", [f.get("tkg_mrr") for f in folds]),
        ("copy-only", [f.get("copyonly_mrr") for f in folds]),
        ("RotatE", [f.get("rotate_mrr") for f in folds]),
    ]
    return line_chart(
        series, xlabels,
        title="目标② walk-forward 每折 filtered MRR",
        yfmt=lambda v: f"{v:.3f}", roles=["series-1", "series-2", "series-3"],
    )


def fusion_rank_svg(ranking: pd.DataFrame, top_k: int = 10) -> str:
    """目标①：融合 top-k 得分横向条（单色，长度编码量级）。"""
    if ranking is None or ranking.empty:
        return ""
    df = ranking.head(top_k)
    items = [
        (row.get("name") or str(row.get("entity")), float(row.get("score") or 0.0))
        for _, row in df.iterrows()
    ]
    return hbar_chart(items, title=f"目标① 融合 Top-{len(items)} 得分", yfmt=lambda v: f"{v:.3f}")


def forecast_svg(forecasts: pd.DataFrame, top_k: int = 40) -> str:
    """目标③：actual vs forecast 散点（对角参考线显式标注系统性高估）。"""
    if forecasts is None or forecasts.empty:
        return ""
    df = forecasts.head(top_k)
    actual = df["actual"].astype(float).to_numpy()
    pred = df["forecast"].astype(float).to_numpy()
    vmax = max(float(actual.max()), float(pred.max()), 1e-6) * 1.1
    width, height = 760, 320
    plot_w = width - _LEFT - _RIGHT
    plot_h = height - _TOP - _BOTTOM

    def X(v: float) -> float:
        return _LEFT + v / vmax * plot_w

    def Y(v: float) -> float:
        return _TOP + (1 - v / vmax) * plot_h

    p = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
        f'aria-label="目标③ 预测 vs 实际" style="max-width:100%">',
        f'<text x="{_LEFT}" y="{_TOP - 10}" font-family="{_FONT}" font-size="13" '
        f'font-weight="600" fill="{color("text-primary")}">目标③ 预测值 vs 实际值</text>',
    ]
    for t in [v for v in (0.0, vmax / 2, vmax)]:
        p.append(
            f'<line x1="{_LEFT}" y1="{Y(t):.1f}" x2="{width - _RIGHT}" y2="{Y(t):.1f}" '
            f'stroke="{color("gridline")}" stroke-width="1"/>'
        )
        p.append(
            f'<text x="{_LEFT - 8}" y="{Y(t) + 4:.1f}" font-family="{_FONT}" font-size="10.5" '
            f'fill="{color("text-muted")}" text-anchor="end">{t:.4g}</text>'
        )
    # 对角参考线 y=x
    p.append(
        f'<line x1="{X(0):.1f}" y1="{Y(0):.1f}" x2="{X(vmax):.1f}" y2="{Y(vmax):.1f}" '
        f'stroke="{color("baseline")}" stroke-width="1"/>'
    )
    # 点（单序列，标题即命名，无图例框）
    for a, pv in zip(actual, pred):
        p.append(
            f'<circle cx="{X(a):.1f}" cy="{Y(pv):.1f}" r="4" fill="{color("series-1")}" '
            f'fill-opacity="0.7" stroke="{color("surface-1")}" stroke-width="1.5"/>'
        )
    p.append(
        f'<text x="{_LEFT}" y="{height - _BOTTOM + 20}" font-family="{_FONT}" font-size="11" '
        f'fill="{color("text-muted")}">x = 实际活动量，y = 模型预测（对角虚线为 y=x，点上偏 = 高估）</text>'
    )
    p.append("</svg>")
    return "".join(p)


__all__ = [
    "trend_top_svg",
    "s_curve_overlay_svg",
    "stage_dist_svg",
    "walkforward_folds_svg",
    "fusion_rank_svg",
    "forecast_svg",
]
