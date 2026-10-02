> 本机适配说明：工程路径已改为 `F:/Predictive agents`；以下阶段设计与实验数字仍为上游历史记录。本机执行结果见 README 的「本机修订 00」。

# P3 时序预测 —— 完整构建计划

## Context（为什么做这件事）

P2 已交付「多源 + 动态 KG + 实体对齐」：六源采集 → 结构化 + LLM 抽取 → 跨源对齐 → Neo4j 四元组落库，链接预测 **MRR 0.2734 / Hits@10 0.3746**（仍为 P1 的 RotatE 静态基线，跑在更大图上）。P3 按 PROJECT_PLAN 七「分阶段路线图」推进第一个真正**有时序维度**的预测阶段：

- **目标**：CyGNet（复制机制）时序外推 + TLogic 可解释规则 + 多信号融合，并补上目标③「指标时序外推」（回归）。
- **验收标准**（计划书原文）：**外推 MRR/Hits 优于静态基线**。
- **范围**：预测层从「静态 KG 补全」升级为「时序 KG 外推」；数据层/图谱层不变（P2 已固化四元组 + 时间戳）。S 曲线阶段（目标④）留 P6。

### 已确认关键决策

| 项 | 结论 | 依据 |
|---|---|---|
| 主干模型 | **CyGNet**（复制机制，契合技术演化重复性）+ **TLogic**（可解释规则层） | PROJECT_PLAN 4.2(2) |
| TKG 数据来源 | 现图谱只有 **doc→tech** 边（Paper/Patent/Repo/News 作头，技术实体作尾），无 tech→tech 边。P3 从 `triples.jsonl` **投影**出持久实体共现边 `relates_to`（Concept×Concept，时间=文档时间） | 本计划（对齐后技术实体已折叠为 `Concept`，见 P2_PLAN 对齐折叠） |
| 时态切分 | train < val < test 时间不重叠（3-way），禁止 shuffle | PROJECT_PLAN 5.1 |
| 评估口径 | TKG 外推 filtered MRR/Hits；**同时跑 RotatE(随机切分) 与 RotatE(时态切分) 两个对照**，CyGNet 须 > RotatE(时态切分)——比「大于静态基线」更严格的同协议对比 | 本计划（rotatE.py 的 `temporal_split` 早已预留，P3 正式启用） |
| 目标③回归 | per-Concept 月度活动序列 + sklearn `HistGradientBoostingRegressor`（轻量替代 XGBoost，不新增依赖） | PROJECT_PLAN 4.2(4)/4.3 + 范围控制 |
| 融合 | Kleinberg 突发 + TKG 分 + 回归增速 → z-score/秩归一 + 加权排名（目标①集成） | PROJECT_PLAN 4.3 |
| 范围控制 | Tier1：TLogic 规则 + copy-only 启发式基线先跑通；Tier2：完整 CyGNet 达验收 | PROJECT_PLAN 七「范围控制」 |
| 数据读取 | 预测层仍从 `data/interim/{triples,nodes}.jsonl` 读（**不直接读 Neo4j**），与 P1/P2 一致、predict 不依赖 Neo4j 在线 | rotatE.py 现有做法 + PROJECT_PLAN 3.1 |
| 目标④ S 曲线 | 留 P6（趋势图 + S 曲线阶段 + 周报） | PROJECT_PLAN 七 roadmap |

---

## 目录结构（P3 新增/改动）

```
techtrend/
  config.py                 # 改：新增 TKG / TLogic / 回归 / 融合参数
  prediction/
    __init__.py             # 改：导出 temporal/cygnet/tlogic/regression/fusion
    kleinberg.py            # 复用（不改）
    metrics.py              # 改：+ mrr_at/hits_at（TKG 过滤排名）+ mae/rmse/mape（回归）
    rotatE.py               # 复用（静态基线；temporal_split 由 P3 正式启用）
    temporal.py             # 新：投影 + 时态切分 + 实体/关系编码（TKG 数据准备）
    cygnet.py               # 新：CyGNet 模型（copy+generate）+ copy-only 基线
    tlogic.py               # 新：时序逻辑规则挖掘 + 候选打分（可解释层）
    regression.py           # 新：指标时序回归（目标③）
    fusion.py               # 新：多信号融合排名（目标①集成）
  stages/
    predict.py              # 改：PredictStage 在 Kleinberg/RotatE 之外，追加 TKG + 回归 + 融合
    report.py               # 改：报告加 TKG/回归/融合指标段落（读 temporal_metrics.json）
```

