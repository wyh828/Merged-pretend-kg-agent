"""SVG 原语（P6）：纯函数、零依赖，输入 list 数据、输出 SVG 字符串。

颜色全部走 CSS 变量（`--series-*` / `--stage-*` / `--text-*` / `--gridline` 等），
由 [dashboard.py](techtrend/viz/dashboard.py) 的 `<style>` 定义 light/dark 两套值
（承 dataviz skill 参考色板：品牌中性、可替换、明暗分选），因此本模块不硬编码 hex。

规格（承 dataviz skill marks-and-anatomy）：折线 2px 圆头、末端圆点 r=4 带 2px 表面环、
坐标轴 1px 实线（不虚线）、网格线 recessed、文本用 text 色而非系列色。
"""
from __future__ import annotations

import math
from typing import Callable, Sequence

# 几何常量
_LEFT = 56
_RIGHT = 20
_TOP = 30
_BOTTOM = 44
_FONT = "system-ui, -apple-system, 'Segoe UI', sans-serif"


def _esc(s) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def color(role: str) -> str:
    """CSS 变量引用（theme-aware）。"""
    return f"var(--{role})"


def nice_ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    """整洁刻度（1 / 2 / 5 × 10^k），用于 y 轴。"""
    if hi <= lo:
        return [lo]
    span = hi - lo
    step = 10 ** math.floor(math.log10(span / n))
    err = span / n / step
    if err >= 7.5:
        step *= 10
    elif err >= 3.5:
        step *= 5
    elif err >= 1.5:
        step *= 2
    ticks: list[float] = []
    v = math.floor(lo / step) * step
    while v <= hi + 1e-9:
        if v >= lo - 1e-9:
            ticks.append(v)
        v += step
    return ticks


def _fmt(v: float, yfmt: Callable[[float], str] | None) -> str:
    if yfmt is not None:
        return yfmt(v)
    if v == int(v):
        return f"{int(v)}"
    return f"{v:.4g}"


def _legend(labels: Sequence[str], roles: Sequence[str], width: int) -> str:
    """顶部图例（≥2 序列必带图例；文本用 text-secondary，不穿系列色）。"""
    parts: list[str] = []
    x = _LEFT
    for i, lbl in enumerate(labels):
        role = roles[i] if i < len(roles) else f"series-{i+1}"
        parts.append(
            f'<rect x="{x}" y="13" width="10" height="10" rx="2" fill="{color(role)}"/>'
        )
        parts.append(
            f'<text x="{x + 15}" y="22" font-family="{_FONT}" font-size="11" '
            f'fill="{color("text-secondary")}">{_esc(lbl)}</text>'
        )
        x += 15 + 8 + len(str(lbl)) * 6.4 + 22
        if x > width - _RIGHT - 40:
            break
    return "".join(parts)


