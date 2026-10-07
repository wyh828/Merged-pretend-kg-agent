"""P4 验证体系：walk-forward 回测引擎 + purge/embargo 防泄漏 + 多期聚合。

四目标四类指标，每折独立切分、独立建模，最后聚合 mean ± std 与每折明细：

- 目标② TKG 外推：copy-only / CyGNet / RotatE（时态）filtered MRR / Hits@1/3/10
- 目标③ 回归：MAE / RMSE / MAPE（含 purge 剔除 label 与测试窗口重叠的训练样本）
- 目标① 排名：precision@k / recall@k（Kleinberg 突发信号 vs 未来增速 top-k 真值）
- leak_check：每折 train/test 时间不重叠 + embargo/purge 生效 + test 独有实体计数

与 predict 阶段职责分工：predict 保留单次 3-way 快指标（向后兼容 P1/P2/P3），
evaluate 是严谨多期回测，报告以 eval_report.md 为准。
"""
import logging
from typing import Callable, Iterable

import numpy as np
import pandas as pd

from techtrend.prediction.metrics import (
    mae,
    mape,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    rmse,
    spearman_rho,
    top1_lift,
)

log = logging.getLogger(__name__)

# 排名回测（目标①）聚合的键：主信号（相对份额动量）+ 消融（Kleinberg）
_RANK_KEYS = [
    "p_at_k", "r_at_k",
    "ndcg_at_3", "ndcg_at_5", "spearman_rho", "top1_lift",
    "kleinberg_p_at_k", "kleinberg_r_at_k",
]


# ---------------------------------------------------------------------------
# 时间窗口工具（月粒度，ISO 日期字符串可直接比较）
# ---------------------------------------------------------------------------
def _month_of(t) -> str:
    """ISO 时间 → 'YYYY-MM'（截取前 7 位）。"""
    return (t or "")[:7]


def _month_add(ym: str, n: int) -> str:
    """'YYYY-MM' 加减 n 个月。"""
    y, m = int(ym[:4]), int(ym[5:7])
    idx = y * 12 + (m - 1) + n
    yy, mm = divmod(idx, 12)
    return f"{yy:04d}-{mm + 1:02d}"


def rolling_origins(
    times: list[str], n_splits: int, test_months: int, step_months: int,
) -> list[tuple[str, str]]:
    """按时间生成 walk-forward 起点。返回 [(test_start, test_end)]（月字符串，升序）。

    最后一段 test 窗口的 test_end = max(time) + 1 月（右开区间），向前倒推 n_splits 段。
    """
    months = sorted({_month_of(t) for t in times if _month_of(t)})
    if not months:
        return []
    max_month = months[-1]
    origins: list[tuple[str, str]] = []
    test_end = _month_add(max_month, 1)  # 右开区间：最后一月也纳入最后一段 test
    for _ in range(n_splits):
        test_start = _month_add(test_end, -test_months)
        origins.append((test_start, test_end))
        test_end = _month_add(test_end, -step_months)
    origins.reverse()
    return origins


def walk_forward_splits(
    triples: list[dict],
    origins: list[tuple[str, str]],
    embargo_months: int,
    mode: str = "expanding",
    rolling_window_months: int = 24,
) -> list[tuple[list[dict], list[dict]]]:
    """每折 (train, test)。

    test = 时间 ∈ [test_start, test_end)；train = 时间 < test_start - embargo（embargo 缓冲）。
    expanding：train = 全部更早事实；rolling：train 仅取 [test_start - window, test_start - embargo)。
    """
    splits: list[tuple[list[dict], list[dict]]] = []
    for test_start, test_end in origins:
        train_cutoff = _month_add(test_start, -embargo_months)
        win_start = _month_add(test_start, -rolling_window_months)
        train: list[dict] = []
        test: list[dict] = []
        for t in triples:
            m = _month_of(t.get("time"))
            if not m:
                continue
            if test_start <= m < test_end:
                test.append(t)
            elif mode == "expanding":
                if m < train_cutoff:
                    train.append(t)
            else:  # rolling
                if win_start <= m < train_cutoff:
                    train.append(t)
        splits.append((train, test))
    return splits