`pipeline.py` 阶段顺序不变（`predict` 仍是第 5 阶段）；仅把日志措辞「P2」改「P3」。`main.py` argparse description 同步。

---

## 数据流与阶段接口契约

六阶段顺序不变：`collect → extract → align → build_graph → predict → report`。前四阶段（P2 已交付）**不改**；P3 只动 `predict`/`report` 与 `prediction/` 包。

### predict 阶段数据流（P3 扩展）

```
triples.jsonl（对齐后：head_id/tail_id/time/source）
  │
  ├─(1) Kleinberg 突发 ──────────────────────────────► precision@k / recall@k（沿用 P1/P2）
  ├─(2) RotatE 静态基线（随机切分 + 时态切分两对照）────► filtered MRR/Hits@1/3/10（沿用 + 新增时态对照）
  │
  ├─(3) TKG 外推 ── temporal.project_t2t → 时态 3-way 切分 → CyGNet / TLogic
  │                └─────────────────────────────────► tkg filtered MRR/Hits@1/3/10 + 规则表
  ├─(4) 指标时序回归 ── build_concept_monthly_counts → regression.run_regression
  │                └─────────────────────────────────► forecast MAE/RMSE/MAPE + forecast.csv
  └─(5) 融合 ── Kleinberg 突发 + TKG 分 + 回归增速 → fusion.fuse
                   └─────────────────────────────────► fusion_precision@k / recall@k + fusion_ranking.csv
```

### 输出文件（output/）

| 文件 | 内容 | 阶段 |
|---|---|---|
| `baseline_metrics.json` | Kleinberg + RotatE（沿用 P1/P2，**不破坏向后兼容**） | predict |
| `burst_concepts.csv` | Kleinberg 突发 top-k（沿用） | predict |
| `temporal_metrics.json` | **P3 新增**：TKG filtered MRR/Hits、回归 MAE/RMSE/MAPE、融合 precision@k/recall@k | predict |
| `tkg_rules.jsonl` | 挖掘出的时序规则（头/体/置信度/支持度） | predict |
| `forecast.csv` | per-Concept 未来 `forecast_horizon` 月预测值 | predict |
| `fusion_ranking.csv` | 融合排名（entity_id / 名 / 各分 / 总排序分） | predict |
| `report.md` | 汇总（读 baseline + temporal 两 json） | report |

### predict 阶段 run() 返回 dict 契约（扩展）

```python
{
  "stage": "predict", "status": "ok",
  # Kleinberg（沿用）
  "precision_at_k": ..., "recall_at_k": ..., "burst_top_k": [...],
  # RotatE 静态基线（沿用；新增时态切分对照字段）
  "filtered_mrr": ..., "hits_at_1/3/10": ...,
  "rotate_temporal_mrr": ..., "rotate_temporal_hits_at_10": ...,
  # TKG 外推（新）
  "tkg_filtered_mrr": ..., "tkg_hits_at_1/3/10": ...,
  "tkg_train_triples": N, "tkg_val_triples": V, "tkg_test_triples": T,
  "tkg_rules": K,
  "tkg_copyonly_mrr": ...,        # copy-only 基线对照
  # 回归（新）
  "forecast_mae": ..., "forecast_rmse": ..., "forecast_mape": ...,
  # 融合（新）
  "fusion_precision_at_k": ..., "fusion_recall_at_k": ...,
}
```

仍经 `pipeline.py` 顺序串行；`predict` 内各子任务各自 try/except（TKG 训练失败不阻断 Kleinberg/RotatE 结果，延续 predict.py 现有防御风格）。

### 关键数据变换：持久实体投影（P3 的核心数据工作）

对齐后，LLM 抽取的技术实体已被 `alignment.py` 折叠为 `Concept`（Technology/Method/Model/Framework/Dataset→Concept；Institution→Institution；Person→Author），见 `_MATCH_TARGET`。故「技术间关联」落到 **Concept×Concept** 共现边：

