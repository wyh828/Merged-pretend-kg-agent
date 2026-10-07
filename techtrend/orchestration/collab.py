"""确定性多智能体协同（阶段 5 合并，核心突破点）。

两个独立「agent」对同一批候选技术实体各自打分，再交叉质证：

- **信号 agent**（热度加速）：Concept 级相对注意力份额 + EMA/MACD 动量
  （`techtrend.prediction.signal.concept_share_momentum`，阶段 1 引入，救 p@k=0）。
- **链接预测 agent**（新关联）：TKG 外推的未来链接分
  （`techtrend.prediction.cygnet.future_link_scores`，predict 的 `_tkg_scores` 同源）。

交叉质证把每个候选实体归入四类：
`agree`（两路都高）/ `signal_only`（信号高、链接低）/ `tkg_only`（链接高、信号低）/
`neither`（都低）。共识分 = 两路秩归一分加权求和；冲突 = signal_only + tkg_only。

全程确定性（不依赖 LLM），可复现可审计；LLM 化留作后续（README「后续优化」记录接口预留）。
"""
import json
import hashlib
import logging
from datetime import date

import pandas as pd

from techtrend.prediction.fusion import zscore_rank
from techtrend.prediction.kleinberg import build_concept_monthly_counts, concept_names

log = logging.getLogger(__name__)


def score_cache_payload(scores: dict, triples: list[dict], settings) -> dict:
    """Bind cached scores to historical facts and model parameters, without secrets."""
    fields = ("tkg_edge_source", "tkg_relation", "tkg_doc_types", "tkg_min_cooccur",
              "tkg_max_entities", "techpair_min_support", "techpair_relations",
              "tkg_train_ratio", "tkg_val_ratio", "tkg_embedding_dim", "tkg_epochs",
              "tkg_neg_samples", "tkg_alpha", "tkg_max_time")
    payload = {"facts": triples, "settings": {k: getattr(settings, k) for k in fields}}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return {"protocol_version": "causal_01", "input_digest": digest, "scores": scores}


def signal_agent_scores(works: list[dict], settings) -> dict[str, float]:
    """信号 agent：Concept 级相对份额动量分（[0,1]，与 predict `_run_share_signal` 同源）。"""
    from techtrend.prediction.signal import concept_share_momentum

    df = build_concept_monthly_counts(works, mode=settings.burst_bin)
    if df.empty or df.shape[1] <= settings.burst_future_months:
        return {}
    exclude = {c.strip() for c in settings.openalex_concept_ids.split(",") if c.strip()}
    df = df.drop(index=[c for c in exclude if c in df.index])
    hist_df = df.iloc[:, : -settings.burst_future_months]
    return concept_share_momentum(hist_df)


def link_agent_scores(triples: list[dict], settings) -> dict[str, float]:
    """链接预测 agent：TKG 外推的未来链接分（原始分，未归一）。

    优先读 predict 已缓存的 `output/tkg_scores.json`（同源、免重复训练）；缺文件时
    重新投影 + 训练 CyGNet 计算（自包含，供 `--stage collaborate` 单独运行）。
    失败（事实不足 / 训练异常）返回 {}（链接 agent 无意见）。
    """
    cache = settings.output_dir / "tkg_scores.json"
    if cache.exists():
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            expected = score_cache_payload({}, triples, settings)
            if cached.get("input_digest") == expected["input_digest"] and isinstance(cached.get("scores"), dict):
                return cached["scores"]
            log.info("TKG 缓存缺少可匹配的输入与参数记录，重新计算")
        except Exception as exc:  # noqa: BLE001
            log.warning("读 tkg_scores.json 失败（%s），重新计算", exc)

    try:
        from techtrend.prediction import cygnet, temporal as tp

        doc_types = {x.strip() for x in settings.tkg_doc_types.split(",") if x.strip()}
        max_time = settings.tkg_max_time or date.today().isoformat()
        if settings.tkg_edge_source == "directed":
            facts = tp.load_directed_edges(triples, relations=settings.techpair_relations.split(","), min_support=1, max_time=max_time)
        else:
            facts = tp.project_t2t(triples, relation=settings.tkg_relation, min_cooccur=1, max_entities=0, doc_types=doc_types, max_time=max_time)
        if len(facts) < 50:
            log.warning("投影事实过少（%d），链接预测 agent 无意见", len(facts))
            return {}
        train, val, test = tp.temporal_split_3way(
            facts, settings.tkg_train_ratio, settings.tkg_val_ratio,
        )
        scope = tp.fit_graph_scope(train, min_support=settings.techpair_min_support if settings.tkg_edge_source == "directed" else settings.tkg_min_cooccur, max_entities=settings.tkg_max_entities)
        train = tp.apply_graph_scope(train, scope, training=True)
        val = tp.apply_graph_scope(val, scope)
        test = tp.apply_graph_scope(test, scope)
        if not train or not test:
            log.warning("时态切分后 train/test 为空，链接预测 agent 无意见")
            return {}
        e2id, r2id, _id2e, _id2r = cygnet.encode_ids(train + val)
        bundle = cygnet.train_cygnet(
            train, val, dim=settings.tkg_embedding_dim, epochs=settings.tkg_epochs,
            neg_samples=settings.tkg_neg_samples, alpha=settings.tkg_alpha,
        )
        heads = list(dict.fromkeys(t["head"] for t in train + val))
        return cygnet.future_link_scores(bundle, heads)
    except Exception as exc:  # noqa: BLE001 —— 链接 agent 失败不阻断信号 agent
        log.exception("链接预测 agent 计算失败")
        return {}


