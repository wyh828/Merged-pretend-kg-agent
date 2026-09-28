# P3 优化 + P4 验证体系 —— 完整构建计划

> 本文档承接 [P3_PLAN.md](P3_PLAN.md)「验证结果」（**P3 验收未达标**：CyGNet 时态 MRR 0.4790 < RotatE 时态对照 0.6539）与 [PROJECT_PLAN.md](PROJECT_PLAN.md) 七「分阶段路线图」P4 行。
> 分两部分：**Part A（P3 优化）** 针对未达标根因做「治本 + 治标」；**Part B（P4 验证体系）** 落地 walk-forward + purge/embargo + 前 N 年→后一月 ground truth。
> 两部分可拆为 `P3.5_PLAN.md` / `P4_PLAN.md` 两份，当前合并为一份便于整体审查。

---

## 0. 一页速览

| 维度 | Part A：P3 优化 | Part B：P4 验证体系 |
|---|---|---|
| 目标 | 让 CyGNet（时序）反超 RotatE（同时态同协议），P3 验收转 ✅ | 四指标齐备、无泄漏、可复现的多期回测 |
| 根因/缺口 | 无向共现 `relates_to` 稠密+对称+单关系 → copy 被嵌入泛化压制 | 当前只有单次 3-way 切分，无 walk-forward/purge/embargo |
| 主手段 | **定向 tech→tech 关系**（LLM 抽取 uses/improves/…）+（可选）序列化 generate | 滚动回测引擎 + 防泄漏三道闸 |
| 交付物 | 定向关系抽取 + TKG 边源切换 + 多关系 TLogic | `prediction/evaluation.py` + `stages/evaluate.py`（第 7 阶段） |
| 验收 | 定向图上 `tkg_filtered_mrr > rotate_temporal_mrr` | `eval_metrics.json` 四指标齐备，`leak_check.json` 全部通过 |

---

# Part A：P3 优化（定向技术关系 + 模型增强）

## A1. Context（为什么优化）

P3 已全量交付，但验收标准「CyGNet 时态 filtered MRR > RotatE 同时态 filtered MRR」未达标：`0.4790 < 0.6539`，且 copy-only（0.5435，复制机制最强形态）也低于 RotatE。P3_PLAN.md「验证结果」经多组对照已把根因锁定为**数据形状**而非实现 bug：

1. **无向共现 `relates_to`**：`temporal.project_t2t` 对每文档 k 个 Concept 产 C(k,2) 条对称边，图稠密、无方向 → 静态嵌入的「传递相似性」泛化（DistMult=0.576、RotatE=0.654）压制 copy 的「精确复现」（0.5435）。
2. **单关系**：投影后只有一条 `relates_to` → TLogic 退化为 1 条 symmetry 规则；CyGNet 的 relation 维度失效。
3. **99% 复现查询**：335/338 条测试 (s,r) 在 train 见过 → generate 的「新链接」优势无处发挥。

据此，优化方向按 [P3_PLAN.md](P3_PLAN.md)「建议的下一步方向」排序，本计划选 **方向①（定向技术关系）为主治手段**，**方向②（序列化 generate）为可选治标**，方向③④为兜底。

### A1.1 优化动因对照表（承 TECH_ROADMAP §13）

「目标② → 数据特性 → 算法 → 数据处理 → 检测值 → 优化方向」的因果链说明：**优化动因是「数据形状配不上问题」，不是「算法配不上问题」**。完整 6 行表见 [TECH_ROADMAP.md](TECH_ROADMAP.md) §13，此处只摘目标②三算法同协议对照：

| 算法 | 数据特性 | 检测值（时态 filtered MRR） | 含义 |
|---|---|---|---|
| copy-only | 无向共现、稠密、对称、单关系 | **0.5435** | 真实 tail 平均第 ~1.84 名；复制机制最强形态 |
| CyGNet（copy+generate） | 同上 + 99% 复现查询 | **0.4790** | 平均第 ~2.1 名；generate 与 copy 同源，混合反降 |
| RotatE 时态对照 | 静态嵌入靠传递相似性泛化占优 | **0.6539** | 平均第 ~1.53 名，Hits@10 0.7911 |

结论：目标②问的是「技术间**新关联**」，`relates_to` 无向共现是 P3 起就明确标注的「关联代理」（`project_t2t` 诚实声明），天然缺方向与语义；定向 uses/improves 是**更贴近问题本身的构造**。优化后仍以「同样的三算法、同样的同时态同协议」重跑，共现投影保留作消融对照，不预设赢家。