- 输入 `triples.jsonl` 中 `head_type ∈ {Paper,Patent,Repo,News}` 且 `tail_type == Concept` 的行 → 按 `head`（文档）分组，同一文档内出现的 Concept 两两成**无向**边 `relates_to`，`time = 文档 time`。
- 计数后仅保留共现次数 ≥ `tkg_min_cooccur` 的边（降噪、控规模）；按度截断至 `tkg_max_entities`（控训练规模）。
- 输出事实流 `(head, relates_to, tail, time)`，端点均为持久 `entity_id`（Concept），满足 TKG「实体跨时间重复出现」的要求。

> **诚实声明**：`relates_to` 是「同文档共现」的**关联代理**，不是经 LLM 验证的 uses/improves 定向关系。这是本数据粒度下能无成本得到的「技术间关联」。若需定向关系，可在 P3 之后追加一次 LLM 技术对抽取（见「风险与注意」），不阻塞本阶段验收。

---

## 配置扩展（config.py + .env.example）

`Settings` 新增字段（无新密钥；`.env.example` 仅补注释段说明）：

```python
# ---- 时序预测（P3）----
# TKG 外推（CyGNet / TLogic）
predict_enable_tkg: bool = True
tkg_relation: str = "relates_to"     # 投影边关系名
tkg_min_cooccur: int = 2             # 投影边最小共现次数（降噪）
tkg_max_entities: int = 5000         # 按度截断，控 TKG 规模
tkg_train_ratio: float = 0.7
tkg_val_ratio: float = 0.1           # test = 1 - train - val
tkg_embedding_dim: int = 128
tkg_epochs: int = 30
tkg_neg_samples: int = 10            # 每条正例的负采样数
tkg_alpha: float = 0.5               # copy vs generate 融合权重（亦可训练）

# TLogic 规则层
tlogic_min_support: int = 5
tlogic_min_confidence: float = 0.3
tlogic_max_len: int = 3              # 规则体原子数上限

# 指标时序回归（目标③）
forecast_horizon: int = 6            # 预测未来月数
forecast_min_history: int = 12       # 最少历史箱数
forecast_top_k: int = 100            # 只对最活跃 top-k 实体做回归
forecast_lag: int = 6                # 滞后特征窗口

# 融合（目标①集成）
fusion_weights: str = "burst=0.3,tkg=0.4,forecast=0.3"  # 逗号分隔 name=weight
fusion_top_k: int = 10
```

---

## 依赖变更（requirements.txt）

**不新增依赖**：CyGNet/TLogic 自实现（torch/numpy 已装）；回归用 sklearn `HistGradientBoostingRegressor`（scikit-learn 已装）；torch 已于 P1 安装（CPU 版即可）。

- 若后续想换原生 XGBoost，可加 `xgboost>=2.0`（**P3 默认不装**，sklearn 轻量替代满足要求）。

---

## 各模块详细设计

### 1. prediction/temporal.py —— TKG 数据准备

```python
PERSISTENT_TYPES = ("Concept",)   # 对齐后技术实体折叠为 Concept；可扩展 ("Concept","Institution")

def project_t2t(triples: Iterable[dict], relation: str = "relates_to",
                min_cooccur: int = 2, max_entities: int = 5000) -> list[dict]:
    """doc→Concept 三元组 → Concept×Concept 共现事实流。

    按 head（文档）分组，同一文档内 Concept 两两成边（无向），time=文档 time；
    计数后仅保留 ≥ min_cooccur 的边；按度截断至 max_entities 后只保留端点都在内的边。
    返回 [{"head":entity_id, "relation":relation, "tail":entity_id, "time":iso}]。
    """

def temporal_split_3way(triples: list[dict], train_ratio: float = 0.7,
                        val_ratio: float = 0.1) -> tuple[list, list, list]:
    """按 time 升序切 train/val/test 三段，时间不重叠（禁止 shuffle）。
    复用/取代 rotatE.temporal_split 的 2-way 版本。"""

def encode_entities(triples: Iterable[dict]) -> tuple[dict[int, str], dict[str, int]]:
    """实体 → 连续 id（供 torch 索引）。"""
```

