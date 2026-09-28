"""周报生成（P6）：聚合最近 N 天 run_manifest + 最新四目标指标 → output/weekly_report.md。

只读 output/ 下的小文件（run_manifest.jsonl / eval_metrics.json / citation_metrics.json /
fusion_ranking.csv / burst_concepts.csv），不跑任何重计算。`cron.py --mode weekly` 与
VisualizeStage 周边界触发都调用这里。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from techtrend.config import Settings
from techtrend.io import read_jsonl

log = logging.getLogger(__name__)


def _fmt(v) -> str:
    return "—" if v is None else f"{v:.4f}"


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 —— 缺文件/坏 JSON 都当作无数据
        return {}


def _read_csv_col(path: Path, col: str, limit: int = 10) -> list[str]:
    try:
        import pandas as pd

        df = pd.read_csv(path, encoding="utf-8-sig")
        return [str(v) for v in df[col].head(limit).tolist()]
    except Exception:  # noqa: BLE001
        return []


def build_weekly_report(settings: Settings) -> dict:
    """生成周报，返回 {"status","report_file","window_days","n_runs"}。"""
    out_dir = settings.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    since = datetime.now() - timedelta(days=settings.weekly_window_days)
    manifest_path = Path(settings.run_manifest_file)
    runs = read_jsonl(manifest_path)
    recent = [
        r for r in runs
        if r.get("started_at", "") >= since.isoformat(timespec="seconds")
    ]

    # ---- 各源新增聚合 ----
    source_totals: dict[str, int] = {}
    n_ok = n_noop = n_error = 0
    for r in recent:
        status = r.get("status", "error")
        if r.get("noop"):
            n_noop += 1
        elif status == "ok":
            n_ok += 1
        else:
            n_error += 1
        for src, cnt in (r.get("new_records") or {}).items():
            if isinstance(cnt, int) and not isinstance(cnt, bool):
                source_totals[src] = source_totals.get(src, 0) + cnt

    # ---- 四目标快照（最近一次评测） ----
    eval_m = _read_json(out_dir / "eval_metrics.json")
    cite_m = _read_json(out_dir / "citation_metrics.json")
    fusion_top = _read_csv_col(out_dir / "fusion_ranking.csv", "name")
    burst_top = _read_csv_col(out_dir / "burst_concepts.csv", "concept_name")

    lines = [
        "# 技术趋势预测周报",
        "",
        f"- 窗口：最近 {settings.weekly_window_days} 天（截至 {datetime.now().strftime('%Y-%m-%d %H:%M')}）",
        f"- 运行：{len(recent)} 次（ok {n_ok} / no-op {n_noop} / error {n_error}）",
        "",
        "## 各源新增记录",
        "",
    ]
    if source_totals:
        lines.append("| 来源 | 新增 |")
        lines.append("|---|---|")
        for src, cnt in sorted(source_totals.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {src} | {cnt} |")
    else:
        lines.append("（窗口内无新增记录）")
    lines += [
        "",
        "## 四目标快照（最近一次 evaluate）",
        "",
        "| 目标 | 指标 | 值 |",
        "|---|---|---|",
        f"| ① 新兴技术识别 | precision@k（融合） | {_fmt(eval_m.get('p_at_k_mean'))} |",
        f"| ② 时序链接预测 | CyGNet MRR / RotatE MRR | {_fmt(eval_m.get('tkg_mrr_mean'))} / {_fmt(eval_m.get('rotate_mrr_mean'))} |",
        f"| ③ 指标时序回归 | 活动代理 RMSE / 引用 RMSE | {_fmt(eval_m.get('rmse_mean'))} / {_fmt(cite_m.get('rmse'))} |",
        f"| ④ S 曲线 | 阶段分布 | {cite_m.get('s_curve_dist') or '—'} |",
        "",
    ]
    if fusion_top:
        lines += ["## 融合 Top 概念（目标①）", ""]
        lines += [f"- {n}" for n in fusion_top if n]
        lines += [""]
    if burst_top:
        lines += ["## 突发概念（Kleinberg）", ""]
        lines += [f"- {n}" for n in burst_top if n]
        lines += [""]

    lines += ["> 阶段标签为启发式（非监督真值）；详见 output/eval_report.md。"]

    report_file = Path(settings.weekly_report_file)
    if not report_file.is_absolute() and report_file.parent == Path("."):
        report_file = out_dir / report_file.name
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text("\n".join(lines), encoding="utf-8")
    log.info("周报完成：%s（%d 次运行，窗口 %d 天）", report_file, len(recent), settings.weekly_window_days)
    return {
        "status": "ok",
        "report_file": str(report_file),
        "window_days": settings.weekly_window_days,
        "n_runs": len(recent),
    }


__all__ = ["build_weekly_report"]