### A1.2 决策声明（三则，定稿）

1. **排除 News/GDELT 于共现投影**（`tkg_doc_types=Paper,Patent,Repo`）：GDELT 是单日快照，会形成巨大时间组使 val/test 为空；且其「主题」是事件主题（CYBER_ATTACK 等）而非技术实体，与 Concept×Concept 投影语义不匹配。News/GDELT 仍参与静态图谱、Kleinberg 突发、回归与融合，只是不进共现投影；**定向 tech→tech 抽取同样只来自 Paper/Patent/Repo（技术文档），News 仅做 mentions/tone**。
2. **过滤 future-dated OpenAlex 数据**（`tkg_max_time` 默认今天）：OpenAlex 存在发布日期在「今天」之后的坏记录，若不滤会污染时态切分（train 混入未来 = 泄漏 + 违反「过去→未来」）。这是唯一正确做法；可选固定快照日期以保证复现。
3. **序列化 generate（GRU 编码实体历史）——数据量增加后再用**：真 CyGNet 的 generate 是序列编码器，能捕捉「近期重复」，是模型侧唯一可能反超静态嵌入的手段；但当前 545 实体 / 10856 事实规模下易过拟合、历史样本不足。P3.5 默认 `tkg_sequence_generate=False`，待 P5 每日增量积累数据、定向图变丰富后再启用。

## A2. 关键决策

| 项 | 结论 | 依据 |
|---|---|---|
| 主优化 | **定向 tech→tech 关系抽取**（LLM 二次 pass，抽 uses/improves/compares/targets/competes） | P3_PLAN 方向①（治本）；图变「定向 + 稀疏 + 多关系」 |
| 边源切换 | TKG 直接读定向 tech→tech 边（`head_type==tail_type==Concept`），**不再走共现投影**；共现投影保留作对照/兜底 | 根因①/② |
| 多关系 | 定向图有 5 关系 → TLogic 规则空间恢复（uses/improves 的传递性）、CyGNet relation 维度恢复 | 根因② |
| 对齐 | 定向边两端都是技术实体名，复用现有 `align` 阶段折叠为 Concept + 映射 entity_id | P2 已固化 `_MATCH_TARGET` |
| 次优化（可选） | 序列化 generate（GRU 编码实体历史序列），替换静态 DistMult 打分 | P3_PLAN 方向②（治标，数据量小把握低） |
| 兜底 | 若定向图仍不达标：①提高 `tkg_min_cooccur` 得稀疏图；②放宽验收口径（copy-only ≥ DistMult 同量级 或「结构完整 + 可解释 + 回归/融合全通」） | P3_PLAN 方向③④，须在报告如实说明，避免「调到赢」 |
| 验收 | 定向图上 `tkg_filtered_mrr`（CyGNet）> `rotate_temporal_mrr`（RotatE，同时态同协议） | PROJECT_PLAN P3 行 |

## A3. 目录结构（P3 优化新增/改动）

```
techtrend/
  extraction/
    schema.py                 # 改：+ TECH_PAIR_RELATIONS（定向 tech→tech 关系白名单）
    llm.py                    # 改：+ LLMExtractor.extract_tech_pairs()（新 prompt）
  stages/
    extract.py                # 改：_run_llm 内对每文档追加定向对抽取，写入 triples 流
  prediction/
    temporal.py               # 改：+ load_directed_edges()（从 triples 过滤 Concept→Concept 定向边）
    cygnet.py                 # 改：generate_logits 增加「序列化 GRU」变体（可选，开关控制）
  config.py                   # 改：+ P3.5 定向关系参数段
  stages/
    predict.py                # 改：_run_tkg 按 tkg_edge_source 选边源（directed / cooccur）
  stages/
    report.py                 # 改：报告注明当前边源 + 是否定向图
```

## A4. 数据流（定向关系如何进入 TKG）