# ---------------------------------------------------------------------------
# 无泄漏校验
# ---------------------------------------------------------------------------
def leak_check(folds: list[tuple[list[dict], list[dict]]]) -> dict:
    """校验每折 train/test 时间不重叠 + 统计 test 独有实体（train 未见）。

    返回 {ok, violations, test_only_entities_per_fold}。
    """
    violations: list[dict] = []
    test_only_per_fold: list[dict] = []
    checked_folds = 0
    for i, (train, test) in enumerate(folds):
        train_months = [_month_of(t.get("time")) for t in train if _month_of(t.get("time"))]
        test_months = [_month_of(t.get("time")) for t in test if _month_of(t.get("time"))]
        if train_months and test_months:
            checked_folds += 1
            max_train = max(train_months)
            min_test = min(test_months)
            if max_train >= min_test:
                violations.append(
                    {"fold": i, "max_train_month": max_train, "min_test_month": min_test}
                )
        train_entities = {t.get("head") for t in train} | {t.get("tail") for t in train}
        test_entities = {t.get("head") for t in test} | {t.get("tail") for t in test}
        test_only = test_entities - train_entities
        test_only_per_fold.append(
            {
                "fold": i,
                "test_only_entities": len(test_only),
                "test_entities": len(test_entities),
                "n_train": len(train),
                "n_test": len(test),
            }
        )
    return {
        "ok": not violations if checked_folds else None,
        "checked_folds": checked_folds,
        "scope": "fact_event_time_boundary_only; not_source_availability",
        "violations": violations,
        "test_only_entities_per_fold": test_only_per_fold,
    }


# ---------------------------------------------------------------------------
# 回归 purge
# ---------------------------------------------------------------------------
def purge_label_overlap(
    samples: list[tuple[int, float]], horizon: int, test_start_idx: int, purge: int,
) -> list[tuple[int, float]]:
    """剔除 label 窗口 [t, t+horizon) 与测试窗口重叠的训练样本。

    samples: [(t_idx, label)]，t_idx 为特征时间箱下标（lag 特征起点），label = mean(series[t:t+horizon])。
    保留条件：t + horizon <= test_start_idx - purge（右开标签窗口不与测试重叠）。
    """
    return [s for s in samples if s[0] + horizon <= test_start_idx - purge]


# ---------------------------------------------------------------------------
# 聚合
# ---------------------------------------------------------------------------
def _aggregate(fold_metrics: list[dict], keys: list[str]) -> dict:
    agg: dict = {"fold_metrics": fold_metrics, "n_folds": len(fold_metrics)}
    for k in keys:
        vals = [m.get(k) for m in fold_metrics if m.get(k) is not None]
        agg[f"{k}_mean"] = float(np.mean(vals)) if vals else None
        agg[f"{k}_std"] = float(np.std(vals)) if vals else None
    return agg


# ---------------------------------------------------------------------------
# 目标②：TKG 外推回测
# ---------------------------------------------------------------------------
def _tkg_fold(train: list[dict], test: list[dict], cfg: dict) -> dict | None:
    from techtrend.prediction import cygnet
    from techtrend.prediction.rotatE import run_rotate

    try:
        e2id, r2id, id2e, id2r = cygnet.encode_ids(train)
        history = cygnet.build_history(train, e2id, r2id)
        copy_metrics = cygnet.evaluate_copy_only(e2id, r2id, history, test, known_triples=train + test)

        bundle = cygnet.train_cygnet(
            train, [], dim=cfg["tkg_dim"], epochs=cfg["tkg_epochs"],
            neg_samples=cfg["tkg_neg"], alpha=cfg["tkg_alpha"],
        )
        cyg_metrics = cygnet.evaluate_cygnet(bundle, test, known_triples=train + test)

        rotate_metrics = run_rotate(
            train, test, dim=cfg["tkg_dim"], epochs=cfg["rotate_epochs"],
        )

        train_months = [_month_of(t.get("time")) for t in train if _month_of(t.get("time"))]
        test_months = [_month_of(t.get("time")) for t in test if _month_of(t.get("time"))]
        return {
            "tkg_mrr": cyg_metrics.get("mrr"),
            "tkg_hits_at_1": cyg_metrics.get("hits_at_1"),
            "tkg_hits_at_3": cyg_metrics.get("hits_at_3"),
            "tkg_hits_at_10": cyg_metrics.get("hits_at_10"),
            "copyonly_mrr": copy_metrics.get("mrr"),
            "rotate_mrr": rotate_metrics.get("filtered_mrr"),
            "rotate_hits_at_10": rotate_metrics.get("hits_at_10"),
            "n_train": len(train),
            "n_test": len(test),
            "train_end": max(train_months) if train_months else None,
            "test_start": min(test_months) if test_months else None,
            "test_end": max(test_months) if test_months else None,
        }
    except Exception as exc:  # noqa: BLE001 —— 单折失败跳过，不阻断整体
        log.exception("TKG 折回测失败")
        return None


