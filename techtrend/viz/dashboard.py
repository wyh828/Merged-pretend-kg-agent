"""自包含 HTML Dashboard 装配（P6）：把各图 SVG + 指标拼成一个离线可开的 dashboard.html。

零新依赖、零外部资源：CSS 变量 + prefers-color-scheme + data-theme 实现明暗主题，
SVG 颜色引用 CSS 变量（`--series-*` / `--stage-*` / `--text-*`），主题切换即换色。
所有输入都是已渲染好的 SVG 字符串（见 [charts.py](techtrend/viz/charts.py)），
本模块只负责 HTML 骨架、排版、主题与交互，不 import pandas / torch / pykeen。

明暗色板承 dataviz skill 参考色板（品牌中性、CVD 安全、固定顺序）：
- 系列色（Okabe-Ito 去黄/黑，固定顺序）：蓝 → 橙 → 绿 → 朱 → 紫 → 天蓝
- 阶段色（S 曲线四阶段，固定顺序）：emerging → growth → mature → declining
"""
from __future__ import annotations

from typing import Sequence

_LIGHT = {
    "surface-1": "#f7f7f8",
    "surface-2": "#ffffff",
    "text-primary": "#1a1a1a",
    "text-secondary": "#55565a",
    "text-muted": "#8a8b90",
    "gridline": "#e4e4e7",
    "baseline": "#c9c9cf",
    "border": "#e0e0e3",
    "accent": "#0072b2",
    "series-1": "#0072b2",
    "series-2": "#e69f00",
    "series-3": "#009e73",
    "series-4": "#d55e00",
    "series-5": "#cc79a7",
    "series-6": "#56b4e9",
    "stage-emerging": "#56b4e9",
    "stage-growth": "#009e73",
    "stage-mature": "#e69f00",
    "stage-declining": "#d55e00",
}
_DARK = {
    "surface-1": "#1c1c1e",
    "surface-2": "#242426",
    "text-primary": "#ececee",
    "text-secondary": "#b0b0b5",
    "text-muted": "#7d7d83",
    "gridline": "#353538",
    "baseline": "#4a4a4e",
    "border": "#3a3a3e",
    "accent": "#56b4e9",
    "series-1": "#56b4e9",
    "series-2": "#f0b429",
    "series-3": "#2bb48a",
    "series-4": "#e57324",
    "series-5": "#d18bb0",
    "series-6": "#7fc4e8",
    "stage-emerging": "#7fc4e8",
    "stage-growth": "#2bb48a",
    "stage-mature": "#f0b429",
    "stage-declining": "#e57324",
}


def _esc(s) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _tokens(vars_: dict) -> str:
    return "\n".join(f"  --{k}: {v};" for k, v in vars_.items())


def _css() -> str:
    light = _tokens(_LIGHT)
    dark = _tokens(_DARK)
    return f"""*{{box-sizing:border-box}}
:root{{
  color-scheme:light;
{light}
  font-family:system-ui,-apple-system,'Segoe UI',sans-serif;
}}
@media (prefers-color-scheme: dark){{
  :root:not([data-theme="light"]){{
    color-scheme:dark;
{dark}
  }}
}}
:root[data-theme="dark"]{{
  color-scheme:dark;
{dark}
}}
body{{
  margin:0;
  background:var(--surface-1);
  color:var(--text-primary);
  padding:24px 20px 40px;
  line-height:1.5;
}}
.wrap{{max-width:1080px;margin:0 auto}}
header{{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap;margin-bottom:8px}}
h1{{font-size:20px;margin:0;font-weight:650}}
.sub{{color:var(--text-muted);font-size:12.5px;margin-top:4px}}
button#theme-toggle{{
  background:var(--surface-2);color:var(--text-secondary);
  border:1px solid var(--border);border-radius:8px;padding:6px 12px;
  font-size:12.5px;cursor:pointer;
}}
.hero{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px;margin:18px 0 22px}}
.tile{{
  background:var(--surface-2);border:1px solid var(--border);border-radius:12px;
  padding:16px;
}}
.tile .k{{font-size:12px;color:var(--text-muted);margin-bottom:8px}}
.tile .v{{font-size:26px;font-weight:650;font-variant-numeric:tabular-nums}}
.tile .s{{font-size:12px;color:var(--text-secondary);margin-top:6px}}
.grid{{display:grid;grid-template-columns:1fr;gap:18px}}
.card{{
  background:var(--surface-2);border:1px solid var(--border);border-radius:12px;
  padding:16px 16px 8px;overflow:hidden;
}}
.card h2{{font-size:15px;margin:0 0 4px;font-weight:600}}
.card p.note{{font-size:12px;color:var(--text-muted);margin:0 0 10px}}
.card .svg{{overflow-x:auto}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
@media (max-width:760px){{.two{{grid-template-columns:1fr}}}}
table{{border-collapse:collapse;width:100%;font-size:12.5px;margin-top:8px}}
th,td{{text-align:left;padding:6px 10px;border-bottom:1px solid var(--border);font-variant-numeric:tabular-nums}}
th{{color:var(--text-secondary);font-weight:600}}
section.notes{{margin-top:22px;font-size:12.5px;color:var(--text-secondary)}}
section.notes li{{margin:3px 0}}
footer{{margin-top:22px;color:var(--text-muted);font-size:11.5px}}
"""