```
extract（P3.5 扩展）
  _run_llm：对每文档 doc
    ├─ extractor.extract(doc)            → doc→tech 三元组（沿用，不动）
    └─ extractor.extract_tech_pairs(doc) → 定向 tech→tech 三元组（新增）
          {head: tech_id_A, head_type:"Technology", relation:"uses",
           tail: tech_id_B, tail_type:"Technology", time, source}
          两端 ID 用 deterministic_entity_id(source, "Technology", name) —— 与 doc→tech 尾实体同一套，
          保证复用 extract 已建节点、名字一致。
            ↓  与 doc→tech 一起写入 triples.jsonl（无新文件）
align（不改逻辑，自动覆盖）
  Technology → Concept 折叠；head_id/tail_id = entity_id
            ↓
predict._run_tkg
  tkg_edge_source == "directed"：
    load_directed_edges(triples) → 过滤 head_type==tail_type=="Concept" 且 relation∈定向白名单
    → TKG 事实流（多关系、定向、稀疏）
  tkg_edge_source == "cooccur"（兜底/对照）：
    project_t2t(triples) → 共现投影（P3 现状，不改）
```

> **诚实声明**：定向关系来自 LLM 对文档原文的定向陈述抽取，语义强于共现，但仍受 LLM 幻觉与召回限制；抽取结果须经 `min_support` 计数降噪 + 白名单校验（`llm._validate` 同款）。

## A5. 配置扩展（config.py + .env.example）

```python
# ---- 定向技术关系（P3.5 优化）----
techpair_enable: bool = True          # 是否启用定向 tech→tech 抽取（需 llm_api_key，无 key 自动跳过）
techpair_relations: str = "uses,improves,compares,targets,competes"  # 定向关系白名单（逗号分隔）
techpair_min_support: int = 2         # 定向边最小计数（降噪；定向边稀疏，可低于共现阈值）
tkg_edge_source: str = "directed"     # TKG 边源：directed(定向 tech→tech) | cooccur(共现投影，P3 现状)
tkg_sequence_generate: bool = False   # 序列化 generate（GRU）开关；默认关（数据量小易过拟合）
tkg_gru_hidden: int = 64              # GRU 隐层（tkg_sequence_generate=True 时生效）
```

## A6. 各模块详细设计

### A6.1 extraction/schema.py（改）

```python
# 定向 tech→tech 关系白名单（exclude belongs_to：属层级 doc→tech；causes 罕见可留）
TECH_PAIR_RELATIONS = ("uses", "improves", "compares", "targets", "competes", "causes")
```

### A6.2 extraction/llm.py（改）—— 二次 pass 抽定向对

```python
_TECHPAIR_SYSTEM_PROMPT = """你是科技文档的「技术间定向关系」抽取器。只输出 JSON。
输入已给出本文档识别到的技术实体名列表。
关系（relation）限定：uses（A 使用 B）/ improves（A 改进 B）/ compares（A 对比 B）/
targets（A 针对 B）/ competes（A 与 B 竞品）。
规则：
1. head、tail 都必须是「技术实体名列表」里出现的实体（规范名，保持原文语言）。
2. 只抽文档中明确陈述的定向关系，不臆造；方向必须符合语义（A→B 与 B→A 不同）。
3. 无定向关系输出 {"pairs": []}。
4. 严格输出 JSON：{"pairs": [{"head": 实体A, "relation": 关系, "tail": 实体B}]}。"""

class LLMExtractor:
    def extract_tech_pairs(self, doc: dict, known_tech_names: list[str]) -> list[dict]:
        """单文档 → 定向 tech→tech 三元组 [{"head","relation","tail"}]（head/tail 均为技术实体名）。"""
        # user prompt = 标题+正文 + "\n已识别技术实体：[" + ", ".join(known_tech_names) + "]"
        # 复用 _chat / _parse_json；白名单过滤 relation ∈ TECH_PAIR_RELATIONS、head/tail 均 ∈ known_tech_names、
        # head != tail、去重；逐条 try/except 不阻断整批。
```

### A6.3 stages/extract.py（改）—— 接入定向对

在 `_run_llm` 对每个 doc 抽取完 doc→tech 三元组后：

```python
known_names = [n["name"] for n in self_doc_tech_nodes]   # 该文档已抽取的技术实体名
for pair in extractor.extract_tech_pairs(doc, known_names):
    hid = deterministic_entity_id(doc.get("source") or "llm", "Technology", pair["head"])
    tid = deterministic_entity_id(doc.get("source") or "llm", "Technology", pair["tail"])
    # 端点节点复用/新建（_merge_nodes 同 doc→tech 尾巴），保证 align 可解析
    triples.append({"head": hid, "head_type": "Technology", "relation": pair["relation"],
                    "tail": tid, "tail_type": "Technology",
                    "time": doc.get(time_field), "source": doc.get("source")})
```