def backtest_tkg(facts: list[dict], cfg: dict) -> dict:
    """每折跑 copy-only / CyGNet / RotatE（时态），聚合 MRR/Hits mean±std。"""
    origins = rolling_origins(
        [f["time"] for f in facts], cfg["n_splits"], cfg["test_months"], cfg["step_months"],
    )
    folds = walk_forward_splits(
        facts, origins, cfg["embargo_months"], cfg["mode"], cfg["rolling_window_months"],
    )
    fold_metrics: list[dict] = []
    from techtrend.prediction.temporal import fit_graph_scope, apply_graph_scope
    preprocessing = []
    for i, (train, test) in enumerate(folds):
        scope = fit_graph_scope(train, min_support=cfg.get("min_support", 1), max_entities=cfg.get("max_entities", 0))
        raw_train, raw_test = len(train), len(test)
        train = apply_graph_scope(train, scope, training=True)
        test = apply_graph_scope(test, scope)
        preprocessing.append({"fold": i, "fit_end": scope["fit_end"], "test_start": origins[i][0],
                              "fit_on": "train_only", "entities": len(scope["entities"]),
                              "raw_train": raw_train, "raw_test": raw_test,
                              "kept_train": len(train), "kept_test": len(test)})
        if len(train) < cfg["min_train"] or not test:
            log.warning(
                "TKG 折 %d 训练/测试事实不足，跳过（train=%d, test=%d）",
                i, len(train), len(test),
            )
            continue
        m = _tkg_fold(train, test, cfg)
        if m is not None:
            m["fold"] = i
            fold_metrics.append(m)
    result = _aggregate(
        fold_metrics,
        ["tkg_mrr", "tkg_hits_at_1", "tkg_hits_at_3", "tkg_hits_at_10",
         "copyonly_mrr", "rotate_mrr"],
    )
    result["origins"] = origins
    result["preprocessing"] = preprocessing
    log.info(
        "TKG 回测：%d/%d 折完成，tkg_mrr mean=%.4f±%.4f",
        len(fold_metrics), len(origins),
        result.get("tkg_mrr_mean") or 0.0, result.get("tkg_mrr_std") or 0.0,
    )
    return result


