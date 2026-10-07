# Benchmark 对标报告（P1-3：外部基线 + 口径对齐）

> 本文保留上游设计和历史结果，未经本机复现；当前进展和本机验证见 [项目入口](../../README.md)。

> 目标：把「我们做得好不好」从「自己跟自己比」变成「跟已发表基准比」。
> 本表只做**口径对齐后的**对比，不拿不同口径的数字硬比。口径守则见文末。

---

## 0. 一页结论

| 本项目指标 | 本系统值 | 可比基准 | 基准值 | 可比性判定 |
|---|---|---|---|---|
| TKG filtered MRR（**共现图**，walk-forward） | **0.9459** | Science4Cast 语义网络链接预测（AUC） | 0.94–0.99 | ⚠️ 任务相近（共现/语义关联）但**图不同**，仅作「量级参照」 |
| TKG filtered MRR（**定向图**，3-way 时态） | **0.1621** | ICEWS18 CyGNet MRR | 0.2493 | ⚠️ 域不同（政治事件 vs 技术关系），仅示「时态协议」下合理区间 |
| 回归 RMSE（目标③，活动量代理） | 0.5269 | AIPatent CTPIR（引用量预测 RMSLE） | 见下 | ⚠️ 口径未对齐（代理 vs 真引用），P1-2 换真值后再比 |
| 排名 p@k（目标①） | 0.0 | 无直接公开基准 | — | ❌ 信号弱，留待更大数据 |

> **核心诚实声明**：0.9459（共现图）**不可**与 ICEWS/AIPatent 的 MRR 直接比——那是不同图、不同关系、不同域的绝对数。
> 它只说明「本系统在自建共现图上的相对表现」，对外有意义的参照系是**协议一致性**（filtered + 时态切分 + walk-forward），而非绝对分。

---

## 1. TKG 链接预测（目标②）—— 协议对齐的基线

ICEWS14/18/05-15 是 TKGC 标准基准（政治事件流），CyGNet/RotatE 的公开数字（filtered、时态切分）：

| 方法 | ICEWS14 MRR / Hits@10 | ICEWS18 MRR / Hits@10 | ICEWS05-15 MRR / Hits@10 |
|---|---|---|---|
| **CyGNet**（Zhu 2021 AAAI） | 0.3273 / 0.5067 | 0.2493 / 0.4261 | 0.3497 / 0.5294 |
| **TLogic**（Liu 2022 AAAI） | 0.343 / 0.543 | 0.284 / 0.453 | 0.365 / 0.556 |

> 来源：CyGNet 原始论文 / TLogic 论文的 comparison table（Cai 2022 TKGC 综述转引）。

**本项目对照**（同协议：filtered + 时态切分 + walk-forward + purge/embargo）：

| 本系统边源 | CyGNet MRR | RotatE 时态 MRR | 相对 ICEWS 的量级 |
|---|---|---|---|
| 共现投影（无向 relates_to） | 0.9459 ± 0.0765 | 0.4487 | ≫ ICEWS（因共现图高复现，copy 天然占优，非算法更强） |
| 定向 tech→tech（稀疏） | 0.1621 | 0.2390 | 低于 ICEWS CyGNet（因定向图 86.5% 新链接，copy 无史可复） |

**解读**：ICEWS 数字说明「时态外推 MRR 的合理区间在 0.2–0.35」。本项目共现图 0.9459 远超此区间，
是因为**共现图的任务本身更简单**（无向对称、高复现），不是模型更强；定向图 0.1621 低于区间，是因为
**数据形状**（稀疏 + 问新链接）与 copy 机制相克——这正是 P0-1 专利引用图要解决的（定向 + 高重复 = 两者兼得）。

---

## 2. 专利引用域（P0-1 目标域）—— AIPatent

AIPatent（Zong et al., arXiv:2210.00450）是与本项目**同域**的基准：AI 专利（CPC 过滤）、2002–2021、
20 个年度快照，含 `citedBy` / `relatedTo` 两种边。但注意其公开任务与口径：

| 维度 | AIPatent 做法 | 本项目对照 |
|---|---|---|
| 边类型 | `citedBy`（前向引用）+ `relatedTo` | P0-1 只做 `cited_by`（前向引用），与 AIPatent `citedBy` **直接可比** |
| 任务 | **引用轨迹/引用量预测**（citation trajectory） | 目标③ 回归（换真引用后同任务） |
| 指标 | **RMSLE / MALE**（不是 MRR） | 目标③ MAE/RMSE/MAPE |
| 切分 | 10 年训练 → 10 年预测 | walk-forward（expanding）+ purge |

> **结论**：AIPatent 证明「专利引用预测」的学术口径是**回归指标（RMSLE/MALE）**而非链接预测 MRR。
> 本项目 P1-2 把目标③换成真引用时序后，应补报 **RMSLE** 以与 AIPatent 对齐（当前只有 MAE/RMSE/MAPE）。

---

## 3. 语义网络链接预测 —— Science4Cast

Science4Cast（Krenn & Zeilinger 2020 PNAS；arXiv:2210.00881）把「预测未来高影响概念」形式化为
语义网络链接预测，AUC 0.94–0.99。这是与本项目**共现图**最接近的评测范式：

| 维度 | Science4Cast | 本项目共现图 |
|---|---|---|
| 图 | 概念语义网络（共现/相似） | Concept×Concept 共现投影 |
| 任务 | 预测未来概念关联 | 时态外推 `relates_to` |
| 指标 | AUC 0.94–0.99 | MRR 0.9459 |

> 口径接近（都是「概念共现」代理），但 Science4Cast 报 AUC 而非 filtered MRR，**不直接换算**；
> 若要正式对标，需在共现图上补报 ROC-AUC。

---

## 4. 口径守则（贯穿 P0–P2，本表遵守）

1. **filtered 口径**：TKG 一律报 filtered MRR/Hits，不与 raw 混比。
2. **时态切分**：与 ICEWS/Science4Cast 对齐时间切分，禁用 shuffle；train<val<test 时间不重叠。
3. **同协议对比**：CyGNet 时态 vs RotatE 时态（walk-forward），不与随机切分（P2=0.2734）混比。
4. **真值独立**：目标②（新关联）/③（引用量）/④（S 曲线阶段）各有独立真值，不交叉。
5. **诚实**：不同域/不同图的绝对分不硬比；0.9459 是「共现图相对表现」不是「超 ICEWS」。

---

## 5. 待补（数据/口径就绪后）

- [ ] P1-2 换真引用时序后，目标③ 补报 **RMSLE**（对齐 AIPatent）。
- [ ] 专利引用图（P0-1 全量历史）就绪后，补 `cited_by` 图上的 CyGNet vs RotatE filtered MRR，与 AIPatent `citedBy` 直接可比。
- [ ] 共现图补报 ROC-AUC（对齐 Science4Cast）。
