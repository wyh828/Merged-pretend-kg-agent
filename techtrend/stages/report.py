"""报告阶段：把 baseline_metrics.json + temporal_metrics.json + 评测产物落成四目标 report.md。

向后兼容：P3 单快照（baseline + temporal）为主；若 output/eval_metrics.json /
citation_metrics.json 已存在（同一次 daily 运行 evaluate 在 report 前，或上次全量运行），
追加「四目标总览」段（目标①排名 ②时序链接 ③回归 ④S 曲线）。缺文件则如实写「—」。
"""
import json
import logging

from techtrend.stages.base import Stage

log = logging.getLogger(__name__)


class ReportStage(Stage):
    name = "report"

    def run(self) -> dict:
        s = self.settings
        try:
            output_dir = s.output_dir
            output_dir.mkdir(parents=True, exist_ok=True)
            metrics_path = output_dir / "baseline_metrics.json"
            eval_m = _read_json(output_dir / "eval_metrics.json")
            cite_m = _read_json(output_dir / "citation_metrics.json")
            if not metrics_path.exists():
                if not eval_m and not cite_m:
                    log.warning("没有预测或评估产物，请先运行 --stage predict/evaluate")
                    return {"stage": self.name, "status": "skipped", "reason": "missing prediction/evaluation artifacts", "report_file": None}
                baseline = {}
            else:
                baseline = json.loads(metrics_path.read_text(encoding="utf-8"))
            temporal_path = output_dir / "temporal_metrics.json"
            temporal = (
                json.loads(temporal_path.read_text(encoding="utf-8"))
                if temporal_path.exists()
                else {}
            )

            body = _render(baseline, temporal)
            if eval_m or cite_m:
                body += _render_four_goals(eval_m, cite_m)

            # 阶段 4 合并：可选 DeepSeek 研报解读（有 key 才跑；无 key 确定性回退）
            body += _render_llm_narrative(s, output_dir, eval_m)

            report_path = output_dir / "report.md"
            report_path.write_text(body, encoding="utf-8")
            log.info("report 完成：%s", report_path)
            return {"stage": self.name, "status": "ok", "report_file": str(report_path)}
        except Exception as exc:  # noqa: BLE001
            log.exception("report 阶段失败")
            return {"stage": self.name, "status": "error", "error": str(exc)}


