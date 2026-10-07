# 两项目合并方案计划

> 本文保留上游设计和历史结果，未经本机复现；当前进展和本机验证见 [项目入口](../../README.md)。

> 承接 [COMPARISON_REPORT.md](../reports/COMPARISON_REPORT.md)。合并目标：**把她的「信号模型 + 排序评估 + 工程规范」装进我的「知识图谱 + 时序推理 + 严格验证」骨架**，并补上双方都缺的「真正的多智能体协同」。
>
> 状态：**方案定稿（文档层面）**，代码级合并等老师反馈后再启动。每个阶段给「目标 / 落点 / 验收 / 风险」。

---

## 合并主线（一句话）

> **信号引擎（她）** 注入 **图引擎（我）**，统一验证口径，最后补 **多智能体协同** 作为合并后的核心突破点。

```
她的贡献：相对注意力份额+动量信号 · NDCG/Spearman/Top-1 Lift 排序评估 · DeepSeek 研报范式 · 工程规范(缓存/限速/配置)
                    │  注入/对齐
                    ▼
我的骨架：数据层(6源) → 图谱层(Neo4j+对齐) → 预测层(RotatE/CyGNet/TLogic/回归/融合) → 编排层(hermes+HITL+notify)
                    │  补全
                    ▼
共同补：真正的多智能体协同（记忆/反思/规划）—— 课题三要素的最后一块
```

---

## 阶段 0 —— 统一仓库与目录（以我的 repo 为主干）

- **目标**：确立合并后代码的唯一归属与包结构，她作为「信号子包」并入。
- **落点**：
  - 我的 `tech-trend-kg-agents` 作为主干仓库。
  - 引入她的 `Attempt/Shared/` 为一个新子包，例如 `techtrend/signal/`：
    - `http_client.py`（PoliteApiClient：SQLite 缓存 + 限速 + 指数退避）→ 替换/增强我的 `sources/*` 的 HTTP 层。
    - `processors/cleaner.py`（单向因果平滑）、`detector.py`、`normalize.py` → 作为特征工程前置。
    - `agents/reporting_agent.py`（DeepSeek 直连）→ 增强我的 report 层。
  - 引入她的 `configs/topics.yaml`、`sources.yaml` 为「话题/源配置层」，并入我的 `config.py`。
- **验收**：`git clone` 主干后能跑通她 signal 子包的最小单测；`--list` 阶段不变。
- **风险**：两边都用 `config.py` 同名模块，合并时需命名空间隔离（`signal.config` vs 我的 `techtrend.config`）。

---

## 阶段 1 —— 信号层注入（救目标① p@k=0）

- **目标**：用她的「相对注意力份额 + EMA/MACD 动量」替换/补充我失效的 Kleinberg 突发，把 precision@k 从 0 拉正。
- **做法**：
  1. 在她的 `scoring.py` 基础上实现 `share_t = (count_t+1)/(Total_t+N)` + `Growth = MACD/EMA`，适配我的 6 源月度计数。
  2. 我已有 `fusion.py`（三路融合：Kleinberg + TKG + 回归），把「Kleinberg 突发」这一路换成「相对份额动量」信号。
  3. 真值用我的 `future_growth_top_k`（未来 6 月增速 top-k），重跑 `--stage predict`。
- **验收**：precision@k > 0 且稳定；与「未来增速 top-k」真值有正交集；保留 Kleinberg 作消融对照。
- **风险**：她的模型主题粒度粗（5–6 个主题），我的实体是 545+ Concept 细粒度——信号模型需要按 Concept 聚合，工程量中等。若 Concept 级份额噪声大，退回到「主题级榜单 + Concept 级 TKG」双层。

---

## 阶段 2 —— 评估体系对齐（补排序指标）

- **目标**：补齐我缺的排序类指标，与她的口径对齐。
- **做法**：在我的 `prediction/evaluation.py` 增加 `top1_lift / spearman_rho / ndcg_at_k`，对目标①（新兴识别）与目标②（链接预测排序）都补报。
- **验收**：`eval_metrics.json` 同时含 filtered MRR/Hits/MAE 与 NDCG@3/5/Spearman/Top-1 Lift；报告里两套指标分区，不混比。
- **风险**：低。纯指标工程，复用 scipy `spearmanr` + 手写 ndcg（她已有实现可参考）。