要点：两端 ID 与 doc→tech 尾实体用**同一 `deterministic_entity_id`**，名字一致 → 无需新对齐通道，`align` 阶段自动把 Technology 折叠成 Concept 并补 `head_id/tail_id`。受 `llm_max_docs_per_run` 预算与 `techpair_enable` 开关约束。

### A6.4 prediction/temporal.py（改）—— 定向边读取

```python
def load_directed_edges(
    triples: Iterable[dict],
    relations: Iterable[str] | None = None,
    min_support: int = 2,
) -> list[dict]:
    """从 triples.jsonl 过滤定向 tech→tech 事实流。
    保留 head_type==tail_type=="Concept" 且 relation∈relations 的行（对齐后 tech 已折叠为 Concept）；
    按 (head, relation, tail) 计数，仅保留计数 ≥ min_support 的边。
    返回 [{"head","relation","tail","time"}]，端点均为 entity_id。
    """
```

`project_t2t`（共现投影）**原样保留**，仅作 `tkg_edge_source=="cooccur"` 的兜底与消融对照。

### A6.5 stages/predict.py（改）—— 边源切换

`_run_tkg` 开头按 `s.tkg_edge_source` 分支：

```python
if s.tkg_edge_source == "directed":
    facts = tp.load_directed_edges(triples, relations=techpair_rel_set, min_support=s.techpair_min_support)
else:
    facts = tp.project_t2t(triples, ...)   # 现状
```

其余 3-way 切分 → copy-only → CyGNet → TLogic → RotatE 时态对照逻辑**复用不变**；唯一变化是 CyGNet/TLogic 现在跑在**多关系**图上，`encode_ids` 的 `r2id` 含多个关系，copy 矩阵索引按关系区分，`score_candidates` 沿各关系规则游走。

### A6.6 prediction/cygnet.py（改，可选）—— 序列化 generate

新增 `class CyGNetSeq(CyGNet)` 或给 `CyGNet` 加 `use_seq` 分支：

```python
def generate_logits(self, s, r, hist_seq) -> Tensor:
    """序列化 generate：GRU 编码实体 s 的历史关系序列（近期重复），
    替代静态 DistMult。hist_seq 由 train 按时间排序的 (r, o) 序列构造。"""
```

默认 `tkg_sequence_generate=False`（数据量小、易过拟合）；仅当定向图上仍不达标再启用（见实施顺序第 6 步）。

### A6.7 stages/report.py（改）

时序外推段增补一行「TKG 边源 = directed / cooccur」，并保留「是否优于静态基线」结论行（`_conclusion_line` 逻辑不变，指标来源变定向图）。

---

# Part B：P4 验证体系（walk-forward + purge/embargo）

## B1. Context（为什么做）

P3 用的是**单次 3-way 时态切分**（`temporal.temporal_split_3way`），满足「时间不重叠」，但：① 单期评测、易过拟合；② 无 embargo（train 紧贴 test，copy 机制可能「偷看」近邻事实）；③ 回归无 purge（label 窗口与测试窗口重叠）；④ 无泄漏 lint。P4 按 PROJECT_PLAN §五把验证升级为**可复现的多期 walk-forward 回测**，四目标四指标齐备、无泄漏，作为 P3 优化后新图与未来 P5/P6 的**统一评测基准**。

## B2. 关键决策

| 项 | 结论 | 依据 |
|---|---|---|
| 切分 | **walk-forward / rolling origin（expanding window 主选，rolling 可选）** | PROJECT_PLAN 5.1 |
| TKG 防泄漏 | 时态切分（train 时间 < test 时间）+ **embargo**（train 剔除 test 窗口前的缓冲期事实） | 5.1「purge+embargo」 |
| 回归防泄漏 | **purge**（剔除 label 窗口与 test 重叠的训练样本）+ 特征只在 train 段构建 | 5.1「scaler/imputer 只在训练段 fit」 |
| 排名防泄漏 | 每折独立：train 窗口算信号、test 窗口算 ground truth（未来增速 top-k） | 5.1 |
| 新实体 | TKG 转导协议：test 独有实体（train 无历史）剔除，与 P3 一致 | P3 已固化 |
| 交付物 | 独立评测脚本 + `stages/evaluate.py`（**第 7 阶段**，`main.py --stage evaluate`），写 `eval_metrics.json` + `eval_report.md` | PROJECT_PLAN P4「评测脚本」 |
| 四指标 | ①排名 precision@k/recall@k ②链接预测 filtered MRR/Hits@1/3/10 ③回归 MAE/RMSE/MAPE（④ S 曲线留 P6） | PROJECT_PLAN 4.1 |
| 复用 | 复用 P3 的 cygnet/tlogic/regression/fusion/rotatE/kleinberg；只把「切分」升级为滚动窗口（接口已隔离在 temporal.py + 新 evaluation.py） | P3_PLAN「P4 衔接」 |

