"""指标时序回归（目标③）：per-Concept 月度活动序列 → 未来 horizon 月月均预测。

用 sklearn `HistGradientBoostingRegressor`（轻量替代 XGBoost，不新增依赖）。
数据复用 :func:`techtrend.prediction.kleinberg.build_concept_monthly_counts` 产出的
Concept × 月频次矩阵。指标口径：以「活动量（月度被提及/发表频次）」作为引用数/star/
专利量的可计算代理。
"""
import logging

import numpy as np
import pandas as pd

from techtrend.prediction.metrics import mae, mape, rmse

log = logging.getLogger(__name__)


def build_lag_features(series: pd.Series, lag: int) -> pd.DataFrame:
    """滞后特征（前 lag 月活动量），返回 DataFrame[lag_1..lag_k]，index=起始时间箱。

    第 t 行（时间箱 t）特征 = series[t-lag .. t-1]（不含 t），供预测 t 起未来 horizon 月。
    """
    vals = series.to_numpy(dtype=float)
    index = list(series.index)
    rows = [vals[t - lag : t] for t in range(lag, len(vals))]
    cols = [f"lag_{i}" for i in range(1, lag + 1)]
    return pd.DataFrame(rows, index=index[lag:], columns=cols)


def run_regression(
    monthly: pd.DataFrame,
    horizon: int = 6,
    min_history: int = 12,
    top_k: int = 100,
    lag: int = 6,
    names: dict[str, str] | None = None,
) -> dict:
    """对最活跃 top-k 个 Concept 的月度活动序列做回测。

    预测起点为 N-horizon；训练特征及其完整标签均截止于该起点之前，
    候选实体也仅按该起点之前的活动量选择（跨实体共享一个模型）。
    预测「后 horizon 月月均」，与真实值比对得 MAE/RMSE/MAPE（聚合，逐实体见 forecasts）。
    返回 {"mae","rmse","mape","forecasts":[{entity_id,name,recent_mean,forecast,actual}]}。
    """
    names = names or {}
    empty = {"mae": None, "rmse": None, "mape": None, "forecasts": []}
    if monthly.empty:
        log.warning("月度频次矩阵为空，回归跳过")
        return empty
    if monthly.shape[1] < min_history + horizon:
        log.warning(
            "时间箱仅 %d 个（需 ≥ %d = min_history+horizon），回归跳过",
            monthly.shape[1], min_history + horizon,
        )
        return empty

    from sklearn.ensemble import HistGradientBoostingRegressor

    # Forecast origin is before the held-out horizon. Entity selection and
    # every training label must be observable strictly before this origin.
    origin = monthly.shape[1] - horizon
    if origin < lag or horizon < 1 or lag < 1:
        return empty
    totals = monthly.iloc[:, :origin].sum(axis=1)
    totals = totals[totals > 0]
    selected = totals.sort_values(ascending=False).head(top_k).index.tolist()

    X_all: list[np.ndarray] = []
    y_all: list[float] = []
    test_feats: list[np.ndarray] = []
    test_cids: list[str] = []
    test_actuals: list[float] = []
    test_recent: list[float] = []

    for cid in selected:
        series = monthly.loc[cid].to_numpy(dtype=float)
        L = len(series)
        if L < min_history + horizon:
            continue
        # A label [t, t+horizon) is known only when t+horizon <= origin.
        for t in range(lag, origin - horizon + 1):
            X_all.append(series[t - lag : t])
            y_all.append(float(series[t : t + horizon].mean()))
        # 测试窗口：预测最后 horizon 月月均
        test_feats.append(series[L - horizon - lag : L - horizon])
        test_cids.append(str(cid))
        test_actuals.append(float(series[L - horizon : L].mean()))
        test_recent.append(float(series[origin - lag : origin].mean()))

    if len(X_all) < 2 or not test_feats:
        log.warning("有效回归样本不足（train=%d, test=%d），回归跳过", len(X_all), len(test_feats))
        return empty

    X = np.asarray(X_all, dtype=np.float32)
    y = np.asarray(y_all, dtype=np.float32)
    model = HistGradientBoostingRegressor(max_iter=200, random_state=42)
    model.fit(X, y)

    X_test = np.asarray(test_feats, dtype=np.float32)
    preds = model.predict(X_test).tolist()

    forecasts = [
        {
            "entity_id": cid,
            "name": names.get(cid, ""),
            "recent_mean": recent,
            "forecast": p,
            "actual": a,
        }
        for cid, recent, p, a in zip(test_cids, test_recent, preds, test_actuals)
    ]

    result = {
        "mae": mae(test_actuals, preds),
        "rmse": rmse(test_actuals, preds),
        "mape": mape(test_actuals, preds),
        "forecasts": forecasts,
        "audit": {"origin": str(monthly.columns[origin]),
                  "selection_end": str(monthly.columns[origin - 1]),
                  "train_label_end_exclusive": str(monthly.columns[origin]),
                  "selected_entities": [str(cid) for cid in selected]},
    }
    log.info(
        "指标回归：top-%d 实体（%d 可预测）→ MAE=%.4f, RMSE=%.4f, MAPE=%.4f",
        top_k, len(forecasts), result["mae"], result["rmse"], result["mape"],
    )
    return result