- 复用 rotatE.py 已预留的 `temporal_split`（P3 正式启用），扩展为 3-way 加 val 段。
- 时态切分是「外推」的语义核心：train 只含早期事实，test 是未来窗口的事实，模型从未见过 test 时间段的任何事实（P4 再补 purge/embargo 与 walk-forward，P3 先保证时间不重叠）。

### 2. prediction/cygnet.py —— CyGNet 复制机制（目标②主干）

```python
def build_history(train: list[dict], e2id) -> dict[tuple[int, int], Counter]:
    """(s, r) → 历史 tail 频次（CyGNet 的 copy 词表）。"""

def copy_only_score(s, r, o, history, id2e) -> float:
    """Tier1 基线：仅复制历史——tail 在 (s,r) 历史中的频次 + 时间衰减（近者权重高）。
    无历史则 0。这是 CyGNet「copy mode」的确定性退化版，先跑通拿第一个时态 MRR。"""

class CyGNet(nn.Module):
    """复制 + 生成混合打分（自实现，参考 Zhu 2021 AAAI）。
    - entity_emb / relation_emb：生成模式，s 与 r 的组合嵌入与候选 o 打分。
    - copy：由 (s,r) 历史词表经注意力/频次加权得到 copy 分布。
    - 融合：score = α·copy + (1-α)·generate（α 可固定 tkg_alpha 或可训练）。
    """

def train_cygnet(train, val, dim, epochs, neg_samples, alpha) -> CyGNet:
    """负采样训练（每条正例采 neg_samples 个非真 tail）；val 上早停选最优 α/轮次。"""

def evaluate_tkg(score_fn, test, all_entities, known_tails, k=(1, 3, 10)) -> dict:
    """filtered 排名评估：对每条 (s,r,o,t)，o 与所有实体打分，
    剔除 (s,r) 在 train/val/test 中已存在的其它真 tail（filtered），
    返回 MRR + Hits@1/3/10。"""
```

- **CyGNet 契合点**：技术演化高度重复——同一技术反复与同类技术关联，复制机制能捕捉「历史关联再现」，优于纯静态嵌入。
- **评估口径**：`known_tails` = 该 (s,r) 在**全部时间段**出现过的 tail 集合（剔除后排名），与 pykeen filtered 语义一致。
- **两个对照**：① `copy_only_score`（Tier1 确定性基线）；② RotatE 时态切分（静态模型在相同时态切分下的指标，来自 rotatE.py + `temporal_split`）。验收要求 CyGNet > ②。

### 3. prediction/tlogic.py —— 时序规则层（可解释）

```python
def mine_rules(train: list[dict], min_support: int = 5,
               min_confidence: float = 0.3, max_len: int = 3) -> list[dict]:
    """挖掘时序规则：(X,r1,Y,T1) ∧ (Y,r2,Z,T2) → (X,r3,Z,T3)，T1<T3 且 T2<T3。
    单关系 relates_to 下退化为长度 2/3 的传递性/三角规则；
    置信度 = 规则支持 / 体支持。返回 [{"body","head","support","confidence"}]。"""

def score_candidates(s: str, r: str, rules: list[dict], graph, t: str) -> dict[str, float]:
    """对查询 (s,r,?,t)，沿规则做带时间约束的图游走，取匹配规则置信度之和为候选分。"""
```

- 输出 `tkg_rules.jsonl`（可解释：哪些技术关联模式反复出现），既是打分器也是可读解释。
- 单关系下规则空间有限，但满足「可解释规则层」验收与后续报告引用。

### 4. prediction/regression.py —— 指标时序回归（目标③）

```python
def build_lag_features(series: pd.Series, lag: int) -> pd.DataFrame:
    """滞后特征（前 lag 月活动量 → 未来 horizon 月均值）。"""

def run_regression(monthly: pd.DataFrame, horizon: int, min_history: int,
                   top_k: int, lag: int) -> dict:
    """对最活跃 top-k 个 Concept 的月度活动序列做回测：
    用前 N-horizon 月训 HistGradientBoosting（lag 特征），预测后 horizon 月月均，
    与真实值比对得 MAE/RMSE/MAPE（聚合 + 逐实体）。
    返回 {"mae","rmse","mape","forecasts":[...]}。"""
```