## B3. 目录结构（P4 新增/改动）

```
techtrend/
  prediction/
    evaluation.py             # 新：walk-forward 切分 + purge/embargo + 多期回测引擎 + leak_check
  stages/
    evaluate.py               # 新：EvaluateStage（第 7 阶段）
    __init__.py               # 改：注册 EvaluateStage
  config.py                   # 改：+ P4 验证参数段
  main.py                     # 改：argparse description / --list 含 evaluate
```

`pipeline.py` 阶段顺序在 `report` 后追加 `evaluate`（或作为独立入口，见 B7）。

## B4. 数据流（walk-forward 回测）

```
triples.jsonl（定向 tech→tech，多关系）
  │
  ├─ 目标② TKG 外推：rolling_origins → 每折 (train, test)
  │     train = time < test_start - embargo   （expanding：全部更早；rolling：窗口内）
  │     test  = time ∈ [test_start, test_start + test_months)
  │     每折跑 copy-only / CyGNet / RotatE（时态）→ filtered MRR/Hits@1/3/10
  │     └─► 聚合 mean ± std + 每折明细
  │
  ├─ 目标③ 回归：monthly（Concept × 月）→ walk-forward，每折
  │     train 样本 feature-time t 且 t + horizon < test_start - purge（purge 剔除 label 重叠）
  │     test = 最后 horizon 月
  │     └─► MAE/RMSE/MAPE 聚合 + 每折明细
  │
  ├─ 目标① 排名：每折 train 窗口算 Kleinberg/fusion 信号，test 窗口 future_growth_top_k 为真值
  │     └─► precision@k/recall@k 聚合 + 每折明细
  │
  └─ leak_check：所有折 train/test 时间不重叠 + 实体组报告（test 独有实体计数）
        └─► leak_check.json（全通过才算「无泄漏」）
```

### 输出文件（output/）

| 文件 | 内容 |
|---|---|
| `eval_metrics.json` | walk-forward 聚合指标：TKG MRR/Hits mean±std、回归 MAE/RMSE/MAPE mean±std、排名 p@k/r@k mean±std + 各折明细数组 |
| `eval_folds.csv` | 每折 (fold, train_end, test_start, test_end, n_train, n_test, 各指标) |
| `eval_report.md` | 可读评测报告（含结论行：定向图上 CyGNet 是否 > RotatE） |
| `leak_check.json` | 无泄漏校验结果（每折 train/test 时间不重叠、embargo/purge 生效、test 独有实体计数） |

## B5. 配置扩展（config.py）

```python
# ---- 验证体系（P4）----
eval_enable: bool = True
eval_n_splits: int = 5              # walk-forward 折数
eval_test_months: int = 1           # 每折测试窗口（"后一月"）
eval_step_months: int = 1           # 折间步长（rolling origin 前进量）
eval_embargo_months: int = 1        # TKG：train 与 test 间缓冲（剔除近邻事实）
eval_purge_months: int = 6          # 回归：label 重叠剔除窗口（≈ forecast_horizon）
eval_mode: str = "expanding"        # expanding | rolling
eval_rolling_window_months: int = 24  # rolling 模式的训练窗口长
eval_min_train: int = 200           # 每折最少训练事实，否则跳过该折
```

## B6. 各模块详细设计

### B6.1 prediction/evaluation.py（新）—— 回测引擎