# ---------------------------------------------------------------------------
# 目标③：回归回测（含 purge）
# ---------------------------------------------------------------------------
def _regression_fold(monthly: pd.DataFrame, test_start: str, cfg: dict) -> dict | None:
    horizon = cfg["horizon"]
    lag = cfg["lag"]
    min_history = cfg["min_history"]
    top_k = cfg["top_k"]
    purge = cfg["purge"]
    cols = list(monthly.columns)
    if len(cols) < min_history + horizon:
        return None

    # 测试预测起点 = 第一个 >= test_start 的月份（右开区间外的第一个）
    t0 = next((j for j, c in enumerate(cols) if c >= test_start), None)
    if t0 is None or t0 < min_history or t0 + horizon > len(cols):
        return None  # 未来数据不足，跳过该折

    totals = monthly.iloc[:, :t0].sum(axis=1)
    totals = totals[totals > 0]
    selected = totals.sort_values(ascending=False).head(top_k).index.tolist()

    X_all: list[np.ndarray] = []
    y_all: list[float] = []
    test_feats: list[np.ndarray] = []
    test_actuals: list[float] = []

    for cid in selected:
        series = monthly.loc[cid].to_numpy(dtype=float)
        L = len(series)
        if L < min_history + horizon:
            continue
        # 训练样本：(t, label)，t ∈ [lag, L-horizon)
        samples = [
            (t, float(series[t : t + horizon].mean()))
            for t in range(lag, L - horizon)
        ]
        # purge：剔除 label 与测试窗口重叠的训练样本
        samples = purge_label_overlap(samples, horizon, t0, purge)
        for t, label in samples:
            X_all.append(series[t - lag : t])
            y_all.append(label)
        # 测试：预测 [t0, t0+horizon) 月均
        if t0 - lag < 0:
            continue
        test_feats.append(series[t0 - lag : t0])
        test_actuals.append(float(series[t0 : t0 + horizon].mean()))

    if len(X_all) < 2 or not test_feats:
        return None

    from sklearn.ensemble import HistGradientBoostingRegressor

    X = np.asarray(X_all, dtype=np.float32)
    y = np.asarray(y_all, dtype=np.float32)
    model = HistGradientBoostingRegressor(max_iter=200, random_state=42)
    model.fit(X, y)
    preds = model.predict(np.asarray(test_feats, dtype=np.float32)).tolist()

    return {
        "mae": mae(test_actuals, preds),
        "rmse": rmse(test_actuals, preds),
        "mape": mape(test_actuals, preds),
        "n_train_samples": len(X_all),
        "n_test_entities": len(test_feats),
        "selected_entities": [str(cid) for cid in selected],
        "selection_end": cols[t0 - 1],
        "train_label_end_exclusive": cols[t0 - purge] if t0 - purge >= 0 else None,
    }


def backtest_regression(monthly: pd.DataFrame, cfg: dict) -> dict:
    """walk-forward MAE/RMSE/MAPE（含 purge），聚合 mean±std。"""
    if monthly.empty:
        log.warning("月度频次矩阵为空，回归回测跳过")
        return _aggregate([], ["mae", "rmse", "mape"])
    cols = list(monthly.columns)
    horizon = cfg["horizon"]
    n_splits = cfg["n_splits"]
    step = max(1, cfg["step_months"])
    # 回归预测的是 [test_start, test_start+horizon) 的未来 horizon 月（列），预测起点 t0
    # 必须满足 t0+horizon <= len(cols)，否则越界导致所有折被跳过（rolling_origins 锚在
    # 最后一月，落在未来无数据处）。因此 origin 锚定在最后一个合法预测起点 len(cols)-horizon，
    # 向前按 step 个日历月回退；矩阵构建已补齐事件缺月，数据覆盖另行记录。
    last_t0 = len(cols) - horizon
    t0s = [last_t0 - i * step for i in range(n_splits) if last_t0 - i * step >= 0]
    origins = [(cols[t0], None) for t0 in reversed(t0s)]
    fold_metrics: list[dict] = []
    for i, (test_start, _test_end) in enumerate(origins):
        m = _regression_fold(monthly, test_start, cfg)
        if m is not None:
            m["fold"] = i
            m["test_start"] = test_start
            fold_metrics.append(m)
    result = _aggregate(fold_metrics, ["mae", "rmse", "mape"])
    log.info(
        "回归回测：%d/%d 折完成，RMSE mean=%.4f±%.4f",
        len(fold_metrics), len(origins),
        result.get("rmse_mean") or 0.0, result.get("rmse_std") or 0.0,
    )
    return result