def _read_json(path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 —— 缺文件/坏 JSON 都当作无
        return {}


def _fmt(v):
    return "—" if v is None else f"{v:.4f}"


def _read_fusion_top(output_dir, k: int = 5) -> list[dict]:
    """读 fusion_ranking.csv 的前 k 个概念（entity/name/score）。"""
    import csv

    path = output_dir / "fusion_ranking.csv"
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        return [
            {"concept": (r.get("name") or r.get("entity") or ""), "score": r.get("score")}
            for r in rows[:k]
        ]
    except Exception as exc:  # noqa: BLE001
        log.warning("读 fusion_ranking.csv 失败：%s", exc)
        return []


def _render_llm_narrative(s, output_dir, eval_m: dict) -> str:
    """阶段 4 合并：DeepSeek 研报解读（榜单解读 + 回测可靠性 + 行动建议）。

    - 无 `llm_api_key` → 如实标注「未启用 LLM」，确定性回退（报告主体仍为确定性四目标总览）。
    - 有 key → 调 DeepSeek（纯文本，不复用抽取器的 json_object），写 `report_llm.md`，
      在 `report.md` 追加指针；失败则标注错误（不阻断确定性报告）。
    """
    note = "\n## 研报解读（LLM）\n\n"
    if not s.llm_api_key:
        return note + "> 未启用 LLM 研报解读：未配置 `LLM_API_KEY`（保持确定性报告）。\n"

    top5 = _read_fusion_top(output_dir, k=5)
    if not top5 and not eval_m:
        return note + "> 无榜单/回测数据，跳过 LLM 研报解读。\n"

    backtest = {
        "p_at_k": eval_m.get("p_at_k_mean"),
        "ndcg_at_3": eval_m.get("ndcg_at_3_mean"),
        "ndcg_at_5": eval_m.get("ndcg_at_5_mean"),
        "spearman_rho": eval_m.get("spearman_rho_mean"),
        "top1_lift": eval_m.get("top1_lift_mean"),
        "kleinberg_p_at_k": eval_m.get("kleinberg_p_at_k_mean"),
        "leak_ok": eval_m.get("leak_ok"),
    }
    prompt = (
        "我们构建了一套面向跨领域技术趋势预测的图+信号融合系统，结合学术论文、开源社区、新闻报道等多源信号，"
        "采用「相对注意力份额 + EMA/MACD 动量」综合评分（Concept 细粒度），提供了滚动时间窗口回测产物，但时间泄漏仍需独立审查。\n\n"
        "【最新融合技术榜单（Top 5）】：\n"
        f"{json.dumps(top5, ensure_ascii=False, indent=2)}\n\n"
        "【滚动回测结果（排序指标：p@k、NDCG@3/5、Spearman 秩相关、Top-1 Lift；Kleinberg 突发为消融基线）】：\n"
        f"{json.dumps(backtest, ensure_ascii=False, indent=2)}\n\n"
        "请基于上述数据撰写一份结构严谨、具学术与商业价值的趋势研判报告，包含：\n"
        "1. **核心前沿技术榜单深度解读**（领跑技术 vs 相对注意力份额加速扩张的黑马）。\n"
        "2. **回测有效性与排序可靠性评估**（结合 Spearman 单调性与 NDCG@3/5 头部命中增益，评价系统稳定度；"
        "对比相对份额动量与 Kleinberg 突发的 p@k 差异）。\n"
        "3. **研判结论与后续行动建议**（科研交叉方向 / 产业配置节奏 / 预测系统工程改进）。\n\n"
        "请用清晰专业的中文、Markdown 表格与排版，保持客观严谨。"
    )

    try:
        from openai import OpenAI  # 延迟导入，无 openai 或网络故障时确定性回退

        client = OpenAI(base_url=s.llm_base_url, api_key=s.llm_api_key)
        resp = client.chat.completions.create(
            model=s.llm_model,
            messages=[
                {"role": "system", "content": "你是一名资深技术趋势分析师，用 Markdown 撰写客观严谨的研报。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=s.llm_max_tokens,
            temperature=0.5,
        )
        md = (resp.choices[0].message.content or "").strip()
        if not md:
            return note + "> LLM 返回空内容，研报解读未生成。\n"
        (output_dir / "report_llm.md").write_text(md, encoding="utf-8")
        log.info("LLM 研报解读已写：%s", output_dir / "report_llm.md")
        return note + "> 完整 LLM 研报解读见 `report_llm.md`（DeepSeek）。\n"
    except Exception as exc:  # noqa: BLE001 —— 网络/key 故障不阻断确定性报告
        log.warning("LLM 研报解读失败：%s", exc)
        return note + f"> LLM 研报解读未生成（调用失败：{exc}）。\n"


def _render(baseline: dict, temporal: dict) -> str:
    lines = [
        "# P3 时序预测报告",
        "",
        "## 链接预测（RotatE，filtered，随机切分）",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| filtered MRR | {_fmt(baseline.get('filtered_mrr'))} |",
        f"| Hits@1 | {_fmt(baseline.get('hits_at_1'))} |",
        f"| Hits@3 | {_fmt(baseline.get('hits_at_3'))} |",
        f"| Hits@10 | {_fmt(baseline.get('hits_at_10'))} |",
        "",
        "## 新兴技术识别（Kleinberg 突发 vs 未来窗口增速）",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| precision@k | {_fmt(baseline.get('precision_at_k'))} |",
        f"| recall@k | {_fmt(baseline.get('recall_at_k'))} |",
        "",
    ]

    # ---- 时序链接预测外推（P3）----
    lines += [
        "## 时序链接预测外推（CyGNet，时态 3-way 切分）",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| TKG filtered MRR（CyGNet） | {_fmt(temporal.get('tkg_filtered_mrr'))} |",
        f"| TKG Hits@1 | {_fmt(temporal.get('tkg_hits_at_1'))} |",
        f"| TKG Hits@3 | {_fmt(temporal.get('tkg_hits_at_3'))} |",
        f"| TKG Hits@10 | {_fmt(temporal.get('tkg_hits_at_10'))} |",
        f"| copy-only 基线 MRR | {_fmt(temporal.get('tkg_copyonly_mrr'))} |",
        f"| RotatE 时态对照 MRR | {_fmt(temporal.get('rotate_temporal_mrr'))} |",
        f"| RotatE 时态对照 Hits@10 | {_fmt(temporal.get('rotate_temporal_hits_at_10'))} |",
        f"| 规则数 | {temporal.get('tkg_rules', 0)} |",
        f"| TKG 边源 | {temporal.get('tkg_edge_source', 'cooccur')} |",
        f"| train/val/test 三元组 | {temporal.get('tkg_train_triples', 0)} / {temporal.get('tkg_val_triples', 0)} / {temporal.get('tkg_test_triples', 0)} |",
        "",
        "> 结论：" + _conclusion_line(temporal),
        "",
    ]

    # ---- 指标时序回归 + 融合（P3）----
    lines += [
        "## 指标时序回归 + 融合",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| forecast MAE | {_fmt(temporal.get('forecast_mae'))} |",
        f"| forecast RMSE | {_fmt(temporal.get('forecast_rmse'))} |",
        f"| forecast MAPE | {_fmt(temporal.get('forecast_mape'))} |",
        f"| fusion precision@k | {_fmt(temporal.get('fusion_precision_at_k'))} |",
        f"| fusion recall@k | {_fmt(temporal.get('fusion_recall_at_k'))} |",
        "",
    ]
    top = temporal.get("fusion_top_k") or []
    if top:
        lines.append("## 融合 Top 概念")
        lines.append("")
        lines.extend(f"- {c}" for c in top)
        lines.append("")

    # Kleinberg top（沿用）
    top = baseline.get("burst_top_k") or []
    if top:
        lines.append("## Top 突发概念（Kleinberg）")
        lines.append("")
        lines.extend(f"- {c}" for c in top)
        lines.append("")
    return "\n".join(lines)


def _render_four_goals(eval_m: dict, cite_m: dict) -> str:
    """四目标总览（walk-forward 回测 + 引用时序 + S 曲线），如实标注数据来源。"""
    tkg = eval_m.get("tkg_mrr_mean")
    rotate = eval_m.get("rotate_mrr_mean")
    edge = eval_m.get("tkg_edge_source_used") or eval_m.get("edge_source") or "—"
    s_curve = cite_m.get("s_curve_dist") or {}
    s_curve_str = (
        "，".join(f"{k}={v}" for k, v in sorted(s_curve.items()))
        if s_curve else "—"
    )
    verdict = "未验证（缺少模型或对照指标）" if tkg is None or rotate is None else ("✅ 优于" if tkg > rotate else "❌ 未优于")
    return "\n".join([
        "",
        "## 四目标总览（walk-forward 回测）",
        "",
        "| 目标 | 指标 | 值 |",
        "|---|---|---|",
        f"| ① 新兴技术识别 | precision@k（排名回测） | {_fmt(eval_m.get('p_at_k_mean'))} ± {_fmt(eval_m.get('p_at_k_std'))} |",
        f"| ② 时序链接预测 | CyGNet filtered MRR | {_fmt(tkg)} ± {_fmt(eval_m.get('tkg_mrr_std'))} |",
        f"| ② 对照 | RotatE 时态 MRR / copy-only MRR | {_fmt(rotate)} / {_fmt(eval_m.get('copyonly_mrr_mean'))} |",
        f"| ③ 指标时序回归 | 活动代理 MAE / RMSE / MAPE | {_fmt(eval_m.get('mae_mean'))} / {_fmt(eval_m.get('rmse_mean'))} / {_fmt(eval_m.get('mape_mean'))} |",
        f"| ③ 引用真值 | 专利引用 RMSE | {_fmt(cite_m.get('rmse'))} |",
        f"| ④ S 曲线 | 阶段分布 | {s_curve_str} |",
        "",
        f"> TKG 边源：`{edge}`；② 结论：CyGNet {verdict}静态（时态同协议）基线。",
        "> ③ 引用回归与 ④ S 曲线来自专利前向引用图（P0-1，分层选样）；阶段标签为启发式。",
        "",
    ])


def _conclusion_line(temporal: dict) -> str:
    """是否优于静态（时态同协议）基线。"""
    tkg_mrr = temporal.get("tkg_filtered_mrr")
    rotate_mrr = temporal.get("rotate_temporal_mrr")
    if tkg_mrr is None or rotate_mrr is None:
        return "时态外推或对照缺失，无法判定是否优于静态基线。"
    verdict = "✅ 优于" if tkg_mrr > rotate_mrr else "❌ 未优于"
    return (
        f"CyGNet 时态 MRR={tkg_mrr:.4f} vs RotatE 时态 MRR={rotate_mrr:.4f}，"
        f"{verdict}静态（时态同协议）基线。"
    )