- **数据复用**：`kleinberg.build_concept_monthly_counts(works, mode="month")` 已产出 `Concept × 月` 频次矩阵，直接作为逐实体时序。
- **指标口径**：以「活动量（月度被提及/发表频次）」作为引用数/star/专利量的可计算代理（见「风险与注意」：`cited_by_count` 当前未入 works.jsonl，如需真引用数可在 openalex.normalize 补该字段再按概念聚合月均）。
- 输出 `forecast.csv`（entity_id / 最近历史 / 未来预测 / 真实值）。

### 5. prediction/fusion.py —— 多信号融合（目标①集成）

```python
def zscore_rank(scores: dict[str, float]) -> dict[str, float]:
    """按秩归一（处理缺失：缺省 0）。"""

def fuse(burst: dict[str, float], tkg: dict[str, float],
         forecast: dict[str, float], weights: dict[str, float],
         top_k: int) -> list[dict]:
    """三路信号 zscore_rank 后加权求和 → 排序 top_k。
    burst：Kleinberg 突发权重；tkg：CyGNet 对该实体的未来链接概率；
    forecast：回归预测的未来增速。返回 [{"entity","name","score","burst","tkg","forecast"}]。"""
```

- 融合真值沿用 `future_growth_top_k`（未来窗口增速 top-k），得 `fusion_precision@k / recall@k`，可与 P2 的 Kleinberg 单独 `precision@k=0` 对比，验证融合是否改善新兴识别。

### 6. prediction/metrics.py 扩展

```python
def mrr_at(ranks: list[int]) -> float          # 1/rank 均值
def hits_at(ranks: list[int], k: int) -> float # rank ≤ k 的比例
def mae(actual, pred) -> float
def rmse(actual, pred) -> float
def mape(actual, pred) -> float                # 0 真值跳过，防除零
```

### 7. stages/predict.py 改造

- `run()` 在现有 `_run_kleinberg` / `_run_rotate` 之后，追加三个私有方法，各自 try/except 不互阻：
  - `_run_rotate_temporal(s, triples)`：RotatE 用**时态切分**再跑一次（对照 ②），产出 `rotate_temporal_mrr/hits_at_10`（时态切分下 test 若空则置 None 并 warning，同 rotatE.py 现有逻辑）。
  - `_run_tkg(s, triples)`：`project_t2t → temporal_split_3way → copy_only 基线 → CyGNet 训练/评估 → TLogic 规则`，写 `temporal_metrics.json` 的 TKG 段 + `tkg_rules.jsonl`。数据不足（投影边/实体过少、test 空）时置 None 并 warning。
  - `_run_forecast(s, works)` + `_run_fusion(s, works, tkg_scores)`：回归 + 融合，写 `temporal_metrics.json` 的回归/融合段 + `forecast.csv` / `fusion_ranking.csv`。
- `baseline_metrics.json` 仍写 Kleinberg + RotatE（随机切分）——**向后兼容 report.py 与 P1/P2 验收**；新增 `temporal_metrics.json` 承载 P3 指标。

### 8. stages/report.py 改造

- 标题「P2 基线报告」→「P3 时序预测报告」。
- 追加两段（读 `temporal_metrics.json`，缺失时跳过不报错）：
  - **时序链接预测外推**：TKG filtered MRR/Hits@1/3/10、copy-only 基线、RotatE 时态对照、规则数；附「是否优于静态基线」的结论行。
  - **指标时序回归 + 融合**：MAE/RMSE/MAPE、fusion precision@k/recall@k、融合 top-k 列表。

---

## 实施顺序（任务分解）