# ---------------------------------------------------------------------------
# 目标①：排名回测
# ---------------------------------------------------------------------------
def _ranking_fold(
    monthly: pd.DataFrame, test_start: str, test_end: str, cfg: dict,
) -> dict | None:
    from techtrend.prediction.kleinberg import (
        detect_top_bursts,
        future_activity,
        future_growth_top_k,
    )
    from techtrend.prediction.signal import share_momentum_rank

    cols = list(monthly.columns)
    hist_cols = [c for c in cols if c < test_start]
    fut_cols = [c for c in cols if test_start <= c < test_end]
    if not hist_cols or not fut_cols:
        return None
    top_k = cfg["top_k"]

    hist_df = monthly[hist_cols]
    hist_df = hist_df.loc[hist_df.sum(axis=1) > 0]
    if hist_df.empty:
        return None
    combined = monthly.loc[hist_df.index, hist_cols + fut_cols]
    n_fut = len(fut_cols)

    # 消融基线：Kleinberg 突发排名（目标①原信号，p@k=0 的来源）
    bursts = detect_top_bursts(
        hist_df, top_k, s=cfg["burst_s"], gamma=cfg["burst_gamma"],
    )
    kleinberg_ranked = bursts["concept"].tolist()
    truth = future_growth_top_k(combined, n_fut, top_k)

    # 主信号：相对份额动量排名（阶段 1 合并，替换 Kleinberg）
    share_ranked = share_momentum_rank(hist_df, top_k)

    # 排序类指标真值：未来活跃度（非负，Spearman/NDCG/Top-1 Lift 用）
    relevance = future_activity(combined, n_fut)
    share_scores = share_momentum_scores(hist_df)

    return {
        # 主信号（相对份额动量）
        "p_at_k": precision_at_k(share_ranked, truth, top_k),
        "r_at_k": recall_at_k(share_ranked, truth, top_k),
        "ndcg_at_3": ndcg_at_k(share_ranked, relevance, 3),
        "ndcg_at_5": ndcg_at_k(share_ranked, relevance, 5),
        "spearman_rho": spearman_rho(share_scores, relevance),
        "top1_lift": top1_lift(share_ranked, relevance),
        # 消融基线（Kleinberg）
        "kleinberg_p_at_k": precision_at_k(kleinberg_ranked, truth, top_k),
        "kleinberg_r_at_k": recall_at_k(kleinberg_ranked, truth, top_k),
        "n_hist_months": len(hist_cols),
        "n_test_months": len(fut_cols),
        "candidate_scope": "entities_observed_before_origin",
        "cold_start_entities": int((monthly[hist_cols].sum(axis=1) == 0).sum()),
    }


def share_momentum_scores(df: pd.DataFrame) -> dict[str, float]:
    """概念 → 相对份额动量分（供 Spearman 用完整分数，而非仅 top-k 列表）。"""
    from techtrend.prediction.signal import concept_share_momentum

    return concept_share_momentum(df)


def backtest_ranking(monthly: pd.DataFrame, cfg: dict) -> dict:
    """每折相对份额动量（主）+ Kleinberg（消融）排名 vs 未来真值，聚合排序类指标。"""
    if monthly.empty:
        log.warning("月度频次矩阵为空，排名回测跳过")
        return _aggregate([], _RANK_KEYS)
    cols = list(monthly.columns)
    origins = rolling_origins(cols, cfg["n_splits"], cfg["test_months"], cfg["step_months"])
    fold_metrics: list[dict] = []
    for i, (test_start, test_end) in enumerate(origins):
        m = _ranking_fold(monthly, test_start, test_end, cfg)
        if m is not None:
            m["fold"] = i
            m["test_start"] = test_start
            fold_metrics.append(m)
    result = _aggregate(fold_metrics, _RANK_KEYS)
    log.info(
        "排名回测：%d/%d 折完成，share p@k mean=%.4f±%.4f，NDCG@3 mean=%.4f，"
        "Spearman ρ mean=%.4f，Top-1 Lift mean=%s",
        len(fold_metrics), len(origins),
        result.get("p_at_k_mean") or 0.0, result.get("p_at_k_std") or 0.0,
        result.get("ndcg_at_3_mean") or 0.0,
        result.get("spearman_rho_mean") or 0.0,
        result.get("top1_lift_mean"),
    )
    return result
