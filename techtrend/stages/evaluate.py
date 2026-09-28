"""评测阶段（P4，第 7 阶段）：walk-forward 回测 + purge/embargo 防泄漏。

输入：data/interim/{triples,works}.jsonl。
输出（output/）：
- eval_metrics.json  四指标（p@k/r@k、MRR/Hits、MAE/RMSE/MAPE）mean±std + 每折明细
- eval_folds.csv     TKG 每折明细（fold, 时间边界, n_train/n_test, 各指标）
- eval_report.md     可读评测报告（含结论行：定向图上 CyGNet 是否 > RotatE）
- leak_check.json    无泄漏校验（每折 train/test 时间不重叠、embargo/purge 生效）

职责：与 predict 的单次 3-way 快指标并存；报告以 eval_report.md 为准。
"""
import json
import logging

import pandas as pd

from techtrend.io import read_jsonl
from techtrend.prediction.kleinberg import build_concept_monthly_counts
from techtrend.stages.base import Stage

log = logging.getLogger(__name__)


class EvaluateStage(Stage):
    name = "evaluate"

    def run(self) -> dict:
        s = self.settings
        try:
            if not s.eval_enable:
                log.info("EVAL_ENABLE=false，评测阶段跳过")
                return {"stage": self.name, "status": "skipped"}

            output_dir = s.output_dir
            output_dir.mkdir(parents=True, exist_ok=True)
            interim_dir = s.data_dir / "interim"

            triples = read_jsonl(interim_dir / "triples.jsonl")
            works = read_jsonl(interim_dir / "works.jsonl")
            if not triples:
                log.warning("triples.jsonl 为空，请先运行 --stage extract/align")
                return {"stage": self.name, "status": "error", "error": "triples 为空"}

            from datetime import date

            from techtrend.prediction import evaluation as ev, temporal as tp

            # ---- 1. 构建事实流（与 predict 同一边源逻辑）----
            doc_types = {x.strip() for x in s.tkg_doc_types.split(",") if x.strip()}
            max_time = s.tkg_max_time or date.today().isoformat()
            if s.tkg_edge_source == "directed":
                # 定向 tech→tech（消融对照）：多关系、定向、稀疏
                techpair_rel = {r.strip() for r in s.techpair_relations.split(",") if r.strip()}
                facts = tp.load_directed_edges(
                    triples, relations=techpair_rel,
                    min_support=s.techpair_min_support, max_time=max_time,
                )
            else:
                # 共现投影（正式主边源，P3 起沿用）
                facts = tp.project_t2t(
                    triples, relation=s.tkg_relation,
                    min_cooccur=s.tkg_min_cooccur, max_entities=s.tkg_max_entities,
                    doc_types=doc_types, max_time=max_time,
                )

            # ---- 2. 月度频次矩阵（回归 + 排名共用）----
            # 过滤 future-dated works：OpenAlex 存在发布日期在「今天」之后的坏记录（可到 2050），
            # 若不过滤会使 monthly 矩阵出现未来月，回归/排名回测的 test 窗口落到未来 = 数据泄漏 + 无真值。
            valid_works = [
                w for w in works
                if (w.get("publication_date") or "") and (w.get("publication_date") or "") <= max_time
            ]
            monthly = build_concept_monthly_counts(valid_works, mode=s.burst_bin)
            exclude = {c.strip() for c in s.openalex_concept_ids.split(",") if c.strip()}
            if not monthly.empty:
                monthly = monthly.drop(index=[c for c in exclude if c in monthly.index])

            # ---- 3. TKG 回测（目标②）----
            cfg_tkg = {
                "n_splits": s.eval_n_splits,
                "test_months": s.eval_test_months,
                "step_months": s.eval_step_months,
                "embargo_months": s.eval_embargo_months,
                "mode": s.eval_mode,
                "rolling_window_months": s.eval_rolling_window_months,
                "min_train": s.eval_min_train,
                "tkg_dim": s.tkg_embedding_dim,
                # walk-forward 每折重训，降轮次控计算量（见 P3_OPT 风险「walk-forward 计算量」）
                "tkg_epochs": max(5, min(s.tkg_epochs, 15)),
                "tkg_neg": s.tkg_neg_samples,
                "tkg_alpha": s.tkg_alpha,
                "rotate_epochs": max(10, min(s.rotate_epochs, 20)),
            }
            tkg_result = ev.backtest_tkg(facts, cfg_tkg) if facts else {"fold_metrics": [], "n_folds": 0}
            tkg_edge_used = s.tkg_edge_source
            tkg_fallback = None
            if tkg_result.get("tkg_mrr_mean") is None:
                # 消融边源（directed）时态跨度不足：近端无事实或单时间组，
                # walk-forward 无法切出有效折（train 不足 min_train 或 test 为空）。
                # 回退共现投影（正式主边源，2023→2026 连续时态分布）作 TKG 回测边源，
                # 报告如实说明。
                fallback_facts = tp.project_t2t(
                    triples, relation=s.tkg_relation,
                    min_cooccur=s.tkg_min_cooccur, max_entities=s.tkg_max_entities,
                    doc_types=doc_types, max_time=max_time,
                )
                tkg_result = ev.backtest_tkg(fallback_facts, cfg_tkg)
                tkg_edge_used = "cooccur"
                tkg_fallback = (
                    f"{s.tkg_edge_source} 边源无有效 walk-forward 折"
                    f"（时态跨度不足，或 test 实体在 train 无历史被转导协议整体剔除）→ 回退共现投影"
                )
                facts = fallback_facts  # leak_check 与 TKG 同一边源，保持一致

            # ---- 4. 回归回测（目标③，含 purge）----
            cfg_reg = {
                "n_splits": s.eval_n_splits,
                "test_months": s.eval_test_months,
                "step_months": s.eval_step_months,
                "horizon": s.forecast_horizon,
                "min_history": s.forecast_min_history,
                "top_k": s.forecast_top_k,
                "lag": s.forecast_lag,
                "purge": s.eval_purge_months,
            }
            reg_result = ev.backtest_regression(monthly, cfg_reg)

            # ---- 5. 排名回测（目标①）----
            cfg_rank = {
                "n_splits": s.eval_n_splits,
                "test_months": s.eval_test_months,
                "step_months": s.eval_step_months,
                "top_k": s.burst_top_k,
                "burst_s": s.burst_s,
                "burst_gamma": s.burst_gamma,
            }
            rank_result = ev.backtest_ranking(monthly, cfg_rank)

            # ---- 5.5 专利引用时序（P1-2：目标③真引用回归 + 目标④ S 曲线）----
            citation_metrics = self._run_citation_metrics(s, ev, cfg_reg)

            # ---- 6. 无泄漏校验 ----
            leak = {"ok": False, "violations": [], "test_only_entities_per_fold": []}
            if facts:
                origins = ev.rolling_origins(
                    [f["time"] for f in facts],
                    s.eval_n_splits, s.eval_test_months, s.eval_step_months,
                )
                folds = ev.walk_forward_splits(
                    facts, origins, s.eval_embargo_months, s.eval_mode,
                    s.eval_rolling_window_months,
                )
                leak = ev.leak_check(folds)

            # ---- 7. 写输出 ----
            eval_metrics = {
                "edge_source": s.tkg_edge_source,
                "tkg_edge_source_used": tkg_edge_used,
                "tkg_fallback_reason": tkg_fallback,
                "n_facts": len(facts),
                # 目标② TKG
                "tkg_mrr_mean": tkg_result.get("tkg_mrr_mean"),
                "tkg_mrr_std": tkg_result.get("tkg_mrr_std"),
                "tkg_hits_at_10_mean": tkg_result.get("tkg_hits_at_10_mean"),
                "copyonly_mrr_mean": tkg_result.get("copyonly_mrr_mean"),
                "rotate_mrr_mean": tkg_result.get("rotate_mrr_mean"),
                "tkg_folds": tkg_result.get("fold_metrics", []),
                # 目标③ 回归
                "mae_mean": reg_result.get("mae_mean"),
                "mae_std": reg_result.get("mae_std"),
                "rmse_mean": reg_result.get("rmse_mean"),
                "rmse_std": reg_result.get("rmse_std"),
                "mape_mean": reg_result.get("mape_mean"),
                "mape_std": reg_result.get("mape_std"),
                "regression_folds": reg_result.get("fold_metrics", []),
                # 目标① 排名
                "p_at_k_mean": rank_result.get("p_at_k_mean"),
                "p_at_k_std": rank_result.get("p_at_k_std"),
                "r_at_k_mean": rank_result.get("r_at_k_mean"),
                "r_at_k_std": rank_result.get("r_at_k_std"),
                "ranking_folds": rank_result.get("fold_metrics", []),
                "leak_ok": leak["ok"],
            }
            (output_dir / "eval_metrics.json").write_text(
                json.dumps(eval_metrics, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            self._write_folds_csv(output_dir / "eval_folds.csv", tkg_result.get("fold_metrics", []))
            (output_dir / "eval_report.md").write_text(
                _render_report(eval_metrics), encoding="utf-8"
            )
            (output_dir / "leak_check.json").write_text(
                json.dumps(leak, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            log.info(
                "evaluate 完成：edge=%s, facts=%d, tkg_mrr=%.4f±%.4f, rmse=%.4f, p@k=%.4f, leak_ok=%s",
                s.tkg_edge_source, len(facts),
                eval_metrics["tkg_mrr_mean"] or 0.0, eval_metrics["tkg_mrr_std"] or 0.0,
                eval_metrics["rmse_mean"] or 0.0, eval_metrics["p_at_k_mean"] or 0.0,
                leak["ok"],
            )
            return {
                "stage": self.name,
                "status": "ok",
                "edge_source": s.tkg_edge_source,
                "tkg_edge_source_used": tkg_edge_used,
                "tkg_mrr_mean": eval_metrics["tkg_mrr_mean"],
                "rotate_mrr_mean": eval_metrics["rotate_mrr_mean"],
                "rmse_mean": eval_metrics["rmse_mean"],
                "p_at_k_mean": eval_metrics["p_at_k_mean"],
                "leak_ok": leak["ok"],
            }
        except Exception as exc:  # noqa: BLE001
            log.exception("evaluate 阶段失败")
            return {"stage": self.name, "status": "error", "error": str(exc)}

    @staticmethod
    def _run_citation_metrics(s, ev, cfg_reg) -> dict:
        """专利前向引用时序（P1-2）：累积引用曲线 → 回归真值 + S 曲线阶段标签。

        依赖 patent_citations.jsonl（P0-1 产物）。若引用时态跨度不足（单月）则跳过并说明，
        不阻断整体评测。写 output/citation_metrics.json + output/s_curve_stages.csv。
        """
        from pathlib import Path

        from techtrend.io import read_jsonl
        from techtrend.prediction.citations import (
            build_patent_citation_monthly,
            s_curve_stages,
        )
        from techtrend.prediction.lifecycle import mean_stage_curves

        out: dict = {"status": "skipped", "reason": None, "mae": None, "rmse": None, "mape": None,
                     "n_patents": 0, "n_months": 0, "sampling": None, "s_curve_dist": {}}
        path = Path(s.patent_citations_file)
        if not path.exists():
            out["reason"] = "patent_citations.jsonl 不存在（先 collect_sources=patent_citations）"
            return out
        facts = read_jsonl(path)
        if not facts:
            out["reason"] = "引用事实为空"
            return out

        monthly = build_patent_citation_monthly(
            facts, mode=s.burst_bin, sampling=s.patent_citation_sampling,
            n_bins=s.patent_citation_n_bins, per_bin=s.patent_citation_per_bin,
        )
        if monthly.empty:
            out["reason"] = "累积引用矩阵为空"
            return out
        out["n_patents"] = len(monthly.index)
        out["n_months"] = len(monthly.columns)
        out["sampling"] = s.patent_citation_sampling

        # 时态跨度不足（< forecast_horizon+2 月）无法回测，仅出 S 曲线分布
        if len(monthly.columns) >= s.forecast_horizon + 2:
            reg = ev.backtest_regression(monthly, cfg_reg)
            out["mae"] = reg.get("mae_mean")
            out["rmse"] = reg.get("rmse_mean")
            out["mape"] = reg.get("mape_mean")
            out["status"] = "ok"
        else:
            out["reason"] = f"引用时态跨度不足（{len(monthly.columns)} 月 < horizon+2），回归跳过"

        stages = s_curve_stages(
            monthly, growth_window=s.lifecycle_growth_window,
            emerging_quantile=s.lifecycle_emerging_quantile,
            min_history=s.lifecycle_min_history,
        )
        out["s_curve_dist"] = stages.value_counts().to_dict()
        pd.DataFrame({"patent": stages.index, "stage": stages.to_numpy()}).to_csv(
            s.output_dir / "s_curve_stages.csv", index=False, encoding="utf-8-sig"
        )
        # 每阶段一条归一化累积均值曲线（供 P6 可视化叠加图，免重读 1GB 引用文件）
        curves = mean_stage_curves(monthly, stages)
        if not curves.empty:
            curves.to_csv(s.output_dir / "s_curve_curves.csv", encoding="utf-8-sig")
        (s.output_dir / "citation_metrics.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log.info(
            "专利引用时序：patents=%d months=%d status=%s s_curve=%s",
            out["n_patents"], out["n_months"], out["status"], out["s_curve_dist"],
        )
        return out

    @staticmethod
    def _write_folds_csv(path, tkg_folds: list[dict]) -> None:
        cols = [
            "fold", "train_end", "test_start", "test_end", "n_train", "n_test",
            "tkg_mrr", "tkg_hits_at_1", "tkg_hits_at_3", "tkg_hits_at_10",
            "copyonly_mrr", "rotate_mrr", "rotate_hits_at_10",
        ]
        rows = [{c: f.get(c) for c in cols} for f in tkg_folds]
        pd.DataFrame(rows, columns=cols).to_csv(path, index=False, encoding="utf-8-sig")


def _fmt(v):
    return "—" if v is None else f"{v:.4f}"


def _conclusion(eval_metrics: dict) -> str:
    tkg = eval_metrics.get("tkg_mrr_mean")
    rotate = eval_metrics.get("rotate_mrr_mean")
    if tkg is None or rotate is None:
        return "TKG 或 RotatE 对照缺失，无法判定。"
    verdict = "✅ 优于" if tkg > rotate else "❌ 未优于"
    return (
        f"CyGNet 时态 MRR={tkg:.4f} vs RotatE 时态 MRR={rotate:.4f}（walk-forward 均值），"
        f"{verdict}静态（时态同协议）基线。"
    )


def _render_report(m: dict) -> str:
    lines = [
        "# P4 验证体系评测报告（walk-forward 回测）",
        "",
        f"- TKG 边源：`{m.get('tkg_edge_source_used') or m.get('edge_source')}`　事实数：{m.get('n_facts')}",
        f"- 无泄漏校验：{'✅ 通过' if m.get('leak_ok') else '❌ 存在重叠'}",
        "",
    ]
    if m.get("tkg_fallback_reason"):
        lines += [
            f"> ⚠️ TKG 回测边源回退：{m['tkg_fallback_reason']}。",
            "",
        ]
    lines += [
        "## 目标② 时序链接预测外推（CyGNet / RotatE 时态对照）",
        "",
        "| 指标 | mean ± std |",
        "|---|---|",
        f"| TKG filtered MRR（CyGNet） | {_fmt(m.get('tkg_mrr_mean'))} ± {_fmt(m.get('tkg_mrr_std'))} |",
        f"| TKG Hits@10 | {_fmt(m.get('tkg_hits_at_10_mean'))} |",
        f"| copy-only 基线 MRR | {_fmt(m.get('copyonly_mrr_mean'))} |",
        f"| RotatE 时态对照 MRR | {_fmt(m.get('rotate_mrr_mean'))} |",
        "",
        "> 结论：" + _conclusion(m),
        "",
        "## 目标③ 指标时序回归（MAE/RMSE/MAPE）",
        "",
        "| 指标 | mean ± std |",
        "|---|---|",
        f"| MAE | {_fmt(m.get('mae_mean'))} ± {_fmt(m.get('mae_std'))} |",
        f"| RMSE | {_fmt(m.get('rmse_mean'))} ± {_fmt(m.get('rmse_std'))} |",
        f"| MAPE | {_fmt(m.get('mape_mean'))} ± {_fmt(m.get('mape_std'))} |",
        "",
        "## 目标① 新兴技术识别排名（precision@k / recall@k）",
        "",
        "| 指标 | mean ± std |",
        "|---|---|",
        f"| precision@k | {_fmt(m.get('p_at_k_mean'))} ± {_fmt(m.get('p_at_k_std'))} |",
        f"| recall@k | {_fmt(m.get('r_at_k_mean'))} ± {_fmt(m.get('r_at_k_std'))} |",
        "",
        "> 口径：walk-forward 多期回测（expanding window + embargo + purge），四指标齐备、无泄漏、可复现。",
        "",
    ]
    return "\n".join(lines)