```python
# ---- 时间窗口 ----
def rolling_origins(
    times: list[str], n_splits: int, test_months: int, step_months: int,
) -> list[tuple[str, str, str]]:
    """按时间生成 walk-forward 起点。返回 [(test_start, test_end)]，时间用 ISO 日期字符串比较；
    最后一段 test 窗口的 test_end = max(time)，向前倒推 n_splits 段。"""

# ---- TKG 切分 ----
def walk_forward_splits(
    triples: list[dict], origins: list[tuple[str, str, str]],
    embargo_months: int, mode: str = "expanding", rolling_window_months: int = 24,
) -> list[tuple[list[dict], list[dict]]]:
    """每折 (train, test)：train 时间 < test_start - embargo；test ∈ [test_start, test_end)。
    expanding：train=全部更早；rolling：train 仅取 [test_start - window, test_start - embargo)。"""

# ---- 回归 purge ----
def purge_label_overlap(samples: list[tuple[int, float]], horizon: int, purge: int) -> list[tuple[int, float]]:
    """剔除 label 窗口 [t, t+horizon) 与 test 窗口重叠的训练样本（t + horizon > test_start - purge）。"""

# ---- 回测 ----
def backtest_tkg(facts: list[dict], cfg) -> dict:
    """每折跑 copy-only / CyGNet / RotatE（时态），返回 {fold_metrics: [...], mrr_mean, mrr_std, hits_mean, ...}。"""

def backtest_regression(monthly: pd.DataFrame, cfg) -> dict:
    """walk-forward MAE/RMSE/MAPE，含 purge；返回 {fold_metrics, mae_mean, rmse_mean, mape_mean, ...}。"""

def backtest_ranking(df: pd.DataFrame, burst_fn, fusion_scores_fn, cfg) -> dict:
    """每折 Kleinberg/fusion 排名 vs 未来增速 top-k；返回 {fold_metrics, p_at_k_mean, r_at_k_mean, ...}。"""

# ---- 无泄漏校验 ----
def leak_check(folds: list[tuple[list, list]]) -> dict:
    """校验：每折 train 最大 time < test 最小 time；统计 test 独有实体（train 未见）计数与占比。
    返回 {ok, violations: [...], test_only_entities_per_fold: [...]}。"""
```

复用：`backtest_tkg` 内部调 P3 的 `cygnet.train_cygnet`/`evaluate_cygnet`/`evaluate_copy_only` 与 `rotatE.run_rotate`；`backtest_regression` 调 `regression.run_regression` 的建模部分但改为按折切分（当前 `run_regression` 是单次最后 horizon 回测，P4 需暴露「给定 train/test 月界」的变体）；`backtest_ranking` 调 `kleinberg`/`fusion`。

### B6.2 stages/evaluate.py（新）—— 第 7 阶段

```python
class EvaluateStage(Stage):
    name = "evaluate"
    def run(self) -> dict:
        # 读 triples.jsonl + works.jsonl；load_directed_edges（或 project_t2t）→ facts
        # ① rolling_origins + walk_forward_splits → backtest_tkg
        # ② build_concept_monthly_counts → backtest_regression（含 purge）
        # ③ backtest_ranking（Kleinberg + fusion）
        # ④ leak_check
        # 写 eval_metrics.json / eval_folds.csv / eval_report.md / leak_check.json
        # 返回 {"stage":"evaluate","status":"ok","tkg_mrr_mean":..., "leak_ok":...}
```

### B6.3 stages/__init__.py（改）—— 注册

`get_default_stages` 追加 `EvaluateStage`（在 `ReportStage` 之后），使 `main.py`/`--list` 可见；`main.py` description 由「P3 时序预测」改「P4 验证体系」。

---

## 实施顺序（任务分解，含依赖）

**Part A（P3 优化）**
1. `config.py` + `.env.example` 补 P3.5 段；`schema.py` 加 `TECH_PAIR_RELATIONS`。
2. `llm.py` 加 `extract_tech_pairs` + `_TECHPAIR_SYSTEM_PROMPT`；`extract.py` `_run_llm` 接入定向对写入 triples 流。单测：抽出的定向对 head/tail 都在 `known_names` 内、relation 在白名单、两端 ID 与 doc→tech 尾一致。
3. `temporal.py` 加 `load_directed_edges`；`predict.py` `_run_tkg` 按 `tkg_edge_source` 分支。**验证定向边数量/关系分布/稀疏度**（应显著稀疏于 C(n,2) 共现）。
4. **定向图跑通全链路**：copy-only → CyGNet → TLogic（多关系规则）→ RotatE 时态对照。看 `tkg_filtered_mrr` vs `rotate_temporal_mrr`。
5. 若未达标，再启用 `tkg_sequence_generate`（A6.6 序列化 generate）；仍不达标则走兜底（调 `techpair_min_support` 得更稀疏、或放宽口径并如实报告）。
6. `report.py` 补边源标注；写 Part A 结论。