---

## 阶段 3 —— 数据源补齐（7 源）

- **目标**：合并为 7 源（我的 6 源 + 她的 CrossRef），并把她的 topics 配置并入。
- **做法**：
  1. 我的 `sources/` 加 `crossref.py`（DOI 锚点 + 增量），她的 `data_collectors/crossref.py` 可复用。
  2. 她的 5–6 主题（Robotics/AI Agents/Embodied/LLM/Quantum/Edge）作为「主题级信号」层，与我的「Concept 级图谱」层并存（双层粒度）。
- **验收**：7 源全通、`--list` 阶段不变；topic 信号与 concept 图谱数据流串通。
- **风险**：CrossRef 与 OpenAlex 有重叠（都以 DOI 对齐），需复用我已有的实体对齐（DOI 强锚点）去重。

---

## 阶段 4 —— 报告层统一

- **目标**：统一成「她的 DeepSeek 研报叙事 + 我的 notify/HITL/可视化」。
- **做法**：
  1. 用她的研报 prompt 范式（榜单解读 + 回测可靠性 + 行动建议）替换/增强我的 `report.py` 的叙事。
  2. 保留我的 `notify` 推送 + `reviewer` HITL 卡点 + `viz/dashboard.py` 仪表盘。
- **验收**：`report.md` 含榜单解读 + 四目标总览；dashboard 图与报告数字一致。
- **风险**：低。双方都已跑通 DeepSeek 直连，仅合并 prompt 与输出路径。

---

## 阶段 5 —— 补真正的多智能体协同（核心突破点）

- **目标**：把课题三要素里「多智能体协同」从「角色化编排」升级为「真·多智能体推理」——这是合并后最有说服力的贡献点。
- **做法**（对齐 Generative Agents / CAMEL / MetaGPT 范式）：
  1. **记忆**：我的 Neo4j 四元组 + 每日增量，天然可作为多智能体的**共享记忆**（她 `Memory_Design` 的设想，我已有图存储）。
  2. **角色分工**：采集 agent / 抽取 agent / 信号 agent（她）/ 链接预测 agent（我）/ 审校 agent（HITL）/ 报告 agent，由 hermes-agent 委派调度（我已有 6 角色骨架）。
  3. **反思/辩论**：让「信号 agent」（她的动量判断）与「链接预测 agent」（我的 TKG 判断）对同一批技术**交叉质证**，不一致时触发 HITL 审校——这是真正意义上的「协同」而非串行。
  4. **规划**：把「每日爬取→预测→报告」固化成 SKILL 沉淀（hermes skills 已具备）。
- **验收**：一次端到端运行中，两个 agent 对同一候选技术给出独立结论 + 合并/冲突记录，可审计。
- **风险**：最高。需要 hermes-agent 稳定性 + 多 agent 编排成本；可先降级为「两路信号 + 规则合并 + HITL」的确定性协同，再逐步 LLM 化。

---

## 建议的实施顺序与里程碑

| 里程碑 | 阶段 | 对应救的短板 | 建议排期 |
|---|---|---|---|
| M1 骨架合并 | 阶段 0 | 工程统一 | 第 1 周 |
| M2 信号注入 | 阶段 1 | 我 p@k=0 | 第 2 周 |
| M3 评估对齐 | 阶段 2 | 我缺排序指标 | 第 2 周 |
| M4 数据源补齐 | 阶段 3 | 她无专利/中文 | 第 3 周 |
| M5 报告统一 | 阶段 4 | 叙事统一 | 第 3 周 |
| M6 多智能体协同 | 阶段 5 | 双方共同短板 | 第 4–6 周 |

> 关键红线（沿用我方守则）：**不「调到赢」**——引入她的信号模型是为了让数据忠实于问题，不是为了把指标做漂亮；所有口径变更如实记录。