def line_chart(
    series: Sequence[tuple[str, Sequence[float]]],
    xlabels: Sequence[str],
    title: str = "",
    width: int = 760,
    height: int = 340,
    yfmt: Callable[[float], str] | None = None,
    roles: Sequence[str] | None = None,
) -> str:
    """多序列折线图（趋势 / walk-forward 折线）。series = [(label, values), ...]。

    values 与 xlabels 等长；roles 为每个序列的 CSS 变量 role（默认 series-1..N）。
    """
    n = len(xlabels)
    if n == 0:
        return ""
    plot_w = width - _LEFT - _RIGHT
    plot_h = height - _TOP - _BOTTOM
    ys = [v for _, vals in series for v in vals if v is not None and math.isfinite(v)]
    ymin = min(0.0, min(ys)) if ys else 0.0
    ymax = max(ys) if ys else 1.0
    if ymax <= ymin:
        ymax = ymin + 1.0
    ymax = ymax + (ymax - ymin) * 0.06

    def X(i: int) -> float:
        return _LEFT + (i / (n - 1)) * plot_w if n > 1 else _LEFT + plot_w / 2

    def Y(v: float) -> float:
        return _TOP + (1 - (v - ymin) / (ymax - ymin)) * plot_h

    p = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
        f'aria-label="{_esc(title)}" style="max-width:100%">',
        f'<text x="{_LEFT}" y="{_TOP - 10}" font-family="{_FONT}" font-size="13" '
        f'font-weight="600" fill="{color("text-primary")}">{_esc(title)}</text>',
    ]
    # 网格 + y 刻度（recessive）
    for t in nice_ticks(ymin, ymax):
        yy = Y(t)
        p.append(
            f'<line x1="{_LEFT}" y1="{yy:.1f}" x2="{width - _RIGHT}" y2="{yy:.1f}" '
            f'stroke="{color("gridline")}" stroke-width="1"/>'
        )
        p.append(
            f'<text x="{_LEFT - 8}" y="{yy + 4:.1f}" font-family="{_FONT}" font-size="10.5" '
            f'fill="{color("text-muted")}" text-anchor="end" '
            f'style="font-variant-numeric:tabular-nums">{_esc(_fmt(t, yfmt))}</text>'
        )
    # 基线
    p.append(
        f'<line x1="{_LEFT}" y1="{Y(ymin):.1f}" x2="{width - _RIGHT}" y2="{Y(ymin):.1f}" '
        f'stroke="{color("baseline")}" stroke-width="1"/>'
    )
    # x 轴标签（抽稀防拥挤）
    step = max(1, math.ceil(n / 12))
    for i in range(0, n, step):
        p.append(
            f'<text x="{X(i):.1f}" y="{height - _BOTTOM + 20}" font-family="{_FONT}" '
            f'font-size="10.5" fill="{color("text-muted")}" text-anchor="middle" '
            f'style="font-variant-numeric:tabular-nums">{_esc(xlabels[i])}</text>'
        )
    # 序列折线 + 末端圆点
    roles = list(roles) if roles else [f"series-{i+1}" for i in range(len(series))]
    for k, (label, vals) in enumerate(series):
        role = roles[k] if k < len(roles) else f"series-{k+1}"
        segments = []
        points = []
        valid = []
        for i, v in enumerate(vals):
            if v is None or not math.isfinite(v):
                if points:
                    segments.append(points)
                    points = []
                continue
            points.append(f"{X(i):.1f},{Y(v):.1f}")
            valid.append((i, v))
        if points:
            segments.append(points)
        for segment in segments:
            pts = " ".join(segment)
            p.append(
                f'<polyline points="{pts}" fill="none" stroke="{color(role)}" stroke-width="2" '
                f'stroke-linecap="round" stroke-linejoin="round"/>'
            )
        if not valid:
            continue
        li, last = valid[-1]
        p.append(
            f'<circle cx="{X(li):.1f}" cy="{Y(last):.1f}" r="4" fill="{color(role)}" '
            f'stroke="{color("surface-1")}" stroke-width="2"/>'
        )
    p.append(_legend([lbl for lbl, _ in series], roles, width))
    p.append("</svg>")
    return "".join(p)


def hbar_chart(
    items: Sequence[tuple[str, float]],
    title: str = "",
    width: int = 760,
    height: int | None = None,
    yfmt: Callable[[float], str] | None = None,
    role: str = "series-1",
) -> str:
    """横向条形图（融合 top-k 榜单）。单色（长度编码量级），label 直接标注在条端。"""
    n = len(items)
    if n == 0:
        return ""
    height = height or max(200, n * 30 + _TOP + _BOTTOM)
    bar_h = 18
    gap = 12
    plot_h = height - _TOP - _BOTTOM
    vmax = max((v for _, v in items), default=1.0) or 1.0
    label_w = 190
    plot_w = width - _LEFT - label_w - _RIGHT

    def Y(i: int) -> float:
        return _TOP + i * (bar_h + gap) + bar_h / 2

    p = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="{_esc(title)}">',
        f'<text x="{_LEFT}" y="{_TOP - 10}" font-family="{_FONT}" font-size="13" '
        f'font-weight="600" fill="{color("text-primary")}">{_esc(title)}</text>',
    ]
    for i, (label, v) in enumerate(items):
        yy = Y(i)
        w = max(2.0, (v / vmax) * plot_w)
        p.append(
            f'<text x="{label_w}" y="{yy + 4:.1f}" font-family="{_FONT}" font-size="11.5" '
            f'fill="{color("text-secondary")}" text-anchor="end">{_esc(str(label)[:34])}</text>'
        )
        p.append(
            f'<rect x="{label_w + 8}" y="{yy - bar_h / 2:.1f}" width="{w:.1f}" height="{bar_h}" '
            f'rx="4" fill="{color(role)}"/>'
        )
        p.append(
            f'<text x="{label_w + 8 + w + 6:.1f}" y="{yy + 4:.1f}" font-family="{_FONT}" '
            f'font-size="11" fill="{color("text-secondary")}" '
            f'style="font-variant-numeric:tabular-nums">{_esc(_fmt(v, yfmt))}</text>'
        )
    p.append("</svg>")
    return "".join(p)


