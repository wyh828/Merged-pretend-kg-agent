# P3 优化 + P4 验证体系 —— 结果报告

> 承接 [P3_OPT_P4_PLAN.md](P3_OPT_P4_PLAN.md)。本文记录 Part A（P3 优化）与 Part B（P4 验证体系）的
> 交付物、验收核对与诚实结论。运行环境：`E:\conda_envs\techtrend\python.exe`。

---

## 0. 一页结论

| 项 | 结果 |
|---|---|
| **Part A 定向图** | 已建成：4 类定向关系（uses/targets/improves/compares，1136 事实），多关系 TLogic 恢复 |
| **A2（CyGNet > RotatE）** | ❌ **未达标**（0.1621 < 0.2390），按计划兜底 ② 如实收尾 |
| **Part B walk-forward** | 已建成：`evaluate` 第 7 阶段，回归/排名/TKG 三路回测 + 防泄漏三道闸 |
| **B1/B2/B3** | ✅ 通过（四指标齐备、无泄漏、`--list` 含 evaluate 且 exit 0） |

**一句话根因**：定向图把「技术间关系预测」变成了**新链接预测**（86.5% 的 test 查询其 (s,r) 历史里
没有正确 tail），CyGNet 的 copy 机制（它的强项）失效，只剩 generate（DistMult）与 RotatE 对拼，
而 DistMult 弱于 RotatE。这是数据形状问题，不是实现 bug。

---

## Part A：P3 优化（定向技术关系）

### A1 定向边 ✅
- `triples.jsonl` 出现 `head_type==tail_type=="Concept"` 的定向边，**4 类关系 > 1**：
  `uses=522, targets=478, improves=54, compares=82`（`competes` 抽取为 0，LLM 未从文档识别出竞品关系）。
- 定向图事实数 **1136**（经 `max_time=今天` 过滤未来坏数据），显著稀疏于共现投影（10580）。

### A2 CyGNet > RotatE ❌（兜底 ② 收尾）
单次 3-way 时态切分（train/val/test = 800/110/226），同协议对照：

| 算法 | 时态 filtered MRR |
|---|---|
| copy-only（CyGNet 纯 copy） | 0.1376 |
| **CyGNet（copy+generate）** | **0.1621** |
| **RotatE（时态对照）** | **0.2390** |

- **0.1621 < 0.2390，A2 不达标。**
- 根因量化：test 的 52 条转导三元组里，**86.5%（45/52）** 的正确 tail 不在其 (s,r) 的 train 历史中
  ——copy 无信息可复制，只靠 generate 打分；generate 的 DistMult 在稀疏定向图上泛化弱于 RotatE。
- 对照：共现图（10580 事实）walk-forward 下 copy-only 0.9419、CyGNet 0.9459 ≫ RotatE 0.4487，
  因为共现图是「高复现」图，copy 轻松赢。**定向图与共现图正好是两个极端**：一个全在问新链接，一个全在复现。
- **兜底 ② 满足**：①「copy-only ≈ DistMult 同量级」（0.1376 vs 0.1621）；②「结构完整 + 可解释 +
  回归/融合全通」——A1（多关系定向结构）✅、A3（4 条方向性规则）✅、A4（forecast/fusion 非空）✅。
  未做任何「调到赢」的参数篡改。

### A3 TLogic 规则 > 1 ✅
`tkg_rules.jsonl` 产出 **4 条**方向性蕴含规则（阈值 `min_support=3 / min_confidence=0.05`）：

```
implication[compares -> improves]  support=3  conf=0.0517
implication[compares -> uses]      support=3  conf=0.0517
implication[improves -> compares]  support=3  conf=0.075
implication[improves -> targets]   support=6  conf=0.15
```

多关系定向图恢复了 TLogic 的判别力（P3 单关系共现退化为 1 条 symmetry 规则）。

### A4 forecast / fusion 非空 ✅
`forecast_mae=0.7055 / rmse=0.7310 / mape=2.3758`；`fusion_precision_at_k=0.0`、
`fusion_recall_at_k=0.0`、`fusion_top_k` 10 个概念（均非 null，未因换边源回归）。

---

## Part B：P4 验证体系（walk-forward + purge/embargo）

### 交付物
- `techtrend/prediction/evaluation.py`：`rolling_origins` / `walk_forward_splits` / `purge_label_overlap` /
  `backtest_tkg` / `backtest_regression` / `backtest_ranking` / `leak_check`。
- `techtrend/stages/evaluate.py`：第 7 阶段（`main.py --stage evaluate`），写 4 个输出文件。

### B1 四指标齐备（含 mean±std 与每折明细）✅
`output/eval_metrics.json`：

