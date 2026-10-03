"""可视化阶段（P6，第 9 阶段）：把 output/ 下的四目标产物渲染成自包含 dashboard.html。

零重算设计（承 P6_PLAN §7 与 PROJECT_PLAN 定稿）：
- 概念级（趋势 + 概念 S 曲线）：实时读 data/interim/works.jsonl（~12MB）算 monthly，
  不跑 RotatE/CyGNet。
- 专利级（S 曲线叠加 + 分布）：读 evaluate 持久化的 s_curve_curves.csv / s_curve_stages.csv，
  不重读 1.07GB patent_citations.jsonl。
- 榜单 / 回测 / 回归：直接读 fusion_ranking.csv / eval_folds.csv / forecast.csv。

输出：
- output/dashboard.html（自包含，离线可开，明暗主题）
- output/charts/*.svg（单图，便于单独复用）
- output/weekly_report.md（weekly_enable 时）
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from techtrend.stages.base import Stage
from techtrend.config import PROJECT_ROOT

log = logging.getLogger(__name__)


def _fmt(v) -> str:
    return "—" if v is None else f"{v:.4f}"


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _read_csv(path: Path, index_col: int | None = None):
    try:
        import pandas as pd

        return pd.read_csv(path, encoding="utf-8-sig", index_col=index_col)
    except Exception:  # noqa: BLE001
        import pandas as pd

        return pd.DataFrame()


class VisualizeStage(Stage):
    name = "visualize"

    def run(self) -> dict:
        s = self.settings
        if not s.viz_enable:
            return {"stage": self.name, "status": "skipped", "reason": "viz_enable=false"}

        try:
            from techtrend.io import read_jsonl
            from techtrend.prediction.kleinberg import (
                build_concept_monthly_counts,
                concept_names,
            )
            from techtrend.prediction.lifecycle import (
                concept_lifecycle_stages,
                mean_stage_curves,
            )
            from techtrend.viz import charts as C
            from techtrend.viz.dashboard import render
            from techtrend.viz.weekly import build_weekly_report

            out_dir = s.output_dir
            out_dir.mkdir(parents=True, exist_ok=True)
            dash_path = self._resolve(s.output_dir, s.viz_dashboard_file)
            charts_dir = self._resolve(s.output_dir, s.viz_charts_dir)
            charts_dir.mkdir(parents=True, exist_ok=True)

            charts: list[dict] = []
            heroes: list[dict] = []
            notes: list[str] = []

            # ---- 概念级（works.jsonl → monthly） ----
            works = read_jsonl(s.data_dir / "interim" / "works.jsonl")
            monthly = build_concept_monthly_counts(works, mode=s.burst_bin)
            names = concept_names(works)
            exclude = {c.strip() for c in s.openalex_concept_ids.split(",") if c.strip()}
            if not monthly.empty:
                monthly = monthly.drop(index=[c for c in exclude if c in monthly.index])

            if not monthly.empty and monthly.shape[1] >= 2:
                svg = C.trend_top_svg(monthly, top_k=min(s.viz_top_k, 6), names=names)
                if svg:
                    charts.append({
                        "title": "概念月度活动量趋势（目标③）",
                        "svg": svg,
                        "note": f"top {min(s.viz_top_k, 6)} 活跃概念（按总活动量），横轴 {s.burst_bin} 箱",
                    })
                cstages = concept_lifecycle_stages(
                    monthly, growth_window=s.lifecycle_growth_window,
                    emerging_quantile=s.lifecycle_emerging_quantile,
                    min_history=s.lifecycle_min_history,
                )
                cdist = cstages.value_counts().to_dict()
                csvg = C.stage_dist_svg(cdist)
                if csvg:
                    charts.append({
                        "title": "概念 S 曲线阶段分布（目标④）",
                        "svg": csvg,
                        "note": "概念级（累积活动量），阶段标签为启发式",
                    })
                ccurves = mean_stage_curves(monthly.cumsum(axis=1), cstages)
                cover = C.s_curve_overlay_svg(ccurves)
                if cover:
                    charts.append({
                        "title": "概念 S 曲线各阶段归一化累积曲线（目标④）",
                        "svg": cover,
                        "note": "每实体按终点归一化后阶段内求均值",
                    })
                # 概念级阶段分布作为目标④ hero
                heroes.append(self._s_curve_hero("概念级", cdist))

            # ---- 专利级（evaluate 持久化产物，零重算） ----
            citation_available = _read_json(out_dir / "citation_metrics.json").get("n_patents", 0) > 0
            pstages = _read_csv(out_dir / "s_curve_stages.csv") if citation_available else None
            if pstages is not None and not pstages.empty and "stage" in pstages.columns:
                pdist = pstages["stage"].value_counts().to_dict()
                pd_svg = C.stage_dist_svg(pdist)
                if pd_svg:
                    charts.append({
                        "title": "专利 S 曲线阶段分布（目标④）",
                        "svg": pd_svg,
                        "note": "专利级（前向引用累积，分层选样）",
                    })
                heroes.append(self._s_curve_hero("专利级", pdist))
            pcurves = _read_csv(out_dir / "s_curve_curves.csv", index_col=0) if citation_available else None
            if pcurves is not None and not pcurves.empty:
                po_svg = C.s_curve_overlay_svg(pcurves)
                if po_svg:
                    charts.append({
                        "title": "专利 S 曲线各阶段归一化累积曲线（目标④）",
                        "svg": po_svg,
                        "note": "专利前向引用累积；阶段分组为描述性结果",
                    })

            # ---- 融合榜单（目标①） ----
            fusion_df = _read_csv(out_dir / "fusion_ranking.csv")
            if not fusion_df.empty:
                fsvg = C.fusion_rank_svg(fusion_df, top_k=s.fusion_top_k)
                if fsvg:
                    charts.append({
                        "title": "融合 Top 榜单（目标①）",
                        "svg": fsvg,
                        "note": f"burst={s.fusion_weights}（三路信号秩归一加权）",
                    })

            # ---- walk-forward 每折 MRR（目标②） ----
            folds_df = _read_csv(out_dir / "eval_folds.csv")
            if not folds_df.empty:
                wsvg = C.walkforward_folds_svg(folds_df.to_dict("records"))
                if wsvg:
                    charts.append({
                        "title": "时序链接预测每折 MRR（目标②）",
                        "svg": wsvg,
                        "note": "CyGNet vs copy-only vs RotatE，filtered MRR",
                    })

            # ---- 预测 vs 实际（目标③） ----
            forecast_df = _read_csv(out_dir / "forecast.csv")
            if not forecast_df.empty:
                fcsv = C.forecast_svg(forecast_df)
                if fcsv:
                    charts.append({
                        "title": "指标时序回归：预测值 vs 实际值（目标③）",
                        "svg": fcsv,
                        "note": "对角参考线 y=x，点上偏 = 系统性高估",
                    })

            # ---- 四目标 hero + 口径 ----
            eval_m = _read_json(out_dir / "eval_metrics.json")
            cite_m = _read_json(out_dir / "citation_metrics.json")
            heroes = self._build_heroes(eval_m, cite_m) + heroes
            notes = self._build_notes(eval_m, cite_m)

            weekly: dict = {}
            if s.weekly_enable:
                weekly = build_weekly_report(s)
            reports = self._read_reports(out_dir, Path(s.weekly_report_file))
            tables = []
            if not fusion_df.empty:
                columns = list(fusion_df.columns)
                tables.append({"title": "融合榜单（已保存产物）", "columns": columns,
                               "rows": fusion_df.head(s.viz_top_k).fillna("—").values.tolist()})
            for filename, title in (("collab_consensus.json", "协同共识"), ("collab_conflicts.json", "协同冲突")):
                path = out_dir / filename
                if path.exists():
                    rows = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(rows, list) and rows:
                        columns = list(dict.fromkeys(k for r in rows if isinstance(r, dict) for k in r))
                        tables.append({"title": title, "columns": columns,
                                       "rows": [[r.get(k, "—") for k in columns] for r in rows[:s.viz_top_k] if isinstance(r, dict)]})
            if not charts:
                notes.append("当前没有可绘图的数据产物；请先采集数据并运行预测与评估。这里不展示模拟实验数字。")
            if not eval_m:
                notes.append("缺少 eval_metrics.json：本地回测尚未完成，指标和模型比较均未验证。")

            # ---- 渲染 + 写盘 ----
            from datetime import datetime

            html = render(
                heroes=heroes,
                charts=charts,
                notes=notes,
                tables=tables,
                reports=reports,
                generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                theme=s.viz_theme,
            )
            dash_path.parent.mkdir(parents=True, exist_ok=True)
            dash_path.write_text(html, encoding="utf-8")
            self._write_chart_files(charts_dir, charts)

            log.info(
                "visualize 完成：%s（%d 张图，hero %d 个，weekly=%s）",
                dash_path, len(charts), len(heroes), weekly.get("status", "skipped"),
            )
            return {
                "stage": self.name,
                "status": "ok",
                "dashboard_file": str(dash_path),
                "n_charts": len(charts),
                "n_reports": len(reports),
                "weekly": weekly,
            }
        except Exception as exc:  # noqa: BLE001
            log.exception("visualize 阶段失败")
            return {"stage": self.name, "status": "error", "error": str(exc)}

    # ------------------------------------------------------------------
    @staticmethod
    def _resolve(output_dir: Path, target: str) -> Path:
        """把配置里的相对路径解析为 Path：裸文件名归 output_dir，其余按 CWD 相对。"""
        p = Path(target)
        if not p.is_absolute() and p.parent == Path("."):
            return output_dir / p.name
        return p

    @staticmethod
    def _s_curve_hero(scope: str, dist: dict) -> dict:
        order = ("emerging", "growth", "mature", "declining")
        parts = " / ".join(str(dist.get(st, 0)) for st in order)
        return {
            "label": f"④ S 曲线阶段分布（{scope}）",
            "value": parts,
            "sub": "emerging / growth / mature / declining",
        }

    @staticmethod
    def _build_heroes(eval_m: dict, cite_m: dict) -> list[dict]:
        tkg = eval_m.get("tkg_mrr_mean")
        rotate = eval_m.get("rotate_mrr_mean")
        return [
            {
                "label": "① 新兴技术识别 precision@k",
                "value": _fmt(eval_m.get("p_at_k_mean")),
                "sub": "walk-forward 回测（相对份额动量；Kleinberg 为消融对照）",
            },
            {
                "label": "② 时序链接预测 CyGNet MRR",
                "value": _fmt(tkg),
                "sub": f"RotatE 对照 {_fmt(rotate)}（{'未验证' if tkg is None or rotate is None else ('优于' if tkg > rotate else '未优于')}）",
            },
            {
                "label": "③ 指标时序回归 RMSE",
                "value": _fmt(eval_m.get("rmse_mean")),
                "sub": f"专利引用真值 RMSE {_fmt(cite_m.get('rmse'))}",
            },
        ]

    @staticmethod
    def _build_notes(eval_m: dict, cite_m: dict) -> list[str]:
        edge = eval_m.get("tkg_edge_source_used") or eval_m.get("edge_source") or "—"
        notes = [
            f"TKG 边源：`{edge}`（共现投影为正式主边源；专利引用图经 P2-1 证伪，不作 TKG 边源）。",
            "回测产物来自 walk-forward 滚动原点；时间泄漏与评估口径仍需独立审查，不能仅凭阶段执行成功认定无泄漏。",
            "目标④ 阶段标签是启发式（非监督真值）：emerging=累积量低于分位/箱数不足，declining=近窗零增长。",
        ]
        if cite_m.get("lifecycle_sampling"):
            notes.append(
                f"专利 S 曲线描述性选样：`{cite_m.get('lifecycle_sampling')}`；引用回测候选仅由每折过去信息选择。"
            )
        if eval_m.get("protocol_version"):
            notes.append(f"评估协议：{eval_m['protocol_version']}。历史字段修订与当时可得性未验证；完整日历缺月表示零条已记录事件，不代表真实活动为零。")
        return notes

    @staticmethod
    def _write_chart_files(charts_dir: Path, charts: list[dict]) -> None:
        for i, c in enumerate(charts):
            svg = c.get("svg") or ""
            if not svg:
                continue
            key = f"chart_{i:02d}"
            (charts_dir / f"{key}.svg").write_text(svg, encoding="utf-8")

    @staticmethod
    def _read_reports(out_dir: Path, weekly_path: Path) -> list[dict]:
        """Read a fixed report allowlist; embed escaped Markdown source for offline review."""
        reports = []
        paths = [out_dir / name for name in ("report.md", "eval_report.md", "report_llm.md")]
        paths.append(weekly_path)
        paths.extend(PROJECT_ROOT / name for name in (
            "COMPARISON_REPORT.md", "MERGE_PLAN.md", "REPORT_OUTLINE.md",
        ))
        paths.extend(PROJECT_ROOT / "Attempt" / "docs" / name for name in (
            "leakage_revision_01.md", "research_direction_01.md",
        ))
        for path in paths:
            exists = path.exists()
            reports.append({
                "title": path.name,
                "source": str(path),
                "body": (path.read_text(encoding="utf-8") if exists else "尚未生成此报告。")
                    + ("\n\n注意：项目计划和对比报告包含上游历史记录，未经本机重新验证。" if path.parent == PROJECT_ROOT else ""),
            })
        return reports


__all__ = ["VisualizeStage"]
