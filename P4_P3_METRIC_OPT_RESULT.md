# P4/P3 指标优化 —— 结果报告（专利前向引用图路线）

> 承接 [P4_P3_METRIC_OPT_PLAN.md](P4_P3_METRIC_OPT_PLAN.md)。记录 P0-1（专利前向引用数据）、
> P1-2（引用时序回归 + S 曲线）、P2-1（引用图接 TKG 边源）三项的实际交付与评测结论。
> 运行环境：`E:\conda_envs\techtrend\python.exe`。

---

## 0. 一页结论

| 项 | 结果 |
|---|---|
| **P0-1 专利前向引用数据** | ✅ **达成**：6,967,772 条前向引用，2015-01-06→2024-12-31，免 key（PatentsView bulk 终版） |
| **P1-2 引用时序回归 + S 曲线** | ⚠️ **跑通但有偏**：patents=5000 / months=120 / RMSE=57.03；S 曲线仅 mature+declining（top-N 选样偏差） |
| **P2-1 引用图接 TKG 边源** | ❌ **前提证伪**：walk-forward + 转导协议下 test 三元组被整体剔除，无有效分，自动回退共现 |

**一句话根因**：专利引用图是**时态 DAG**（只能引用更早专利），test 窗口里的引用专利（tail）是 train 未见的
新实体，被转导协议整体剔除；且每对专利只互相引用一次（单事件边），CyGNet copy 需要的「object 在时间上重复」
根本不存在——「奠基专利被反复引用」只是 **head 的度**，不是 copy 燃料。计划书 P2-1 的假设被经验证伪。

---

## 1. P0-1 专利前向引用数据（✅）

- **数据源**：PatentsView 终版 bulk（2026-03-20 停更前最后一版，Zenodo record 15058362 的
  `g_us_patent_citation.tsv.zip` 2.16GB + `g_patent.tsv.zip` 223MB），免 key 直接下载。
- **处理**：字节精确校验 → 解压 9.64GB TSV → 后向引用对（citing→cited）反转聚合为前向事实
  `(cited, "cited_by", citing, time=citing_date)`。
- **产出**：`data/interim/patent_citations.jsonl`，**6,967,772 条前向引用事实**，跨度 2015-01-06 →
  2024-12-31（终版止于 2024，非计划字面「2026」，受源数据所限）。
- **验收核对**（计划 P0-1 行）：引用边 > 5000 ✅（6.97M）；时态跨 2015→2026 ⚠️（实得 2015→2024）；
  无 key ✅。控制图规模时按二部度截断（head/tail 各取 top-N）至 `tkg_max_entities`，2000 实体下 896,592 条边。

---

## 2. P1-2 引用时序回归 + S 曲线（⚠️ 跑通但有偏）

- `patents=5000, months=120, status=ok`，回归 RMSE 57.03±2.39（引用量口径，替换「月度活动量」代理）。
- **S 曲线分布偏差**：`{mature:2933, declining:2067}`，**无 emerging/growth**——因
  `build_patent_citation_monthly` 按总被引 top-5000 选专利，选出的全是最被引（= 已成熟/衰退）专利，
  天然不含新兴专利。目标④「识别 emerging」在当前 top-N 选样下不成立，需改选样（见 §5 待办）。

---

## 3. P2-1 引用图接 TKG 边源（❌ 前提证伪）

### 3.1 实测

- `tkg_edge_source=patent_citation`、`tkg_max_entities=2000`，`main.py --stage evaluate`：
  5 折全部跑完（walk-forward 切出有效 train/test），但**每折 test 三元组被转导协议整体剔除**——
  日志 10 条 `test 无已知实体三元组，CyGNet 评估跳过`（copy-only + CyGNet × 5 折），`tkg_mrr` 全 None。
- evaluate 按兜底逻辑自动回退共现投影（546 实体 / 10,904 事实），得共现图结果：
  CyGNet 0.9437±0.0796、copy-only 0.9453、RotatE 0.4480、Hits@10 0.9490。
  报告已如实标注 `tkg_edge_source_used=cooccur` + `tkg_fallback_reason`。

### 3.2 根因（结构性，非 bug）

1. **时态 DAG**：只能引用更早专利 → walk-forward test 窗口（最近数月）里的 tail（引用专利）是刚授权
   的新实体，train 从未出现；转导协议要求 head 与 tail 都 ∈ train 词表（`cygnet.evaluate_cygnet` 的
   `t["head"] in e2id and t["tail"] in e2id`），test tail 全新 → 全部剔除。
2. **单事件边**：每对专利只互相引用一次，(cited, cited_by, citing) 边无时间重复；CyGNet copy 靠
   `(s,r)` 历史里 **object（tail）重复**，但 tail 频次恒为 1 → copy 无法预测新引用专利。
3. **关键纠正**：计划书「奠基专利被大量后续专利反复引用 = copy 燃料」混淆了 **head 的度**（subject degree）
   与 **object 的时间重复**。前者在引用图上很高（head 度 889–3339），后者恒为 0。

### 3.3 A2 三图盘点（诚实）

| 图 | 重复性 | CyGNet vs RotatE | 结论 |
|---|---|---|---|
| 共现投影（`relates_to`） | 高（同文档反复共现） | 0.9459 vs 0.4487 | ✅ copy 赢，但是无向共现代理、非真实定向关系 |
| 定向 LLM 图（uses/improves/…） | 低（稀疏 + 问新链接） | 0.1621 vs 0.2390 | ❌ copy 输 |
| 专利引用图（`cited_by`） | 单事件 + 时态 DAG | 退化（无有效分） | ❌ 不适用 |

**尚无一张真实定向图上 CyGNet 反超 RotatE。** P2-1 的「引用图证明 copy 优势」目标无法达成，
回到计划 §4 守则 5 的兜底 ② 如实收尾。

---

## 4. 对后续的影响

- **P0-1 产物仍服务 P1-2**：`patent_citations.jsonl` 是目标③（真引用回归）+ 目标④（S 曲线）的真值，
  与 P2-1 是否成立无关，保留。
- **P5（每日增量）不受阻**：见 [P5_PLAN.md](P5_PLAN.md)；P0-3 的「时序深度累积」作用在 LLM 抽取图
  （共现/定向），与引用图无关；但其「A2 反超 = 喂更多历史」的叙事需按本文 3.3 重新措辞。
- **A2 最终口径建议**：以「共现图上 copy 占优」为达标证据，或以兜底 ② 收尾；不再把「专利引用图」当作
  A2 的反超路径。

---

## 5. 待办（跨 P5/P6）

- **S 曲线选样修正**（P1-2 遗留）：`build_patent_citation_monthly` 的 top-N 按总被引选样会系统性排除
  emerging 专利；改按「近期引用增速」或「分箱抽样」选样，才能让目标④ 覆盖 emerging/growth。
- 根目录残留调试脚本 `alpha_sweep_tmp.py / dim_sweep_tmp.py / debug_fusion_tmp.py` 可删。