1. `config.py` + `.env.example` 补 P3 段（无新依赖安装）。
2. `prediction/temporal.py`（投影 + 3-way 切分）→ 单测：投影边数量、train/val/test 时间不重叠、实体持久性（同一实体跨 train/test 出现）。
3. `prediction/metrics.py` 加 `mrr_at/hits_at/mae/rmse/mape`。
4. `prediction/cygnet.py` 的 `copy_only_score` + `evaluate_tkg` → **Tier1 先跑通**：拿到第一个时态 filtered MRR/Hits。
5. `prediction/tlogic.py` 规则挖掘 → `tkg_rules.jsonl` 可读规则 + 规则打分。
6. `prediction/cygnet.py` 完整 CyGNet（copy+generate，负采样训练）→ **Tier2 达验收**：`tkg_filtered_mrr` 优于 RotatE 时态对照。
7. `prediction/regression.py` → `forecast_mae/rmse/mape` + `forecast.csv`。
8. `prediction/fusion.py` → `fusion_ranking.csv` + fusion precision@k/recall@k。
9. `stages/predict.py` 串起五子任务 + `stages/report.py` 补报告段 + `pipeline.py`/`main.py` 措辞 P2→P3。
10. 端到端全量验证 + 写本 `P3_PLAN.md`。

---

## 验证方式（端到端）

```bash
# 1. 前置：Neo4j 起（build_graph 用）+ 已有 P2 采集/抽取/对齐产物（data/interim 就绪）
#    预测层不直接读 Neo4j，只读 data/interim/{triples,nodes,works}.jsonl

# 2. 装依赖（无新增；沿用 P0/P1 conda 环境 + 完整路径）
& 'F:\Predictive agents\.venv\Scripts\python.exe' -m pip install -r requirements.txt

# 3. 只跑预测阶段（复用 P2 的 interim 产物）
& 'F:\Predictive agents\.venv\Scripts\python.exe' main.py --stage predict
#   预期产出：
#   - output/baseline_metrics.json  仍含 filtered MRR/Hits + precision@k（向后兼容）
#   - output/temporal_metrics.json  含 tkg_* / forecast_* / fusion_*
#   - output/tkg_rules.jsonl / forecast.csv / fusion_ranking.csv

# 4. 全量串跑（六阶段，exit 0）
& 'F:\Predictive agents\.venv\Scripts\python.exe' main.py

# 5. 报告
type output\report.md
```

**验收标准**：
1. `temporal_metrics.json` 内 `tkg_filtered_mrr` / `tkg_hits_at_1/3/10` 非空。
2. **`tkg_filtered_mrr`（CyGNet，时态切分）> `rotate_temporal_mrr`（RotatE，同时态切分）**；建议同时记录 `rotate filtered_mrr`（随机切分，P2=0.2734）作参考。
3. `forecast_mae/rmse/mape` 非空；`tkg_rules.jsonl` 含可读规则（body/head/confidence）。
4. `fusion_precision_at_k` 非空；`main.py` 全量 exit 0。

---

## 风险与注意

- **TKG 需要持久实体**：现图谱 doc→tech 边中，头（Paper/Patent/Repo/News）是一次性实体，直接喂 TKG 会因「test 头实体无历史」退化（rotatE.py `temporal_split` 注释已预警）。P3 用 `project_t2t` 把事实流投影到 Concept×Concept 持久实体，是绕开该问题的关键一步；投影后仍须校验「同一 entity_id 跨 train/test 出现」。
- **共现 ≠ 因果/定向关系**：`relates_to` 是关联代理。若需 uses/improves 等定向技术关系，P3 之后可追加一次 LLM 技术对抽取（A uses/improves B）再重跑 TKG；默认不做、不阻塞验收。
- **单关系规则空间小**：TLogic 在单一 `relates_to` 下退化为传递性/三角规则，可解释但判别力有限；CyGNet 才是达标主力，TLogic 定位为解释层 + 对照。
- **时态切分 vs 随机切分的不可比性**：验收用「同协议对比」（CyGNet 时态 vs RotatE 时态），而非「CyGNet 时态 vs RotatE 随机」，避免口径混淆；随机切分 MRR 仍保留作参考。
- **规模控制**：共现投影边数随实体度平方增长，必须 `tkg_min_cooccur` + `tkg_max_entities` 截断；CyGNet 负采样 + CPU 训练，`tkg_epochs` 从 30 起步，数据量小可调低。
- **数据不足降级**：投影边过少 / test 空时，`_run_tkg` 置 None + warning，不阻断 Kleinberg/RotatE/回归（延续 predict.py「子任务失败不互阻」）。
- **目标③代理指标**：`cited_by_count` 当前未进 works.jsonl（openalex.normalize 丢弃），star 快照 `github_stars.jsonl` 又因「仓库只采一次」而稀疏。故回归以「Concept 月度活动量」为主代理；若需真引用数/star 时序，分别补 normalize 字段、或对同一仓库做多日 star 快照（P3 不做，登记为后续增强）。
- **P4 衔接**：P3 用单次 3-way 时态切分；P4 升级为 walk-forward + purge/embargo + 「前 N 年→后一月」多期回测，并把 `temporal_split_3way` 替换为滚动窗口（接口已隔离在 `temporal.py`，改动局部）。