def _hero_tiles(heroes: Sequence[dict]) -> str:
    parts = []
    for h in heroes:
        label = _esc(h.get("label", ""))
        value = _esc(h.get("value", ""))
        sub = _esc(h.get("sub", ""))
        parts.append(
            f'<div class="tile"><div class="k">{label}</div>'
            f'<div class="v">{value}</div><div class="s">{sub}</div></div>'
        )
    return "".join(parts)


def _chart_cards(charts: Sequence[dict]) -> str:
    parts = []
    for c in charts:
        title = _esc(c.get("title", ""))
        svg = c.get("svg", "") or ""
        note = _esc(c.get("note", ""))
        note_html = f'<p class="note">{note}</p>' if note else ""
        parts.append(
            f'<div class="card"><h2>{title}</h2>{note_html}'
            f'<div class="svg">{svg}</div></div>'
        )
    return "".join(parts)


def _tables(tables: Sequence[dict] | None) -> str:
    if not tables:
        return ""
    parts = []
    for t in tables:
        title = _esc(t.get("title", ""))
        cols = t.get("columns", [])
        rows = t.get("rows", [])
        head = "".join(f"<th>{_esc(c)}</th>" for c in cols)
        body = []
        for row in rows:
            cells = "".join(f"<td>{_esc(row[i] if i < len(row) else '')}</td>" for i in range(len(cols)))
            body.append(f"<tr>{cells}</tr>")
        parts.append(
            f'<div class="card"><h2>{title}</h2>'
            f'<div style="overflow-x:auto"><table><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div></div>'
        )
    return "".join(parts)


def render(
    *,
    heroes: Sequence[dict] | None = None,
    charts: Sequence[dict] | None = None,
    notes: Sequence[str] | None = None,
    tables: Sequence[dict] | None = None,
    generated_at: str = "",
    theme: str = "auto",
    title: str = "技术趋势预测 Dashboard",
) -> str:
    """装配完整 HTML 文档。heroes=[{label,value,sub}]；charts=[{title,svg,note}]（有序）。"""
    heroes = heroes or []
    charts = charts or []
    notes = notes or []
    html_attr = ""
    if theme in ("light", "dark"):
        html_attr = f' data-theme="{theme}"'
    notes_html = "".join(f"<li>{_esc(n)}</li>" for n in notes) if notes else ""
    notes_block = f'<section class="notes"><h2 style="font-size:15px;margin:0 0 6px">口径说明</h2><ul>{notes_html}</ul></section>' if notes_html else ""
    footer = f'<footer>生成于 {_esc(generated_at)} · 阶段标签为启发式（非监督真值）</footer>' if generated_at else ""
    return f"""<!doctype html>
<html lang="zh-CN"{html_attr}>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{_esc(title)}</title>
<style>{_css()}</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>{_esc(title)}</h1>
      <div class="sub">四目标：① 新兴技术识别 ② 时序链接预测 ③ 指标时序回归 ④ S 曲线生命周期</div>
    </div>
    <button id="theme-toggle" onclick="toggleTheme()">主题：{_esc(theme)}</button>
  </header>
  <div class="hero">{_hero_tiles(heroes)}</div>
  <div class="grid">{_chart_cards(charts)}</div>
  {_tables(tables)}
  {notes_block}
  {footer}
</div>
<script>
(function(){{
  var root=document.documentElement;
  var saved=null; try{{saved=localStorage.getItem('viz-theme');}}catch(e){{}}
  if((saved==='light'||saved==='dark')&&!root.getAttribute('data-theme'))root.setAttribute('data-theme',saved);
  window.toggleTheme=function(){{
    var cur=root.getAttribute('data-theme');
    var next=(cur==='dark')?'light':((cur==='light')?'auto':'dark');
    if(next==='auto')root.removeAttribute('data-theme');else root.setAttribute('data-theme',next);
    try{{localStorage.setItem('viz-theme',next==='auto'?'':next);}}catch(e){{}}
    var b=document.getElementById('theme-toggle');
    if(b)b.textContent='主题：'+next;
  }};
}})();
</script>
</body>
</html>
"""


__all__ = ["render"]