**Part B（P4 验证体系）**
7. `config.py` 补 P4 段；`evaluation.py` 先落地 `rolling_origins` + `walk_forward_splits` + `leak_check`。单测：每折 train/test 时间不重叠、embargo 生效、expanding vs rolling 边界正确。
8. `backtest_tkg` / `backtest_regression`（含 purge）/ `backtest_ranking` 三函数。
9. `stages/evaluate.py` + 注册 + `main.py` 措辞；跑 `--stage evaluate`，产出四文件。
10. 端到端：`python main.py` 全量 exit 0；`leak_check.json` 全通过；`eval_metrics.json` 四指标齐备。

---

## 验证方式（端到端）

```bash
# 前置：已有 P2/P3 采集+抽取+对齐产物（data/interim 就绪）；LLM key 已配（定向抽取需）
E:\conda_envs\techtrend\python.exe main.py --stage extract   # 重跑抽取，产出定向 tech→tech 边（进 triples.jsonl）
E:\conda_envs\techtrend\python.exe main.py --stage align     # 折叠 + 映射 entity_id
E:\conda_envs\techtrend\python.exe main.py --stage predict   # 定向图 TKG + 回归 + 融合
E:\conda_envs\techtrend\python.exe main.py --stage evaluate  # P4 walk-forward 回测
type output\eval_report.md
type output\leak_check.json
```

**Part A 验收标准**：
1. `triples.jsonl` 出现 `head_type==tail_type=="Concept"` 的定向边（uses/improves/compares/targets/competes），且关系数 > 1。
2. `temporal_metrics.json` 内 `tkg_filtered_mrr`（定向图）> `rotate_temporal_mrr`（同时态同协议）。
3. `tkg_rules.jsonl` 规则数 > 1（多关系恢复 TLogic 判别力）。
4. `forecast_*` / `fusion_*` 非空（不因换边源回归）。

**Part B 验收标准**：
1. `eval_metrics.json` 四指标（p@k/r@k、MRR/Hits@1/3/10、MAE/RMSE/MAPE）齐备，各含 mean±std 与每折明细。
2. `leak_check.json` `ok=true`（每折 train/test 时间不重叠、embargo/purge 生效）。
3. `main.py` 全量 exit 0；`--list` 含 `evaluate`。

---

## 风险与注意

- **定向抽取成本与幻觉**：二次 LLM pass 使每文档 LLM 调用翻倍（受 `llm_max_docs_per_run` 预算约束）；定向关系有幻觉风险，须白名单 + `min_support` 计数降噪 + 报告如实声明（定向≠绝对因果，是「文档明确陈述的定向关系」）。
- **定向图可能过稀疏**：技术对抽取召回低 → 边数不足使 TKG 退化为空（`len(facts) < 50` 预警）。缓解：`techpair_min_support` 降到 1、扩大 `llm_max_docs_per_run`、或与共现投影**混合**（定向边为主 + 共现兜底补边，需在报告说明混合口径）。
- **序列化 generate 把握低**：数据量小（P3 实测 545 实体 / 10856 事实）GRU 易过拟合，定位为「定向图仍不达标」时的次优尝试，不做为默认。
- **walk-forward 计算量**：每折重训 CyGNet/RotatE，`eval_n_splits=5` × 训练成本可能较长（CPU）。缓解：`eval_n_splits` 起步 3、`tkg_epochs` 在 evaluate 内可下调；单折 try/except 失败跳过、不阻断整体。
- **口径可比性**：Part A 验收仍坚持「同时态同协议」（CyGNet 时态 vs RotatE 时态），不与 P2 随机切分（0.2734）混比；walk-forward 的 mean±std 才是最终对外口径。
- **evaluate 与 predict 职责**：`predict` 保留单次 3-way 快指标（向后兼容 P1/P2/P3 输出）；`evaluate` 是严谨多期回测，二者并存不冲突，报告以 `eval_report.md` 为准。

---

## 待办登记（跨 P4/P5/P6）

- 目标③真引用数/star 时序（`cited_by_count` 补 normalize、多日 star 快照）—— P3 已登记，P4 回归仍以「月度活动量」为代理。
- 目标④ S 曲线阶段 + 趋势图 + 周报 —— 留 P6。
- hermes-agent cron + 角色化 agent —— P5。