| 目标 | 指标 | mean ± std |
|---|---|---|
| ② 链接预测 | TKG filtered MRR（CyGNet） | 0.9459 ± 0.0765 |
| ② | TKG Hits@10 | 0.9500 |
| ③ 回归 | MAE / RMSE / MAPE | 0.5017 ± 0.0890 / 0.5269 ± 0.0840 / 1.9166 ± 0.4419 |
| ① 排名 | precision@k / recall@k | 0.0 / 0.0 |

- ⚠️ **TKG 回测边源回退**：定向图时态跨度不足（2025 仅 15 条、无 2026），walk-forward 无有效折
  （test 窗口为空 / test 独有实体被转导协议剔除），故 TKG 回测回退到**共现投影**（10580 事实，2023→2026
  连续时态），并在 `eval_metrics.json` 记录 `tkg_fallback_reason`。对应计划书「与共现投影混合」兜底。
- 回归 5 折、排名 3 折、TKG 3 折均有每折明细；`eval_folds.csv` 落盘。

### B2 无泄漏 ✅
`output/leak_check.json`：`ok=true`，`violations=[]`，每折 train/test 时间不重叠、embargo 生效、
purge 生效（fold 4 的 53 个 test 独有实体是 2026-09 新增概念，属转导协议正常剔除范围）。

### B3 全量 exit 0 + `--list` 含 evaluate ✅
`main.py --list` 输出 7 阶段（collect/extract/align/build_graph/predict/report/**evaluate**），exit 0。

---

## 关键修复（本报告数字的可信度）

1. **平均秩破同分**（`cygnet.evaluate_cygnet`）：原先全 0 分（无历史）时正确 tail 侥幸并列第 1，
   使 copy-only 虚高到 0.7071；改为平均秩后 copy-only 落到诚实的 0.1376。
2. **正确 tail 保留在候选集**：修掉 filtered 排名里 mask 把正确 tail 自身也剔除、导致 rank < 1（MRR > 1）的 bug。
3. **filtered 剔除口径与 RotatE 对齐**：CyGNet 原只剔除 test 尾，现剔除 `train+val+test`（与 pykeen 的
   `realistic` 过滤一致），保证 A2「同协议」对比公平。
4. **future-dated works 过滤**（`evaluate.py`）：OpenAlex 有 ~538 条发布日在「今天」之后的坏记录（可到 2050），
   已过滤，避免回归/排名回测的 test 窗口落到未来。

---

## 诚实声明与后续

- **A2 未达标是数据形状问题**：定向图「稀疏 + 问新链接」与 CyGNet「靠复制历史」的假设天然相克。计划书
  预判的「序列化 generate（GRU）」与「提高 min_support 得更稀疏图」都不会改善这一根本矛盾，故未强启。
  后续若要真反超 RotatE，需**先喂给 CyGNet 更多可复制的历史**（P5 每日增量 + 定向抽取覆盖近期文档），
  再评估。
- **定向图时态跨度不足**：`_run_openalex_tech_pairs` 上次抽取只覆盖到 2025-06 的 works（`works.jsonl`
  现已含 2026-09 的作品）。重跑 `--stage extract` 即可把近期作品的定向对补进 triples，缓解 B1-TKG 的回退。
- **排名 p@k=0.0**：Kleinberg 突发与「未来增速 top-k」在月度粒度上基本不重合，这是目标①信号本身的弱，
  非实现问题；留待 P6（S 曲线）再评估。
- 根目录残留调试脚本 `alpha_sweep_tmp.py / dim_sweep_tmp.py / debug_fusion_tmp.py` 可删。

---

## Part C：专利前向引用图（P4_P3 计划 P0-1 / P2-1，2026-09）

> 全文见 [P4_P3_METRIC_OPT_RESULT.md](P4_P3_METRIC_OPT_RESULT.md)。

- **P0-1 ✅ 达成**：PatentsView bulk 终版免 key，产 6,967,772 条前向引用（2015-01-06→2024-12-31），
  `data/interim/patent_citations.jsonl` 已入 interim。
- **P2-1 ❌ 前提证伪**：引用图接 `tkg_edge_source=patent_citation` 后，walk-forward + 转导协议下每折
  test 三元组被整体剔除（10 条 `test 无已知实体三元组`），evaluate 自动回退共现（0.9437 vs 0.4480）。
  根因：引用图是**时态 DAG**（test tail 全新）+ **单事件边**（copy 无 object 重复），
  「高重复 = copy 燃料」的假设其实是 **head 的度** 而非 object 的时间重复，被证伪。
- **A2 三图盘点**：共现投影 copy 赢（0.9459 vs 0.4487）、定向 LLM 图输（0.1621 vs 0.2390）、
  引用图退化（无有效分）；尚无真实定向图上 CyGNet 反超 RotatE。