---

## 验证结果（2026-09-22，实际跑通）

P3 全部模块 + 接线已交付并端到端验证（`predict` 阶段 P3 子任务 + `report` 均跑通，输出 `temporal_metrics.json` / `tkg_rules.jsonl` / `forecast.csv` / `fusion_ranking.csv`）。数据规模：投影 `relates_to` 共现边 1433 条 → 事实流 10856 条（`tkg_doc_types=Paper,Patent,Repo`，排除 News 单日快照 + 过滤 future-dated 坏数据），3-way 时态切分 train/val/test = 7610/1076/2170，实体 545（train+val 词表，转导协议）。

| 指标 | 值 |
|---|---|
| CyGNet `tkg_filtered_mrr`（α=0.5） | **0.4790** |
| copy-only 基线 `tkg_copyonly_mrr` | 0.5435 |
| RotatE 时态对照 `rotate_temporal_mrr` | **0.6539** |
| TLogic 规则 | 1（symmetry, conf=1.0） |
| 回归 RMSE / 融合 precision@k | 0.7310 / 0.0000 |

**验收结论：❌ 未达标** —— `tkg_filtered_mrr (0.479) < rotate_temporal_mrr (0.654)`，且 copy-only（0.5435，CyGNet 复制机制的最强形态）也低于 RotatE 时态对照。这不是 bug，而是本数据特性下的真实结果，原因经多组对照确认（见下）。

**根因（多组实验佐证）**：
1. 共现图**稠密且对称**（无向 `relates_to`，每文档 C(n,2) 边），RotatE/DistMult 的嵌入**泛化**（传递相似性）优于 copy 的**精确复现**：pykeen DistMult=0.576、RotatE=0.654，均 > copy=0.5435。
2. 测试集 **99% 是「复现查询」**（335/338 个已知实体测试事实的 (s,r) 在 train 见过），generate 模式唯一占优的「新查询」仅 3 条，无处发挥。
3. copy 与静态嵌入**高度同源**（都学共现结构），oracle 融合 MRR 仅 0.545（generate 仅在 2.1% 事实上优于 copy），copy 无法给嵌入「补盲」。
4. 附加验证均无效：时间衰减 copy（半衰期 30~1095d）不提升；生成模式 DistMult 式打分、负采样 margin / 全词表 softmax、30/50/100 轮均无质变。

**可选后续方向（按优先级）**：
1. **定向技术关系**（LLM 抽取 uses/improves）：`relates_to` 无向共现是 copy 劣势的根源；定向 + 稀疏图更贴近「重复技术关联」，预期 copy 占优。计划书已列为 P3 之后的可追加项。
2. **序列化 generate 模式**（GRU 编码实体历史）：真正 CyGNet 的 generate 是序列编码器（非静态嵌入），可捕捉「近期重复」，或可反超 RotatE；需改 `cygnet.py` 的 `generate_logits`。
3. **放宽验收口径**：若以「copy-only（0.5435）≥ 静态 DistMult（0.576）同量级」或「CyGNet 结构完整 + TLogic 可解释 + 回归/融合全通」为验收，则本阶段可视为完成，把「超 RotatE」留到定向关系图（方向 1）。
4. **数据/配置调参**：提高 `tkg_min_cooccur` 得稀疏图（强关联边），或扩大数据量，观察 copy 是否翻盘——但这是「调到赢」，需谨慎、须在报告中如实说明。