def col_chart(
    items: Sequence[tuple[str, float, str]],
    title: str = "",
    width: int = 760,
    height: int = 300,
    yfmt: Callable[[float], str] | None = None,
) -> str:
    """竖向柱状图（阶段分布）。items = [(label, value, css_role), ...]。

    柱宽 ≤24px、顶端圆角、基线下接底；柱端直接标数值。
    """
    n = len(items)
    if n == 0:
        return ""
    plot_w = width - _LEFT - _RIGHT
    plot_h = height - _TOP - _BOTTOM
    vmax = max((v for _, v, _ in items), default=1.0) or 1.0
    slot = plot_w / n
    bar_w = min(24.0, slot * 0.62)

    def X(i: int) -> float:
        return _LEFT + slot * (i + 0.5)

    def Y(v: float) -> float:
        return _TOP + (1 - v / vmax) * plot_h

    p = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="{_esc(title)}">',
        f'<text x="{_LEFT}" y="{_TOP - 10}" font-family="{_FONT}" font-size="13" '
        f'font-weight="600" fill="{color("text-primary")}">{_esc(title)}</text>',
    ]
    # 网格 + y 刻度
    for t in nice_ticks(0, vmax):
        yy = Y(t)
        p.append(
            f'<line x1="{_LEFT}" y1="{yy:.1f}" x2="{width - _RIGHT}" y2="{yy:.1f}" '
            f'stroke="{color("gridline")}" stroke-width="1"/>'
        )
        p.append(
            f'<text x="{_LEFT - 8}" y="{yy + 4:.1f}" font-family="{_FONT}" font-size="10.5" '
            f'fill="{color("text-muted")}" text-anchor="end" '
            f'style="font-variant-numeric:tabular-nums">{_esc(_fmt(t, yfmt))}</text>'
        )
    p.append(
        f'<line x1="{_LEFT}" y1="{Y(0):.1f}" x2="{width - _RIGHT}" y2="{Y(0):.1f}" '
        f'stroke="{color("baseline")}" stroke-width="1"/>'
    )
    for i, (label, v, role) in enumerate(items):
        cx = X(i)
        top = Y(v)
        base = Y(0)
        p.append(
            f'<rect x="{cx - bar_w / 2:.1f}" y="{top:.1f}" width="{bar_w:.1f}" '
            f'height="{base - top:.1f}" rx="4" fill="{color(role)}"/>'
        )
        p.append(
            f'<text x="{cx:.1f}" y="{top - 6:.1f}" font-family="{_FONT}" font-size="11" '
            f'font-weight="600" fill="{color("text-primary")}" text-anchor="middle" '
            f'style="font-variant-numeric:tabular-nums">{_esc(_fmt(v, yfmt))}</text>'
        )
        p.append(
            f'<text x="{cx:.1f}" y="{height - _BOTTOM + 20}" font-family="{_FONT}" '
            f'font-size="11.5" fill="{color("text-secondary")}" '
            f'text-anchor="middle">{_esc(label)}</text>'
        )
    p.append("</svg>")
    return "".join(p)


__all__ = ["color", "line_chart", "hbar_chart", "col_chart", "nice_ticks"]