def cross_examine(
    signal_scores: dict[str, float],
    link_scores: dict[str, float],
    signal_weight: float = 0.5,
) -> tuple[list[dict], list[dict]]:
    """两路独立分 → 秩归一 → 分类 + 共识排序。返回 (consensus_rows, conflicts)。

    阈值：秩归一分 ≥ 0.5 视为「高」（= 该路排序前 50%）；确定性、可复现。
    """
    s_rank = zscore_rank(signal_scores)
    l_rank = zscore_rank(link_scores)
    candidates = sorted(set(s_rank) | set(l_rank))

    rows: list[dict] = []
    for cid in candidates:
        sr = s_rank.get(cid, 0.0)          # 缺失信号视为低
        lr = l_rank.get(cid, 0.0)          # 缺失链接视为低
        has_s = cid in s_rank
        has_l = cid in l_rank

        if has_s and has_l:
            if sr >= 0.5 and lr >= 0.5:
                verdict = "agree"
            elif sr >= 0.5:
                verdict = "signal_only"
            elif lr >= 0.5:
                verdict = "tkg_only"
            else:
                verdict = "neither"
        elif has_s:
            verdict = "signal_only" if sr >= 0.5 else "neither"
        else:
            verdict = "tkg_only" if lr >= 0.5 else "neither"

        # 共识分：两路加权；缺一路时把缺失路权重折给有意见的一路（保持总分可比较）。
        w_s = (signal_weight if has_l else 1.0) if has_s else 0.0
        w_l = ((1.0 - signal_weight) if has_s else 1.0) if has_l else 0.0
        denom = w_s + w_l
        consensus = (w_s * sr + w_l * lr) / denom if denom > 0 else 0.0

        rows.append(
            {
                "concept": cid,
                "verdict": verdict,
                "signal_score": signal_scores.get(cid),
                "link_score": link_scores.get(cid),
                "signal_rank": sr,
                "link_rank": lr,
                "consensus": round(consensus, 6),
            }
        )

    rows.sort(key=lambda r: r["consensus"], reverse=True)
    conflicts = [r for r in rows if r["verdict"] in ("signal_only", "tkg_only")]
    return rows, conflicts


def collaborate(works: list[dict], triples: list[dict], settings) -> dict:
    """两个 agent 独立打分 → 交叉质证 → 共识 + 冲突。

    返回 {signal_n, link_n, agree, signal_only, tkg_only, neither, conflicts,
          consensus_rows, conflict_rows}（不写文件，由 CollaborateStage 落盘）。
    """
    from datetime import date
    max_time = settings.tkg_max_time or date.today().isoformat()
    works = [w for w in works if w.get("publication_date") and w["publication_date"] <= max_time]
    triples = [t for t in triples if t.get("time") and t["time"] <= max_time]
    signal_scores = signal_agent_scores(works, settings)
    monthly = build_concept_monthly_counts(works, mode=settings.burst_bin)
    as_of = str(monthly.columns[-settings.burst_future_months]) if monthly.shape[1] > settings.burst_future_months else None
    historical_triples = [t for t in triples if as_of and (t.get("time") or "") < as_of]
    link_scores = link_agent_scores(historical_triples, settings) if as_of else {}
    if not signal_scores and not link_scores:
        log.warning("两路 agent 均无输出，协同跳过")
        return {
            "signal_n": 0, "link_n": 0, "agree": 0, "signal_only": 0,
            "tkg_only": 0, "neither": 0, "conflicts": 0,
            "consensus_rows": [], "conflict_rows": [],
        }

    consensus_rows, conflicts = cross_examine(
        signal_scores, link_scores, settings.collab_signal_weight,
    )

    def _count(verdict: str) -> int:
        return sum(1 for r in consensus_rows if r["verdict"] == verdict)

    names = concept_names(works)
    for r in consensus_rows:
        r["name"] = names.get(r["concept"], "")
    for r in conflicts:
        r["name"] = names.get(r["concept"], "")

    summary = {
        "signal_n": len(signal_scores),
        "link_n": len(link_scores),
        "agree": _count("agree"),
        "signal_only": _count("signal_only"),
        "tkg_only": _count("tkg_only"),
        "neither": _count("neither"),
        "conflicts": len(conflicts),
        "prediction_kind": "historical_backtest",
        "as_of": as_of,
        "protocol_version": "causal_01",
        "consensus_rows": consensus_rows,
        "conflict_rows": conflicts,
    }
    log.info(
        "协同质证：signal=%d, link=%d, agree=%d, signal_only=%d, tkg_only=%d, neither=%d",
        summary["signal_n"], summary["link_n"], summary["agree"],
        summary["signal_only"], summary["tkg_only"], summary["neither"],
    )
    return summary


__all__ = ["collaborate", "signal_agent_scores", "link_agent_scores", "cross_examine"]
