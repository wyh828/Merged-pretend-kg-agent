"""预测阶段（P3）：RotatE 链接预测 + Kleinberg 突发 + TKG 外推 + 回归 + 融合。

输出：
- output/baseline_metrics.json  Kleinberg + RotatE（随机切分），向后兼容 P1/P2
- output/temporal_metrics.json  P3 时序指标（RotatE 时态对照 + TKG + 回归 + 融合）
- output/tkg_rules.jsonl / forecast.csv / fusion_ranking.csv
"""
import json
import logging

import pandas as pd

from techtrend.io import read_jsonl
from techtrend.prediction.kleinberg import (
    build_concept_monthly_counts,
    concept_names,
    detect_top_bursts,
    future_growth_top_k,
    kleinberg_bursts,
)
from techtrend.prediction.metrics import precision_at_k, recall_at_k
from techtrend.prediction.signal import concept_share_momentum, share_momentum_rank
from techtrend.prediction.rotatE import random_split, run_rotate
from techtrend.stages.base import Stage

log = logging.getLogger(__name__)


class PredictStage(Stage):
    name = "predict"

    def run(self) -> dict:
        s = self.settings
        try:
            output_dir = s.output_dir
            output_dir.mkdir(parents=True, exist_ok=True)
            interim_dir = s.data_dir / "interim"

            works = read_jsonl(interim_dir / "works.jsonl")
            triples = read_jsonl(interim_dir / "triples.jsonl")

            # ---- 基线（Kleinberg + 相对份额动量 + RotatE 随机切分），向后兼容 ----
            baseline: dict = {"stage": self.name}
            baseline.update(self._run_kleinberg(s, works, output_dir))
            baseline.update(self._run_share_signal(s, works, output_dir))
            baseline.update(self._run_rotate(s, triples))

            # ---- P3 时序：RotatE 时态对照 + TKG + 回归 + 融合 ----
            temporal: dict = {}
            tkg_out = self._run_tkg(s, triples, output_dir)
            temporal.update(tkg_out)
            # 阶段 5 合并：持久化未来链接分，供链接预测 agent（collaborate 阶段）复用
            if tkg_out.get("_tkg_scores"):
                (output_dir / "tkg_scores.json").write_text(
                    json.dumps(tkg_out["_tkg_scores"], ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            forecast_out = self._run_forecast(s, works, output_dir)
            temporal.update(forecast_out)
            temporal.update(
                self._run_fusion(
                    s, works,
                    tkg_out.get("_tkg_scores", {}),
                    forecast_out.get("_forecast_signal", {}),
                    output_dir,
                )
            )
            temporal.pop("_tkg_scores", None)
            temporal.pop("_forecast_signal", None)

            (output_dir / "baseline_metrics.json").write_text(
                json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (output_dir / "temporal_metrics.json").write_text(
                json.dumps(temporal, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            result: dict = {"stage": self.name, "status": "ok"}
            result.update(baseline)
            result.update(temporal)
            log.info(
                "predict 完成：filtered_mrr=%s, tkg_filtered_mrr=%s, rotate_temporal_mrr=%s, "
                "forecast_rmse=%s, fusion_p@k=%s",
                result.get("filtered_mrr"),
                result.get("tkg_filtered_mrr"),
                result.get("rotate_temporal_mrr"),
                result.get("forecast_rmse"),
                result.get("fusion_precision_at_k"),
            )
            return result
        except Exception as exc:  # noqa: BLE001
            log.exception("predict 阶段失败")
            return {"stage": self.name, "status": "error", "error": str(exc)}

    # ------------------------------------------------------------------
    # 基线
    # ------------------------------------------------------------------
    def _run_kleinberg(self, s, works, output_dir) -> dict:
        out = {"precision_at_k": None, "recall_at_k": None, "burst_top_k": []}
        try:
            df = build_concept_monthly_counts(works, mode=s.burst_bin)
            if df.empty:
                log.warning("无 concept 频次数据，Kleinberg 跳过")
                return out
            if df.shape[1] <= s.burst_future_months:
                log.warning(
                    "时间箱仅 %d 个（需 > %d 个月），Kleinberg 评估跳过",
                    df.shape[1], s.burst_future_months,
                )
                return out

            names = concept_names(works)
            # 剔除筛选概念（如 AI/CS）：它们出现在几乎所有 work，突发排名被其无信息地占据
            exclude = {c.strip() for c in s.openalex_concept_ids.split(",") if c.strip()}
            df = df.drop(index=[c for c in exclude if c in df.index])

            hist_df = df.iloc[:, : -s.burst_future_months]
            top_bursts = detect_top_bursts(hist_df, s.burst_top_k, s=s.burst_s, gamma=s.burst_gamma)
            ranked = top_bursts["concept"].tolist()
            truth = future_growth_top_k(df, s.burst_future_months, s.burst_top_k)

            out["precision_at_k"] = precision_at_k(ranked, truth, s.burst_top_k)
            out["recall_at_k"] = recall_at_k(ranked, truth, s.burst_top_k)
            out["burst_top_k"] = ranked

            rows = [
                {
                    "concept_id": r["concept"],
                    "concept_name": names.get(r["concept"], ""),
                    "weight": r["weight"],
                    "n_bursts": r["n_bursts"],
                }
                for _, r in top_bursts.iterrows()
            ]
            pd.DataFrame(rows).to_csv(output_dir / "burst_concepts.csv", index=False, encoding="utf-8-sig")
            log.info("Kleinberg：top-%d 突发概念 = %s", len(ranked), ranked[:5])
        except Exception as exc:  # noqa: BLE001
            log.exception("Kleinberg 运行失败")
        return out

    def _run_share_signal(self, s, works, output_dir) -> dict:
        """阶段 1 合并：相对份额动量信号（与 Kleinberg 消融并列，救目标① p@k=0）。"""
        out = {"share_precision_at_k": None, "share_recall_at_k": None, "share_top_k": []}
        try:
            df = build_concept_monthly_counts(works, mode=s.burst_bin)
            if df.empty:
                log.warning("无 concept 频次数据，share 信号跳过")
                return out
            if df.shape[1] <= s.burst_future_months:
                log.warning("时间箱不足（%d ≤ %d），share 信号评估跳过",
                            df.shape[1], s.burst_future_months)
                return out

            # 与 Kleinberg 同口径剔除筛选概念（AI/CS）
            exclude = {c.strip() for c in s.openalex_concept_ids.split(",") if c.strip()}
            df = df.drop(index=[c for c in exclude if c in df.index])

            hist_df = df.iloc[:, : -s.burst_future_months]
            ranked = share_momentum_rank(hist_df, s.burst_top_k)
            truth = future_growth_top_k(df, s.burst_future_months, s.burst_top_k)

            out["share_precision_at_k"] = precision_at_k(ranked, truth, s.burst_top_k)
            out["share_recall_at_k"] = recall_at_k(ranked, truth, s.burst_top_k)
            out["share_top_k"] = ranked
            log.info("share 信号：top-%d = %s，p@k=%s",
                     len(ranked), ranked[:5], out["share_precision_at_k"])
        except Exception as exc:  # noqa: BLE001
            log.exception("share 信号运行失败")
        return out

    def _run_rotate(self, s, triples) -> dict:
        missing = {
            "filtered_mrr": None,
            "hits_at_1": None,
            "hits_at_3": None,
            "hits_at_10": None,
        }
        if not triples:
            log.warning("triples 为空，RotatE 跳过")
            return missing
        # 静态 KG 嵌入用随机切分（实体跨 train/test 共享）；时态切分留给 P3 TKG。
        train, test = random_split(triples, s.rotate_train_ratio)
        try:
            return run_rotate(train, test, dim=s.rotate_embedding_dim, epochs=s.rotate_epochs)
        except Exception as exc:  # noqa: BLE001 —— RotatE 失败不阻断 Kleinberg 结果
            log.exception("RotatE 运行失败")
            return missing

    # ------------------------------------------------------------------
    # P3：TKG 外推（CyGNet / TLogic / copy-only 基线 / RotatE 时态对照）
    # ------------------------------------------------------------------
    def _run_tkg(self, s, triples, output_dir) -> dict:
        out = {
            "tkg_filtered_mrr": None,
            "tkg_hits_at_1": None,
            "tkg_hits_at_3": None,
            "tkg_hits_at_10": None,
            "tkg_train_triples": 0,
            "tkg_val_triples": 0,
            "tkg_test_triples": 0,
            "tkg_rules": 0,
            "tkg_copyonly_mrr": None,
            "rotate_temporal_mrr": None,
            "rotate_temporal_hits_at_10": None,
            "tkg_edge_source": s.tkg_edge_source,
            "_tkg_scores": {},
        }
        if not s.predict_enable_tkg:
            log.info("PREDICT_ENABLE_TKG=false，TKG 外推跳过")
            return out
        try:
            from datetime import date

            from techtrend.prediction import cygnet, temporal as tp, tlogic

            # 1. 构建 Concept×Concept 持久事实流（按边源切换）
            doc_types = {x.strip() for x in s.tkg_doc_types.split(",") if x.strip()}
            max_time = s.tkg_max_time
            if max_time is None:
                max_time = date.today().isoformat()   # 默认过滤今天之后的未来坏数据
            elif max_time.strip() == "":
                max_time = None
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
            if len(facts) < 50:
                log.warning("投影事实过少（%d），TKG 外推跳过", len(facts))
                return out

            # 2. 时态 3-way 切分（时间不重叠）
            train, val, test = tp.temporal_split_3way(facts, s.tkg_train_ratio, s.tkg_val_ratio)
            out["tkg_train_triples"] = len(train)
            out["tkg_val_triples"] = len(val)
            out["tkg_test_triples"] = len(test)
            if not train or not test:
                log.warning("时态切分后 train/test 为空，TKG 外推跳过")
                return out
            if not val:
                log.warning("时态切分后 val 为空（时间组过大），CyGNet 早停退化为固定轮次")

            # 实体词表 = 过去（train+val），test 仅保留已知实体的三元组（转导协议，
            # 与 RotatE 时态对照一致；test 独有实体无历史，无法外推，须剔除）。
            e2id, r2id, id2e, id2r = cygnet.encode_ids(train + val)

            # 3. copy-only 确定性基线（Tier1）
            history = cygnet.build_history(train, e2id, r2id)
            copy_metrics = cygnet.evaluate_copy_only(e2id, r2id, history, test, known_triples=train + val + test)
            out["tkg_copyonly_mrr"] = copy_metrics.get("mrr")

            # 4. CyGNet 训练 + 评估（Tier2）
            bundle = cygnet.train_cygnet(
                train, val, dim=s.tkg_embedding_dim, epochs=s.tkg_epochs,
                neg_samples=s.tkg_neg_samples, alpha=s.tkg_alpha,
            )
            metrics = cygnet.evaluate_cygnet(bundle, test, known_triples=train + val + test)
            out["tkg_filtered_mrr"] = metrics.get("mrr")
            out["tkg_hits_at_1"] = metrics.get("hits_at_1")
            out["tkg_hits_at_3"] = metrics.get("hits_at_3")
            out["tkg_hits_at_10"] = metrics.get("hits_at_10")

            # 5. RotatE 时态对照：同一投影事实流 + 同一时态切分（同协议对比）
            #    过去 = train+val，未来 = test（与 CyGNet 用同一「过去」数据公平对比）。
            try:
                rotate_t = run_rotate(
                    train + val, test, dim=s.rotate_embedding_dim, epochs=s.rotate_epochs
                )
                out["rotate_temporal_mrr"] = rotate_t.get("filtered_mrr")
                out["rotate_temporal_hits_at_10"] = rotate_t.get("hits_at_10")
            except Exception as exc:  # noqa: BLE001
                log.exception("RotatE 时态对照运行失败")

            # 6. TLogic 规则挖掘（可解释层）
            rules = tlogic.mine_rules(
                train, min_support=s.tlogic_min_support,
                min_confidence=s.tlogic_min_confidence, max_len=s.tlogic_max_len,
            )
            out["tkg_rules"] = len(rules)
            self._write_jsonl(output_dir / "tkg_rules.jsonl", rules)

            # 7. 未来链接分（供融合）
            heads = list(dict.fromkeys(t["head"] for t in test))
            out["_tkg_scores"] = cygnet.future_link_scores(bundle, heads)
        except Exception as exc:  # noqa: BLE001 —— TKG 失败不阻断 Kleinberg/RotatE/回归
            log.exception("TKG 外推运行失败")
        return out

    # ------------------------------------------------------------------
    # P3：指标时序回归（目标③）
    # ------------------------------------------------------------------
    def _run_forecast(self, s, works, output_dir) -> dict:
        out = {
            "forecast_mae": None,
            "forecast_rmse": None,
            "forecast_mape": None,
            "_forecast_signal": {},
        }
        try:
            from techtrend.prediction import regression

            df = build_concept_monthly_counts(works, mode=s.burst_bin)
            if df.empty:
                log.warning("无 concept 频次数据，回归跳过")
                return out
            exclude = {c.strip() for c in s.openalex_concept_ids.split(",") if c.strip()}
            df = df.drop(index=[c for c in exclude if c in df.index])

            names = concept_names(works)
            res = regression.run_regression(
                df, horizon=s.forecast_horizon, min_history=s.forecast_min_history,
                top_k=s.forecast_top_k, lag=s.forecast_lag, names=names,
            )
            out["forecast_mae"] = res["mae"]
            out["forecast_rmse"] = res["rmse"]
            out["forecast_mape"] = res["mape"]

            if res["forecasts"]:
                pd.DataFrame(res["forecasts"]).to_csv(
                    output_dir / "forecast.csv", index=False, encoding="utf-8-sig"
                )
            # 未来增速信号（相对增速，供融合）
            for fc in res["forecasts"]:
                base = max(fc["recent_mean"], 1e-6)
                out["_forecast_signal"][fc["entity_id"]] = (fc["forecast"] - fc["recent_mean"]) / base
        except Exception as exc:  # noqa: BLE001
            log.exception("指标回归运行失败")
        return out

    # ------------------------------------------------------------------
    # P3：多信号融合（目标①集成）
    # ------------------------------------------------------------------
    def _run_fusion(self, s, works, tkg_scores, forecast_signal, output_dir) -> dict:
        out = {"fusion_precision_at_k": None, "fusion_recall_at_k": None, "fusion_top_k": []}
        try:
            from techtrend.prediction import fusion

            df = build_concept_monthly_counts(works, mode=s.burst_bin)
            if df.empty or df.shape[1] <= s.burst_future_months:
                log.warning("数据不足以融合评估，融合跳过")
                return out
            exclude = {c.strip() for c in s.openalex_concept_ids.split(",") if c.strip()}
            df = df.drop(index=[c for c in exclude if c in df.index])

            names = concept_names(works)

            # 第一路信号：相对份额动量（默认，救 p@k=0）或 Kleinberg 突发（消融对照）
            hist_df = df.iloc[:, : -s.burst_future_months]
            if s.fusion_signal_source == "kleinberg":
                burst_signal: dict[str, float] = {}
                for cid in hist_df.index:
                    series = hist_df.loc[cid].to_numpy(dtype=float)
                    bursts = kleinberg_bursts(series, s=s.burst_s, gamma=s.burst_gamma)
                    burst_signal[str(cid)] = max((b["weight"] for b in bursts), default=0.0)
            else:
                burst_signal = concept_share_momentum(hist_df)

            weights = fusion.parse_weights(s.fusion_weights)
            rows = fusion.fuse(
                burst_signal, tkg_scores, forecast_signal, weights, s.fusion_top_k, names=names
            )
            ranked = [r["entity"] for r in rows]
            truth = future_growth_top_k(df, s.burst_future_months, s.fusion_top_k)

            out["fusion_precision_at_k"] = precision_at_k(ranked, truth, s.fusion_top_k)
            out["fusion_recall_at_k"] = recall_at_k(ranked, truth, s.fusion_top_k)
            out["fusion_top_k"] = ranked

            pd.DataFrame(rows).to_csv(
                output_dir / "fusion_ranking.csv", index=False, encoding="utf-8-sig"
            )
            log.info("融合：top-%d = %s", len(ranked), ranked[:5])
        except Exception as exc:  # noqa: BLE001
            log.exception("融合运行失败")
        return out

    @staticmethod
    def _write_jsonl(path, rows) -> None:
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
