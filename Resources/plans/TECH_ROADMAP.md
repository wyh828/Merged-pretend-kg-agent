# 技术路线文档 —— 多源数据驱动的技术趋势预测系统

> 本文保留上游设计和历史结果，未经本机复现；当前进展和本机验证见 [项目入口](../../README.md)。

> 本文档对 [PROJECT_PLAN.md](PROJECT_PLAN.md)、[P0_PLAN.md](P0_PLAN.md) 与 P1 阶段计划做一次**面向审查的完整解读**，回答"每个数据源怎么采、框架用在哪、是否需要 AI API、各阶段元组/数据流/依赖关系、hermes-agent 怎么调度、多智能体体现在哪"等问题。
>
> 阅读定位：不是重写计划，而是把计划里分散的决策串成一条可审查的技术路线。所有结论均来自三份计划文档 + 已落地的 P0 代码，未实现的部分标注为"计划"。

---

## 0. 一页速览

| 维度 | 结论 |
|---|---|
| 课题目标 | 论文/专利/新闻/GitHub 多源数据 → 动态知识图谱 → **多智能体协同**预测技术趋势 |
| 聚焦领域 | 泛 AI / 计算机科学 |
| 架构 | 分层解耦：数据层 → 图谱层 → 预测层 → 编排层（底层 Python pipeline 独立可运行） |
| 顶层编排 | hermes-agent（cron + skills + 多 agent 委派 + MCP），可降级为 APScheduler |
| 图谱存储 | Neo4j（本地 Docker），事实用四元组 `(s, r, o, t, source)` |
| 预测核心 | 静态 KG 嵌入(RotatE/TuckER) + 时序 KG 推理(CyGNet/TGN) + 科技挖掘信号(Kleinberg/主题) + 集成 |
| 验证 | walk-forward 回测，用前 N 年数据预测后一月，filtered MRR / Hits@K / precision@k / MAE |
| 当前进度 | P0–P2 已交付；P3 已交付但**验收未达标**（CyGNet 时态 MRR 0.479 < RotatE 0.654，见 §12）；P4–P6 待实现 |

---

## 1. 总体架构（分层与解耦）

```
┌──────────────────────────────────────────────────────────────┐
│ 编排层   hermes-agent（cron 定时 / SKILL 沉淀 / 多agent委派 / 报告推送） │
│         （降级兜底：APScheduler / 直接 python cron.py）            │
├──────────────────────────────────────────────────────────────┤
│ 预测层   ①新兴识别 ②链接预测外推 ③指标时序回归 ④S曲线阶段          │
├──────────────────────────────────────────────────────────────┤
│ 图谱层   Neo4j 动态知识图谱（四元组 (s,r,o,t,source)）             │
├──────────────────────────────────────────────────────────────┤
│ 数据层   OpenAlex/arXiv | USPTO/EPO | GDELT | GitHub API（每日增量）│
└──────────────────────────────────────────────────────────────┘
```

**关键设计原则**：底层 Python pipeline 与 hermes-agent **解耦**。调度器只负责"定时触发 `cron.py`"，业务代码不知道是谁在调度它。这样 hermes-agent 若不稳定，可无损降级到 APScheduler，主体成果（采集/图谱/预测）不受影响。

---

## 2. 数据采集层

### 2.1 每个数据源的采集方式（API / 爬取 / 文件下载）

这是最容易混淆的一点，按采集方式分类如下：

| 分类 | 数据源 | 具体方式 | 角色 |
|---|---|---|---|
| **REST API** | OpenAlex | `GET api.openalex.org/works`，`filter` 增量 + `cursor` 分页 | 论文主源 |
| **REST API** | Crossref | REST，`from-index-date` 增量 | DOI 锚点 |
| **REST API** | Semantic Scholar | REST | 补充 |
| **REST API** | GitHub | 官方 Search API（`created:>date stars:>=N` 模拟新晋热门） | GitHub 主源 |
| **REST API** | USPTO ODP / PatentsView | REST，需 key | 专利主源 |
| **REST API** | EPO OPS | REST + OAuth2，每周 4GB | 专利补充 |
| **协议接口(HTTP)** | arXiv | OAI-PMH 协议（`from/until` 增量，本质 HTTP） | 论文前沿源 |
| **文件下载** | GDELT GKG | 按天下载 GKG 文件（每 15 分钟更新一次的全量文件） | 新闻主源 |
| **文件下载** | DBLP | 直接下载 XML dump | 论文校验 |
| **文件下载** | EPO OPS 周前文件(ST36) | 周增量文件下载 | 专利增量 |
| **HTML 爬取** | GitHub trending 页 | 爬 trending 页面取周期热门标签（唯一需爬 HTML 的场景） | GitHub 热门标签 |

**一句话结论**：绝大多数是 **REST API**（httpx 即可）；**文件下载**只有 GDELT/DBLP/EPO 周文件；**HTML 爬取**只有 GitHub trending 页一处。

### 2.2 爬取框架用在哪个数据源？

- **主选**：`httpx + aiohttp + asyncio + tenacity`（重试/限速）。因为数据源基本都是 REST，无需重型爬虫。
- **Scrapy**：仅当需要**大规模 HTML 爬取**时用 → 即 **GitHub trending 页**。
- **Playwright**：仅 GitHub trending 页兜底（有 JS 渲染时）。

即：**爬取框架只服务于 GitHub trending 页**，其余一律走 httpx。

### 2.3 RSSHub 自建服务

RSSHub 不是独立数据源，而是采集层的一个**自建服务**（中文新闻源）：

- 用 Docker 起官方镜像 `docker run -d -p 1200:1200 diygod/rsshub`。
- 从官方文档挑目标路由（36氪/虎嗅/机器之心/量子位等，每站点一个 `/xxx/yyy` 路由）。
- 配置缓存与上游请求间隔做限速，避免触发目标站点反爬。
- 下游用 **httpx** 按 RSS 更新频率定时拉取，天然复用 asyncio 主选框架。

**是否需要 API/AI 驱动**：RSSHub 本身是纯 HTTP 抓取服务，**不需要任何 LLM API**。但它只给标题/链接/摘要/时间，**无实体/tone**，所以抓回来的中文新闻内容需要后续 **LLM 抽取**（P2）来补实体与情感，这属于抽取层而非 RSS 服务本身。

### 2.4 是否需要 AI API？自动还是手动？

分三层看，结论不同：

| 层 | 是否需 LLM API | 说明 |
|---|---|---|
| **数据采集** | 否，全自动 | httpx 发 HTTP 请求 / 下载文件，纯代码自动化，无 LLM |
| **抽取（P1）** | 否 | 用 OpenAlex **结构化字段**直接映射三元组，零 LLM、零幻觉 |
| **抽取（P2 起）** | **是** | 用 **DeepSeek API**（OpenAI 兼容、json 输出）从文本抽取技术实体/关系，以及中文新闻实体/tone |
| **预测** | 否 | pykeen / TKG / XGBoost 等模型自动，无 LLM |

所以：**采集全程自动（无 AI API）；LLM API 只在 P2 的抽取环节出现**。P1 为了跑通基线，刻意把 LLM 推迟，用结构化元数据代替。

### 2.5 每日调度：hermes-agent cron vs APScheduler

| 维度 | hermes-agent cron | APScheduler |
|---|---|---|
| 定位 | 编排层**主选** | 底层**降级/解耦兜底** |
| 能力 | 自然语言/表达式调度、挂 SKILL、多 agent 委派、推 Telegram/Discord | 纯定时，无 UI、无分布式 |
| 优点 | 与整体架构统一，体现课题"结合 hermes-agent" | 轻量、Python 原生、稳定 |
| 缺点 | 框架新、稳定性待验证 | 功能单一 |

**关键设计**：底层用 `cron.py` 入口（逻辑与 `main.py` 一致），既可被 hermes-agent cron 调用，也可被 APScheduler 调用。**换调度器不动业务代码**。

---

## 3. 知识图谱构建层

### 3.1 四大功能在目录里的位置

图谱层功能 = **存储、抽取、对齐、动态更新**，在目录中的落点（P0 骨架 + P1 计划）：

```
techtrend/
  extraction/                  ← 抽取
    structured.py              # P1：结构化三元组抽取（无 LLM）
    （P2 起加 LLM 抽取模块）      # P2：LLM 抽取技术实体/关系
  graph/                       ← 存储 + 动态更新
    neo4j_client.py            # 驱动封装：连接/索引/幂等 MERGE
    loader.py                  # triples → Neo4j
    （P2 起加 entity_alignment 模块）← 对齐
  stages/
    extract.py                 # 抽取阶段入口（调 extraction）
    build_graph.py             # 存储阶段入口（调 graph.loader）
```

| 功能 | P1 落点 | P2 增强 |
|---|---|---|
| 抽取 | `extraction/structured.py`（字段映射） | `extraction/` 加 LLM 抽取 |
| 存储 | `graph/neo4j_client.py` + `loader.py` | 四元组 schema 扩展 |
| 对齐 | —（单源无需对齐） | `graph/` 或 `extraction/` 加实体对齐模块 |
| 动态更新 | 带 `time`/`source` 字段 + `MERGE` 幂等 upsert | 事件流存储 + 按时间切快照 |

### 3.2 Neo4j 存储的输入 / 输出

**输入（写）**：`data/interim/triples.jsonl`，每行 `{head, head_type, relation, tail, tail_type, time, source}`。

- 节点标签（P1）：`Paper`(openalex_id, title, pub_date)、`Concept`(openalex_id, name)、`Author`(openalex_id, name)、`Institution`(openalex_id, name)。
- 关系类型：`BELONGS_TO` / `AUTHORED_BY` / `AFFILIATED_WITH` / `CITES`，属性 `{time, source}`。
- 唯一约束 + `Concept.name` 索引，`MERGE` 幂等（重跑不重复）。

**输出（读）**：
- 预测层：RotatE 从 `triples.jsonl` 直接构造 pykeen `TriplesFactory`（不直接读 Neo4j）；P3 的 GNN/TKG **直接从 Neo4j 读子图**（Neo4j 与图神经网络/LangGraph 集成好）。
- 可视化：Neo4j 浏览器 `http://localhost:7474`。
- 报告 agent：通过 MCP 查询 Neo4j。

### 3.3 P1 与 P2 阶段"元组"的区别

| 维度 | P1（单源 + 静态 KG） | P2（多源 + 动态 KG） |
|---|---|---|
| 数据源 | 仅 OpenAlex | + arXiv / USPTO / GDELT / GitHub / RSSHub 中文新闻 |
| 元组来源 | **结构化字段映射**（无 LLM） | **LLM 抽取**（DeepSeek）补技术实体/关系 |
| 实体类型 | 4 类：Paper/Concept/Author/Institution | + 技术/方法/模型/框架/数据集/机构/人物 |
| 关系类型 | 4 种：belongs_to/authored_by/affiliated_with/cites | + 使用/改进/对比/属于/针对/竞品/因果 |
| 时间维度 | 带 `time`+`source`，但预测时静态（RotatE 忽略时间） | 正式四元组 `(s,r,o,t,source)`，动态更新 |
| 实体对齐 | 无（单源） | 强 ID 锚点 + string matching + LLM 消歧 |

**一句话**：P1 = 单源、结构化、静态、四类学术实体；P2 = 多源、LLM 抽取技术实体、四元组带时间戳、跨源对齐、动态更新。

---

## 4. 预测算法层

### 4.1 RotatE 与 pykeen 是什么

- **RotatE**：一个知识图谱嵌入模型（Sun et al. 2019 ICLR），用复数空间旋转建模对称/组合关系，是静态 KG 链接预测的稳定基线。
- **pykeen**：知识图谱嵌入的 Python 库，内置 TransE/RotatE/TuckER 等模型 + 标准评估（filtered MRR / Hits@K）。

**本项目的实现方式**：用 pykeen 的 `pykeen.pipeline.pipeline(model="RotatE", ...)` 一次跑出 filtered MRR / Hits@1/3/10，从 `result.metric_results` 取指标。**即"RotatE 的实现 = 调 pykeen 库"，不自研算法。**

### 4.2 推荐组合（三层融合）

```
① 静态打分层   RotatE/TuckER → 技术-技术新关联候选可行性分
② 时序主干层   CyGNet(或 TGN) 外推 + TLogic 可解释规则
③ 信号融合层   Kleinberg 突发 + DTM 主题 + SAO 语义网络 → 特征拼接
④ 集成预测     XGBoost / 轻量 MLP → 排序列表
⑤ 解释输出     S 曲线阶段标签
```

**MVP 先做**「Kleinberg 突发 + 静态 KG 链接预测」两个基线（P1），再上 TKG 主干与融合（P3）。

---

## 5. 验证与评估层

- **切分**：walk-forward / rolling origin（expanding window），`train < val < test` 时态切分，**禁止 shuffle**。
- **防泄漏**：scaler/imputer 只在训练段 fit；purge + embargo；新实体保证 train/test 实体组不相交。
- **指标**：链接预测 filtered MRR / Hits@1/3/10；分类 precision@k/recall/AUC/F1；回归 MAE/RMSE/MAPE。
- **ground truth**：以"事后发生的事实"为真值，前 N 年数据 → 预测未来一月/一年。

---

## 6. hermes-agent 编排层与多智能体

### 6.1 需要 hermes-desktop 吗？项目有独立 UI 吗？

**不需要任何桌面 UI 来调度**。澄清三点：

1. **调度核心**是 hermes-agent 的 `cronjob` 能力（自然语言/表达式定时），它调用底层 `cron.py`，通过 CLI/配置方式即可运行。
2. **底层完全独立**：`python cron.py` 直接跑，或用 APScheduler 定时，不依赖 hermes-agent 存在（P5 才接 hermes-agent）。
3. **项目当前无独立 UI**：P0 是 CLI（`main.py`）；可视化/报告前端在 P6 才交付。

> 注：三份计划文档通篇使用 **hermes-agent**（NousResearch/hermes-agent，自进化 agent 框架），未提及"hermes-desktop"。若它是 hermes-agent 的某个桌面形态，也**不是调度所必需**——编排能力来自 hermes-agent 的 cron/skills/委派，而非某个 GUI。

### 6.2 多智能体体现在哪（课题要求）

多智能体协同是课题要求，体现在**编排层的角色化 agent 设计**（6.2 节，这是研究贡献点，需自行设计而非只用内置委派）：

| 角色 agent | 职责 |
|---|---|
| 采集 agent | 调度/监控各数据源每日增量 |
| 抽取 agent | LLM 抽取实体关系，写入 Neo4j |
| 分析 agent（可并行多个） | 突发检测 / 主题演化 / 链接预测 / 时序回归 |
| 预测/集成 agent | 融合多路信号，产出排序预测 |
| 审校 agent（人在环） | 预测结论写报告前暂停人工确认（HITL） |
| 报告 agent | 生成日/周趋势报告，推送渠道 |

底层机制：hermes-agent 的 `delegate_task` 子 agent 委派 + kanban 队列。**注意**：底层 Python pipeline 本身是"多阶段串行"（非多智能体），多智能体协作发生在 hermes-agent 顶层（P5 落地）。

---

## 7. 分阶段路线（P0–P6）

| 阶段 | 目标 | 交付物 | 验收标准 |
|---|---|---|---|
| **P0 脚手架** | 目录/依赖/配置/日志 | 可运行空 pipeline | `python main.py` 跑通 ✅已落地 |
| **P1 单源+静态KG+基线** | OpenAlex→结构化抽取→Neo4j→RotatE+Kleinberg | 单源 MVP | 跑出基线 MRR/precision |
| **P2 多源+动态KG** | 接入 arXiv/USPTO/GDELT/GitHub + RSSHub；四元组+时间戳；实体对齐 | 多源动态 KG | 五源实体对齐、增量更新 |
| **P3 时序预测** | CyGNet/TGN 外推 + TLogic 规则 + 融合 | 预测模块 | ⚠️ 外推 MRR/Hits 优于静态基线（**未达标**，见 §12） |
| **P4 验证体系** | walk-forward + purge/embargo + 前N年→后一月 | 评测脚本 | 四指标齐备、无泄漏 |
| **P5 hermes-agent 自动化** | cron 调度 + 角色 agent + 报告推送 | 全自动 pipeline | 每日无人值守跑通 |
| **P6 可视化/报告** | 趋势图 + S 曲线阶段 + 周报 | 前端/报告 | 可演示 |

**范围控制**：P0–P2 必做；P3 时间紧可用「静态链接预测 + Kleinberg + 轻量时序回归(XGBoost)」替代重型 TKG；P5 是"结合 hermes-agent"的落地，务必保留。

---

## 8. 数据流与文件依赖关系

### 8.1 宏观数据流（分层）

```
数据层(collect) → 抽取层(extract) → 图谱层(build_graph) → 预测层(predict) → 报告层(report)
```

### 8.2 P1 文件级数据流（阶段间接口契约）

| 阶段 | 输入 | 输出 |
|---|---|---|
| collect | config 起止日期 | `data/raw/openalex/<date>/works_<cursor>.jsonl` + `data/interim/works.jsonl` |
| extract | `works.jsonl` | `data/interim/triples.jsonl` |
| build_graph | `triples.jsonl` | Neo4j（节点/边 + 计数） |
| predict | `triples.jsonl`(RotatE) + concept 月度频次(Kleinberg) | `output/baseline_metrics.json` + `output/burst_concepts.csv` |
| report | `baseline_metrics.json` | `output/report.md` |

### 8.3 P0 与 P1 的依赖关系

**P0（已实现）= 骨架，P1 在骨架上填肉。** 依赖方向：

```
main.py / cron.py ──调用──> pipeline.py ──编排──> stages/（5 个桩）
                              ↑
                         config.py（改） + logging_config.py（复用）
```

- **P0 交付、P1 复用/改动**：
  - `main.py` / `cron.py`（CLI 入口，复用，仍支持 `--stage`）
  - `techtrend/pipeline.py`（阶段串行，复用）
  - `techtrend/stages/base.py` + 5 个 stage（**桩改实现**）
  - `techtrend/config.py`（**改**：新增 OpenAlex/预测参数）
  - `techtrend/logging_config.py`（复用，不改）
  - `requirements.txt` / `.env.example` / `.gitignore` / `README.md`（改）

- **P1 新增模块**（被 stage 调用）：
  ```
  techtrend/sources/openalex.py          ← CollectStage 调
  techtrend/extraction/structured.py     ← ExtractStage 调
  techtrend/graph/neo4j_client.py        ← BuildGraphStage 调
  techtrend/graph/loader.py
  techtrend/prediction/kleinberg.py      ← PredictStage 调
  techtrend/prediction/rotatE.py
  techtrend/prediction/metrics.py
  ```

### 8.4 整个项目文件 ↔ 阶段功能 ↔ 数据流的全景图

```
[编排层 P5] hermes-agent cron / APScheduler
      │  定时触发
      ▼
[入口] cron.py ──复用──> main.py（argparse CLI：--stage / --list）
      │
      ▼
[pipeline.py] 按序执行 get_default_stages(settings) 返回的 5 个阶段
      │
      ├─(1) CollectStage ──> sources/openalex.py ──httpx──> OpenAlex API
      │                        └─输出 works.jsonl
      ├─(2) ExtractStage ──> extraction/structured.py（P1 无LLM / P2 换LLM）
      │                        └─输出 triples.jsonl
      ├─(3) BuildGraphStage ─> graph/neo4j_client.py + loader.py
      │                        └─写入 Neo4j（四元组 + time/source）
      ├─(4) PredictStage ──> prediction/rotatE.py（pykeen）+ kleinberg.py + metrics.py
      │                        └─输出 baseline_metrics.json
      └─(5) ReportStage ──> 渲染 report.md
```

**依赖方向总结**：`main.py/cron.py → pipeline.py → stages/ → sources|extraction|graph|prediction 模块 → 外部（OpenAlex API / Neo4j / pykeen）`。下层不感知上层，调度器只调入口，业务模块不感知调度器。

---

## 9. 关键术语解释（审查速查）

| 术语 | 含义 |
|---|---|
| **桩（stub）** | P0 里 5 个 stage 的"占位实现"：继承 `Stage` 基类，`run()` 只打一行日志并返回 `{"status":"stub",...}`，无业务逻辑。P1 起逐个替换为真实实现。 |
| **管线（pipeline）** | `pipeline.py` 的 `Pipeline` 类，按序执行 collect→extract→build_graph→predict→report，收集每个阶段的结果摘要。 |
| **四元组** | 事实 = `(s, r, o, t, source)`：主语/关系/宾语 + 时间 + 来源，相比三元组多了时间与来源，支撑动态更新与按时间切快照。 |
| **filtered MRR/Hits@K** | 链接预测标准指标；filtered 剔除已存在三元组，避免被"同样正确"的三元组错误扣分。 |
| **walk-forward** | 滚动回测，尊重时间序，模拟"用过去预测未来"，多期评测。 |
| **Kleinberg 突发** | 词频突发检测（Kleinberg 2002 两状态自动机），识别上升词，作新兴技术信号。 |
| **pykeen** | KG 嵌入库，提供 RotatE/TuckER 等模型 + 标准评估，本项目用它实现 RotatE。 |
| **MCP** | Model Context Protocol，hermes-agent 通过它接 Neo4j、封装爬虫/预测为 MCP server。 |
| **HITL** | Human-in-the-loop，审校 agent 在报告前暂停人工确认。 |

---

## 10. 审查要点清单（Checklist）

审查计划/代码时，逐条对照以下关键一致性：

1. **数据源采集方式**：API 走 httpx；文件下载只有 GDELT/DBLP/EPO 周文件；HTML 爬取只有 GitHub trending 页。
2. **LLM 边界**：P1 无 LLM（结构化抽取）；P2 起用 DeepSeek（json 输出）；采集/预测无 LLM。
3. **调度解耦**：`cron.py` 与 `main.py` 逻辑一致，换调度器不动业务代码。
4. **元组演进**：P1 四类学术实体 + 结构化四关系；P2 加技术实体 + LLM 抽取 + 四元组 + 对齐。
5. **Neo4j 输入输出**：写 triples.jsonl → 节点/关系；读子图供 GNN/TKG、可视化、报告 agent。
6. **时态切分**：train 早 test 晚，禁止 shuffle，scaler 只 fit 训练段（P4 补 purge/embargo）。
7. **评估指标**：链接预测必须报 **filtered** MRR/Hits@K。
8. **密钥管理**：所有 key 进 `.env`（gitignore），GitHub 只用 public 只读最小权限。
9. **多智能体**：体现在 hermes-agent 角色化 agent（P5），非底层 pipeline；底层是多阶段串行。
10. **验收**：P0=`main.py` 跑通；P1=`baseline_metrics.json` 出现非空 filtered MRR/Hits@K/precision@k。

---

## 11. P3 时序预测：概念与联系链路补充解读

> 本节是对 [P3_PLAN.md](P3_PLAN.md) 的术语与链路补充，面向审查与理解，不是重写计划。
> 状态：P0–P2 已落地（代码在 `techtrend/`），P3 为「计划」（本文档第 0/7 节的进度注记暂未更新到 P3，见文末）。

### 11.1 一条链：四个目标如何决定「数据长什么样、模型怎么选」

整个项目的地基是一句因果：**课题的四个预测目标，倒逼数据必须长成某种形状，模型必须按某种方式选型。** 把这个链捋直：

```
课题四目标                              需要的「事实」形态                  P3 建模手段
─────────────────────────────────────────────────────────────────────────────────────
① 新兴/热门技术识别         → 谁在近期突然变热                      → Kleinberg 突发 + 三路融合排名
② 技术间新关联预测         → 「技术 A —关联— 技术 B」的时序边       → TKG 外推（CyGNet / TLogic）
③ 技术指标时序外推         → 每个技术随时间变化的数值序列            → 时序回归（HistGradientBoosting）
④ 成熟度/S曲线阶段         → （可视化/阶段标注）                    → 留 P6
```

其中 **② 是 P3 的主干，也是最别扭的一环**：目标②要预测「技术之间的关联」，但 P2 图谱里**根本没有技术→技术的边**（只有文档→技术的边）。于是 P3 的第一件大事不是建模，而是**把数据「投影」成目标②需要的样子**。这条数据↔建模的完整链路是：

```
collect（六源 raw/interim）
  → extract（triples.jsonl + nodes.jsonl；LLM 抽出的都是 doc→tech 边）
  → align（把 Technology/Method/.../Dataset 折叠成统一 Concept，补 entity_id）
  → build_graph（Neo4j 四元组 (s,r,o,t,source)）
  → predict（P3：投影成 tech→tech 共现边 → 时态切分 → TKG 外推 / 回归 / 融合）
```

一句话结论：**P2 解决「有哪些实体、实体间直接提到什么」，P3 解决「把文档级信息投影成技术级关联，再用时间维度预测未来关联」。**

### 11.2 关键文件各司其职

| 文件 | 归属 | 作用（一句话） |
|---|---|---|
| `data/interim/works.jsonl` | collect(OpenAlex) | 归一化后的论文（标题/摘要/概念/作者/引用） |
| `arxiv.jsonl` `patents.jsonl` `news.jsonl` `github.jsonl` | collect | 其余五源的归一化文档 |
| `github_stars.jsonl` | collect(GitHub) | 每日 star 快照（P2 起记录，供趋势信号） |
| `data/interim/triples.jsonl` | extract→align | **事实流**：每行一条 `(head,relation,tail,time,source)`，对齐后补 `head_id/tail_id` |
| `data/interim/nodes.jsonl` | extract→align | 实体注册表：`{id, type, entity_id, name, source}` |
| `data/interim/alignment.jsonl` | align | 对齐审计：谁锚到谁（`entity_id`/`anchor_id`） |
| `output/baseline_metrics.json` | predict(P1/P2) | Kleinberg + RotatE（随机切分）指标，**P3 保持向后兼容** |
| `output/temporal_metrics.json` | predict(P3) | **新增**：TKG 外推 + 回归 + 融合指标 |
| `output/tkg_rules.jsonl` `forecast.csv` `fusion_ranking.csv` | predict(P3) | 挖掘出的规则 / 逐实体预测 / 融合排名 |
| `prediction/temporal.py` | P3 新 | **投影 + 时态切分 + 实体编码**（TKG 数据准备，P4 换 walk-forward 只改这里） |
| `prediction/cygnet.py` | P3 新 | CyGNet 复制机制模型 + copy-only 基线 |
| `prediction/tlogic.py` | P3 新 | 时序规则挖掘 + 打分（可解释层） |
| `prediction/regression.py` | P3 新 | 指标时序回归（目标③） |
| `prediction/fusion.py` | P3 新 | 三路信号融合排名（目标①） |
| `prediction/rotatE.py` `kleinberg.py` `metrics.py` | P1/P2 复用 | 静态基线 / 突发检测 / 排名指标 |

### 11.3 数据流动全景图（P3 版）

```
data/interim/
  works.jsonl ──┐
  arxiv.jsonl ──┤
  patents.jsonl ┤─ extract（结构化 + LLM）──► triples.jsonl + nodes.jsonl（以 doc→tech 边为主）
  news.jsonl ───┤                              │
  github.jsonl ─┘                              ▼
                                align（技术实体折叠为 Concept，补 entity_id）
                                               │
                                               ▼
                                build_graph ──► Neo4j（四元组落库）
                                               │
                                               ▼
                                predict（P3，读 interim 文件，不直接读 Neo4j）
                                  ├─ temporal.project_t2t：doc→tech 投影成 Concept×Concept 共现边 relates_to
                                  ├─ temporal.temporal_split_3way：按时间切 train/val/test
                                  ├─ cygnet / tlogic：TKG 外推 → tkg filtered MRR/Hits（目标②）
                                  ├─ regression：逐 Concept 月度序列 → MAE/RMSE/MAPE（目标③）
                                  └─ fusion：Kleinberg + TKG + 回归 → 融合排名（目标①）
                                               │
                                               ▼
                                report ──► report.md（读 baseline + temporal 两个 json）
```

### 11.4 术语逐一解释（通俗 + 本项目实例）

**① doc→tech 边 vs tech→tech 边**
- `doc` = 源文档节点（Paper 论文 / Patent 专利 / Repo 仓库 / News 新闻），`tech` = 技术实体（Technology/Method/Model/Framework/Dataset）。
- P2 的 LLM 抽取产出的是 **doc→tech** 边：例如「论文 X 使用了 Transformer」→ `(X, uses, Transformer)`，**头是文档、尾是技术**。
- 目标②要的「技术间新关联」是 **tech→tech** 边：`(Transformer, 关联, 注意力机制)`。P2 数据里**没有**这种边。
- 一句话：**P2 只有「文档提到哪些技术」，没有「技术之间怎么关联」。**

**② 实体对齐 / 折叠为 Concept**
- 对齐（见第 3 节）：把不同来源、不同写法的同一实体合并到统一 `entity_id`。
- P2 的 `alignment.py` 把 LLM 抽出的 `Technology/Method/Model/Framework/Dataset` 全部**折叠（映射）成 `Concept`** 类型（`_MATCH_TARGET` 表），所以对齐后「技术实体」在数据里统一叫 `Concept`——这是 P3 投影时说「Concept×Concept」的由来。

**③ 实体跨时间重复出现 / 时态切分后 test 的 Paper 几乎全不在 train 中**
- TKG 外推 = 用过去预测未来。被预测的实体**必须有一段历史**可查，模型才能「复制/推断」它未来的关联。
- 论文（Paper）是**一次性**实体：一篇论文只在自己发表那天出现一次，之后不再产生新关联。按时间切分后，test 段（未来窗口）里的论文都是**新论文，train 段（历史）里从没见过** → 模型对它们没有任何历史信息，无法预测。
- 技术实体（Concept）则**跨时间反复出现**（「Transformer」2020 和 2024 的论文都会提），所以它才有「历史」，才适合做时序预测。
- 一句话：**时间序列预测只能预测「有历史的东西」，一次性文档节点没有历史，持久技术实体才有。**

**④ 投影出 Concept×Concept 共现边 relates_to**
- **投影** = 不重新抽取，把「文档→技术」的边**间接转化成「技术→技术」的边**。
- 做法：若文档 D 同时提到了技术 A 和 B，就生成一条 `(A, relates_to, B)`，时间戳 = D 的时间；共现次数低于阈值（`tkg_min_cooccur`）的边丢弃以去噪。
- **共现** = 共同出现（co-occurrence）。**对齐后技术实体已折叠为 Concept** = 见 ②。

**⑤ 关联代理、非定向 uses/improves**
- 共现只是「两个技术在同一文档里被一起提到」，是「有关联」的**弱信号（代理 proxy）**，不等于「A 使用了 B」（uses）或「A 改进了 B」（improves）这种**有方向、有语义**的关系。
- **非定向** = `relates_to` 没有方向（A↔B 对称）；`uses/improves` 有方向（A→B ≠ B→A）。

**⑥ 追加一次 LLM 技术对抽取（加在什么时候）**
- 时机：**P3 完成后、作为可选增强**（P3.5 或 P4 之前），不阻塞 P3 验收。
- 做法：新写一个 LLM prompt，输入文档，让模型直接输出 `技术A → uses/improves/... → 技术B` 的**定向 tech→tech 三元组**，替换共现投影。
- 为什么不在 P3 做：P3 的验收只看「外推 MRR 是否优于静态基线」，共现投影零成本、零 LLM 调用就能先跑通整条链路；定向抽取要额外 LLM 成本 + 新抽取模块，故留作增强。

**⑦ 外推 MRR/Hits、静态基线、filtered**
- **MRR**（Mean Reciprocal Rank）：对每条测试三元组 `(s,r,o)`，把真实 `o` 在所有候选实体里按模型打分排名，取 `1/排名` 的均值（排第 1 得 1.0，第 10 得 0.1）。
- **Hits@K**：真实 `o` 排进前 K 的比例（Hits@10 = 排进前 10 的比例）。
- **filtered**：排名时剔除「除正确答案外、其它其实也算对的已有事实」，避免被"同样正确"的实体挤下去而误扣分。
- **外推** = 用历史(train)训练，预测未来(test)窗口里**新出现**的事实。
- **静态基线** = RotatE（不看时间的静态 KG 嵌入），P2 实测 filtered **MRR 0.2734 / Hits@10 0.3746**。

**⑧ 时态切分 vs 随机切分（为什么两种 MRR 不可直接比）**
- **随机切分**：把三元组随机打散成 train/test（8:2），train/test 实体高度重合。这是静态 KG 补全（FB15k/WN18）的标准做法。
- **时态切分**：按 `time` 排序，train=早、test=晚，**时间不重叠**。这才是「用过去预测未来」，但 test 里会出现 train 没见过的新实体。
- 不可比的原因：随机切分下模型「见过」多数 test 实体，天然更好答；时态切分更难（含新实体、无泄漏）。所以 **P3 不拿 CyGNet(时态) 比 RotatE(随机)**，而是同协议对比（见 ⑨）。

**⑨ CyGNet(时态切分) vs RotatE(时态切分)**
- RotatE 是**静态**模型：看不到时间。即便用时态切分，它也只是在「历史事实」上学实体嵌入、再做补全，**利用不了「某技术在什么时间点与谁关联」的时序规律**。
- CyGNet 是**时序**模型，靠「**复制机制**」：预测 `(s,r)` 未来的尾实体时，直接参考 `s`、`r` 历史上跟哪些实体关联过（越近、越频繁权重越高），再叠加「嵌入生成」的新候选（复制 + 生成两分支）。技术演化高度重复，复制机制正好契合。
- 验收：**CyGNet(时态) > RotatE(时态)**，即「用时序信息」确实比「不用时序」更准——这就是「外推 MRR/Hits 优于静态基线」的严格版。

**⑩ 两级范围控制（Tier1 / Tier2）**
- **Tier1**（先跑通流程，低成本）：`copy_only_score` = CyGNet 复制模式的**确定性退化版**（只看「(s,r) 历史出现过哪些尾实体」按频次+时间衰减打分，完全不训练）+ TLogic 规则（从历史挖掘「若 A 关联 B 且 B 关联 C，则 A 可能关联 C」这类**可读规则**）。产出**第一个时态 MRR**，验证数据流与评估口径正确。
- **Tier2**（达验收）：完整 **CyGNet**（复制 + 生成两分支，**负采样训练**学习实体/关系嵌入），把指标推到超过静态基线。
- 一句话：**先零训练跑通，再上重模型冲指标。**

**⑪ sklearn HistGradientBoosting 轻量替代 XGBoost**
- XGBoost 是流行梯度提升树库，但要额外安装、依赖较重。scikit-learn 自带的 `HistGradientBoostingRegressor` 是同类梯度提升树（直方图加速），效果相近、够用，且 P1 已装 scikit-learn → **零新增依赖**。P3 用它做目标③回归，XGBoost 列为可选。

**⑫ 融合三路信号 / Kleinberg precision@k=0**
- **融合** = 把三个独立信号各自归一化后加权求和，得到一个统一的「新兴技术」排序：
  1. Kleinberg 突发权重（近期是否突然变热）；
  2. TKG 分（CyGNet 认为该技术未来成为关联目标的可能性）；
  3. 回归增速（该技术未来活动量的预测增速）。
- **Kleinberg precision@k=0** 是 P2 的实测：单独用 Kleinberg 检出的「突发概念」与真值（未来 6 月增速 top-k）交集为 0——检出的都是「Identification (biology)」这类**泛化概念，不是真技术趋势**。这正是 P3 要上融合的原因：单路信号不够，多路融合看能否改善新兴识别的 precision@k。

**⑬ baseline_metrics.json 保持向后兼容，新增 temporal_metrics.json**
- `baseline_metrics.json` 是 P1/P2 就有的输出（Kleinberg + RotatE 随机切分指标），`report.py` 读它。
- P3 **不改它的结构**（旧报告脚本不坏 = 向后兼容），新指标写进**新文件** `temporal_metrics.json`（TKG + 回归 + 融合），`report.py` 再同时读两个文件。

**⑭ temporal.py 投影方案 / 「有时序维度的预测阶段」**
- `temporal.py` 是 P3 数据准备的核心：把 `triples.jsonl` 里 doc→Concept 的边**投影成 Concept×Concept 共现边**，再按时间做 3-way 切分，喂给 CyGNet/TLogic。把「投影 + 切分 + 编码」收在一个文件，P4 换 walk-forward 时**只改这一处**。
- P1/P2 的 predict 是**静态 KG 补全**：只问「两实体间缺哪条边」，不管时间、随机切分。P3 的 predict **有时序维度**：问「未来某时间点，这个技术会跟谁产生新关联」，用时间切分 + 时序模型外推。
- 一句话：**预测层从「补全已有的静态关联」升级为「预测未来尚未发生的关联」。**

### 11.5 一句话速记

| 概念 | 一句话 |
|---|---|
| doc→tech 边 | 文档「提到」了某技术（P2 只有这种） |
| tech→tech 边 | 技术之间「如何关联」（目标②要的，P3 用投影补出来） |
| 投影 | 不重抽，借「同文档共现」把文档级边变成技术级边 |
| 共现 relates_to | 关联的弱信号，非定向、无语义（uses/improves 才定向） |
| 时态切分 | 按时间前后切，不 shuffle，模拟「用过去预测未来」 |
| 随机切分 | 打散切，实体共享，静态 KG 补全的玩法 |
| TKG 外推 | 用历史事实预测未来新事实 |
| CyGNet 复制机制 | 参考「历史关联过的尾实体」来猜未来尾实体 |
| filtered MRR/Hits | 剔除"同样正确"干扰后的排名指标 |
| Tier1/Tier2 | 先零训练跑通，再上重模型达验收 |
| 融合 | 突发 + 时序 + 回归三路加权排序 |
| baseline vs temporal | 旧指标不动、新指标另存新文件 |

---

> **文档一致性提示**（留给后续维护）：第 0 节「当前进度」与第 7 节路线图已同步到 P3（2026-09-22）。实际 P1（`0673ac3`）、P2（六源 + 对齐）已交付；P3 全量交付但验收未达标，完整结论与 5 个关键问题解答见 §12 与 [P3_PLAN.md](P3_PLAN.md)「验证结果」。

---

## 12. P3 交付、验收结论与关键问题解答

> 状态：本节是 P3 **实际跑通后的结论**（2026-09-22），取代 §11 中「P3 为计划」的措辞。原始数据见 [P3_PLAN.md](P3_PLAN.md)「验证结果」。

### 12.1 交付内容与验收结论

**交付模块**（`techtrend/prediction/` 新增 7 文件 + `stages/predict.py` / `stages/report.py` 接线）：

| 模块 | 作用 |
|---|---|
| `temporal.py` | doc→Concept 投影为 Concept×Concept 共现边 `relates_to` + 时态 3-way 切分 + 实体编码（P4 换 walk-forward 只改此处） |
| `cygnet.py` | CyGNet 复制机制（copy 历史频次 + generate 嵌入打分，`α·copy+(1-α)·generate`）+ copy-only 确定性基线 |
| `tlogic.py` | 时序规则挖掘（可解释层） |
| `regression.py` | HistGradientBoosting 指标时序回归（目标③） |
| `fusion.py` | Kleinberg 突发 + TKG + 回归三路融合排名（目标①） |
| `metrics.py` | 扩展 `mrr_at/hits_at/mae/rmse/mape` |
| `stages/predict.py` | `_run_tkg` / `_run_forecast` / `_run_fusion`（子任务失败不互阻） |

**输出**：`output/temporal_metrics.json`（新）+ `tkg_rules.jsonl` + `forecast.csv` + `fusion_ranking.csv`；`baseline_metrics.json` 保持向后兼容（仍写 P2 随机切分指标）。

**实测指标**（时态切分 train/val/test = 7610/1076/2170，实体 545，投影边 1433 → 事实流 10856）：

| 指标 | 值 | 一句话含义 |
|---|---|---|
| CyGNet `tkg_filtered_mrr`（α=0.5） | 0.4790 | 真实 tail 平均排 ~第 2.1 名 |
| copy-only `tkg_copyonly_mrr` | 0.5435 | 纯复制基线，平均 ~1.84 名 |
| RotatE 时态对照 `rotate_temporal_mrr` | **0.6539** | 平均 ~1.53 名（Hits@10 = 0.7911） |
| P2 静态基线（随机切分） | 0.2734 | 仅参考，随机/时态口径不同不可直接比 |
| TLogic 规则 | 1（symmetry, conf=1.0） | 单关系下退化 |
| 回归 RMSE / 融合 precision@k | 0.7310 / 0.0000 | 融合仍检不出真趋势（同 P2） |

**验收结论：❌ 未达标** —— 验收标准是「CyGNet filtered MRR（时态）> RotatE filtered MRR（同时态、同协议）」。实测 **0.4790 < 0.6539**，且 copy-only（0.5435，CyGNet 复制机制的最强形态）也低于 RotatE。这是**数据特性下的真实结果，非 bug**（多组对照证实，见 Q3/Q4）。

### 12.2 发现的数据特性（根因，简述）

1. 共现图**稠密且对称**（无向 `relates_to`，每文档 C(n,2) 边）→ 嵌入泛化优于 copy 复现；
2. 测试集 **99% 复现查询**（335/338 条 (s,r) 在 train 见过，新查询仅 3）→ generate 的「新链接」优势无处发挥；
3. copy 与嵌入**同源**（都学共现结构）→ oracle 融合上限仅 0.545；
4. **单关系** → TLogic 退化为 1 条 symmetry 规则。

逐条对算法的影响机制详见 **Q3**。

### 12.3 两个数据决策（相对计划书字面 `head_type∈{Paper,Patent,Repo,News}` 的偏离）

1. **排除 News/GDELT 于共现投影**（`tkg_doc_types=Paper,Patent,Repo`）——见 Q5。
2. **过滤 future-dated OpenAlex 数据**（`tkg_max_time` 默认今天）——OpenAlex 有少量日期在未来的坏记录，若不滤会污染时态切分（train 混入未来），滤除后切分才严格「过去→未来」。详见 Q5。

### 12.4 建议的下一步方向（按优先级）

1. **定向技术关系**（LLM 抽取 uses/improves）：无向共现是 copy 劣势的根源，定向 + 稀疏图更贴近「重复技术关联」；
2. **序列化 generate 模式**（GRU 编码实体历史）：真 CyGNet 的 generate 是序列编码器，可捕捉「近期重复」；
3. **放宽验收口径**：以「copy-only 与静态 DistMult 同量级」或「CyGNet 结构完整 + TLogic 可解释 + 回归/融合全通」为验收，把「超 RotatE」留到定向关系图；
4. **数据/配置调参**：提高 `tkg_min_cooccur` 得稀疏图或扩大数据量（须如实报告，避免「调到赢」）。

### 12.5 关键问题解答（5 问）

#### Q1 定向技术关系和序列化 generate 能优化 RotatE 时态对照 MRR 吗？

**能，且是排序最高的两个方向，但性质不同、把握也不同。**

- **定向技术关系（uses/improves）——把握较大，是「治本」方向。** 当前 `relates_to` 是**无向共现**：一篇文档提到 A、B 两个技术就产生一条对称边，整张图**稠密且对称**。copy 机制的强项是「精确复现历史 (s,r)→o」，而嵌入模型（RotatE/DistMult）的强项是「传递式泛化」——在稠密对称图上，嵌入能靠「A 与 B 共现、B 与 C 共现 → A 与 C 相似」的传递性把分数铺开，压制了 copy 的逐条复现。换成**定向、稀疏、有语义**的 uses/improves 边后：每条边的方向明确、重复的 (s,r,o) 组合更集中，copy 的「历史里谁用过谁」就更有判别力，预期能反超或至少追平 RotatE。代价是需要**新增一次 LLM 技术对抽取**（额外 token 成本 + 新抽取模块），所以 P3 未做、列为后续。
- **序列化 generate（GRU）——有可能，但把握较低、依赖数据量。** 当前实现的 generate 模式是**静态 DistMult 打分**，与 RotatE 同属「静态嵌入」一族，天生被 RotatE 的上限压住。**真 CyGNet 的 generate 分支是序列编码器（GRU 编码实体历史）**，能捕捉「这个技术最近半年反复与谁关联」的**近期重复**信号，这是静态 RotatE 完全没有的能力。若换成序列化 generate，理论上可能反超 RotatE；但当前数据量小（1433 边 / 10856 事实 / 545 实体），序列模型易过拟合，收益不保证，且要改 `cygnet.py` 的 `generate_logits`。

一句话：**定向关系改的是「数据形状」（治本、把握大）；序列化 generate 改的是「模型容量」（治标补能力、把握小）。** 两者都直指 12.2 的根因，但都需额外工作、未在 P3 内验证。

#### Q2 详细解释验收指标和值分别代表什么？

**指标口径：**
- **filtered MRR（Mean Reciprocal Rank，平均倒数排名）**：对每条测试事实 `(s, r, o, t)`，模型给「主语 s 在关系 r 下指向所有候选实体」打分并排序，看真实 `o` 排第几名 `rank`，取 `1/rank` 再对全部测试事实求均值。排第 1 名 = 1.0，第 2 名 = 0.5，第 10 名 = 0.1，越接近 1 越好。
- **filtered（过滤）**：排名时先剔除「对同一 (s,r) 而言**其它也正确**的 tail」——一个技术可能同时关联多个技术，模型把某个「同样正确」的实体排在 `o` 前面不该被扣分。filtered 就是剔掉这些干扰后再算排名，是链接预测论文的默认口径。
- **Hits@K**：真实 `o` 排进前 K 的比例。Hits@1 = 精确命中率，Hits@10 = 排进前 10 的比例。

**本项目各值的含义：**

| 值 | 含义 |
|---|---|
| CyGNet MRR = 0.4790 | 平均排名 ≈ 1/0.479 ≈ **第 2.1 名**：多数情况下真实关联技术排在第 2 名左右 |
| copy-only = 0.5435 | 平均 ≈ 第 1.84 名：纯复制历史比「复制+生成混合」还略好 |
| RotatE 时态 = 0.6539 | 平均 ≈ 第 1.53 名，且 Hits@10 = 0.7911 表示 **79%** 的真实 tail 排进了前 10 |
| P2 静态基线 = 0.2734 | 平均 ≈ 第 3.7 名，但这是**随机切分**下的值，与上面的**时态切分**口径不同，**不能直接比大小** |
| 融合 precision@k = 0.0000 | 三路融合排序的 top-k 与「未来增速 top-k」真值交集为 0：单靠现有信号仍检不出真趋势（与 P2 Kleinberg 单独 0 一致） |
| 回归 RMSE = 0.7310 | 概念月度活动量预测的均方根误差（相对归一化频次的量级） |

**为什么 P2 的 0.2734 比 P3 的 0.6539「低却不算差」**：随机切分下 train/test 实体高度重合、且任务是「补全已知静态图」，天然更容易；但 P2 当时是静态 KG 补全口径。P3 的 0.6539 是**时态切分**（用过去预测未来、含新实体、更难）下的 RotatE，两者不可比。P3 验收只比「同时态切分」的 CyGNet vs RotatE。

#### Q3 详细解释数据特性对算法的影响？

| 数据特性 | 机制 | 对算法的影响 |
|---|---|---|
| **① 共现图稠密且对称** | `relates_to` 无向，一篇文档提 k 个技术就产生 C(k,2) 条对称边，图整体密集、无方向 | 嵌入模型靠「传递相似性」（A~B、B~C → A~C）在密集图上**泛化得更好**；copy 的「精确复现」被淹没在大量等价共现边里。结果：DistMult=0.576、RotatE=0.654 均 > copy=0.5435 |
| **② 测试集 99% 复现查询** | 335/338 条测试事实的 (s,r) 在 train 段已出现过，全新 (s,r) 仅 3 条 | CyGNet 的 **generate 分支**唯一占优的场景是「预测从未见过的 (s,r) 的新链接」，这个场景几乎不存在，所以 generate 的优势**无处发挥**；而「复现查询」正是 copy 和嵌入都擅长的，两者拉不开差距 |
| **③ copy 与嵌入同源** | 两者本质都在学「谁和谁共现」——copy 学频次、嵌入学向量，信息同源 | copy 无法给嵌入「补盲」。oracle 融合（每条事实取 copy/generate 的较优者）MRR 只有 0.545，且 generate 仅在 **2.1%** 事实上优于 copy → 融合天花板极低 |
| **④ 单关系** | 投影后只有一条 `relates_to` 关系 | TLogic 规则空间塌缩为「对称性」1 条规则（conf=1.0），可解释但无判别力；CyGNet 的 relation 维度退化，模型学不到「不同类型关系」的差异 |
| **⑤ 数据规模小** | 1433 边 / 10856 事实 / 545 实体 | 序列模型（GRU）等重型时序模型易过拟合；静态嵌入在小图上反而更稳，这也是 RotatE 占优的隐性原因 |

**一句话**：这组数据**天然偏袒「静态嵌入泛化」、压制「时序复制/生成」**，所以 CyGNet 这类时序模型的复制优势在当前数据形状下无法兑现——这正是验收未达标的深层原因。

#### Q4 详细解释附加验证的目的和原理是什么？

**目的**：区分「验收失败是**数据本质**还是**实现瑕疵**」——即证明「copy < RotatE」是这条数据上**稳健成立**的结论，而不是某个实现细节（损失函数、打分方式、超参、衰减设计）恰好选错导致的假象。

**原理**：**单变量对照**。固定其它一切不变，只改一个可疑因素，看结论是否翻转；都不翻转 → 结论稳健。

本轮做的附加验证（均不改变结论）：

| 验证项 | 改了什么 | 排除了什么 |
|---|---|---|
| 时间衰减 copy（半衰期 30~1095 天） | 给历史 tail 加「越近权重越高」的衰减 | 排除「copy 没用是因为没考虑时间远近」——加了衰减仍不提升 |
| 损失函数（负采样 margin vs 全词表 softmax） | 换训练目标 | 排除「训练目标选错导致 generate 学不好」 |
| 训练轮数（30/50/100） | 换 epoch | 排除「欠拟合/过拟合」 |
| 打分方式（DistMult 逐元素乘 vs 相加） | 换 generate 打分族 | 确认 DistMult 已是该族里较好的（0.48，但仍 < copy） |
| oracle 融合 | 每条事实取 copy/generate 最优 | 给出「copy+generate 组合的理论上限」= 0.545，证明即便完美融合也赢不了 RotatE |

**结论**：所有附加验证均未翻转「copy < RotatE」，故把失败归因于数据特性（Q3）而非实现 bug，是可信的。

#### Q5 两个数据决策有无其它解决方法？排除 News/GDELT 是否意味着这两个数据源失效了？

**决策 1：排除 News/GDELT 于共现投影 —— 有其它解法，但都不如「先排除」务实：**

| 替代方案 | 可行性 | 说明 |
|---|---|---|
| 只采**多日** GDELT（跨窗口快照） | 中 | 当前 GDELT 只取了「某一天 0 点文件」的 15 分钟切片 → 单日快照形成**一个巨大时间组**，时态切分后 val/test 为空。若改为连续多天下载，主题事件就能形成时间序列，才可纳入投影 |
| **重新主题过滤**成技术实体 | 中 | 当前 GDELT 主题是**事件主题**（CYBER_ATTACK、TECH_AUTOMATION…）而非「技术实体」，投影到 Concept×Concept 语义不匹配。需换一套「技术实体」粒度的抽取/映射才可用 |
| 把 GDELT 当**独立事件 TKG** | 高（另一目标） | 不为目标②服务，而是另立一个「事件共现图」做「事件趋势」预测，与 Concept 共现图分开 |
| 保持现状（排除） | 高（已采用） | 目标②的 Concept×Concept 投影不需要事件主题，排除零成本、不损失信息（事件仍走其它信号） |

**决策 2：过滤 future-dated OpenAlex 数据 —— 基本无替代，是唯一正确做法：**
- 这些是**坏数据**（发布日期在「今天」之后），不是可抢救的合理值。可选做法只是「过滤到哪天」：默认过滤到 `today`，或固定一个快照日期（如 `2026-09-22`）以保证**复现性**。若错误地把 future 记录留在 train，时态切分就「train 里混进了未来」，泄漏 + 违反「过去预测未来」假设。

**排除 News/GDELT 是否意味着这两个数据源失效了？——不失效，只是「不进入共现投影」这一个环节。**

GDELT/News 在系统中仍有三个明确用途，只是不参与目标②（技术间新关联）的共现投影：
1. **静态图谱**：`build_graph` 仍写入 News 的 `mentions` / `tone` 等边与实体，落进 Neo4j 四元组；
2. **信号层**：Kleinberg 突发、指标回归、三路融合都仍可用新闻实体/提及做信号；
3. **潜在独立任务**：未来可把 GDELT 事件流做成独立的「事件 TKG」预测事件趋势。

所以准确说法是：**News/GDELT 在「Concept×Concept 共现投影」这个具体步骤被排除（因为其数据形态——单日快照 + 事件主题——与该步骤的输入假设不匹配），而非「数据源失效」**。它对应的预测目标（事件趋势、技术热度的新闻侧信号）完全保留。

---

## 13. 目标—数据特性—算法—数据处理—检测值—优化方向 对照表

> 本节把「四个预测目标 → 数据长什么样 → 选什么算法 → 做了什么数据处理 → 检测值是什么意思、结果是多少 → 下一步往哪优化」压成一张因果链表，并回答一个关键问题：**P3 验收未达标后，优化方向是「硬选一个算法、改数据去适配它」还是「基于数据特性与原理综合考量三者」——答案是后者**，判定依据见表格后【判定】。

| 目标 | 数据特性 | 算法 | 数据处理 | 检测值含义和结果 | 优化方向 |
|---|---|---|---|---|---|
| ② 技术间新关联预测（链接预测） | **无向共现、稠密、对称、单关系**：每文档 k 个 Concept 产 C(k,2) 条对称边，图密集无方向 | **copy-only**（纯复制历史 (s,r)→o 频次，零训练） | `project_t2t`：doc→Concept 投影为 Concept×Concept 共现边 `relates_to` → 3-way 时态切分（train<val<test） | filtered MRR **0.5435** ≈ 真实 tail 平均排第 **1.84** 名；复制机制的最强形态 | 定向关系（治本）：无向共现是 copy 劣势根源，定向+稀疏使「历史谁用过谁」有判别力 |
| ② 技术间新关联预测 | 同上 + **99% 复现查询**（335/338 条 (s,r) 在 train 见过，新查询仅 3）→ generate 的「新链接」优势无处发挥 | **CyGNet**（α·copy + (1-α)·generate，generate=DistMult 静态打分） | 同上；负采样 + margin 训练，α=0.5 固定 | filtered MRR **0.4790** ≈ 平均第 **2.1** 名；copy+generate 混合反低于纯 copy，因 generate 与 copy 同源（都学共现结构） | ①定向关系（主）；②**序列化 generate（GRU 编码实体历史）**——建议**数据量增加后再用**（当前 545 实体/10856 事实，GRU 易过拟合） |
| ② 技术间新关联预测（对照） | 同上；静态嵌入靠「传递相似性」（A~B、B~C→A~C）在稠密对称图上泛化占优 | **RotatE 时态对照**（静态嵌入，同时态同协议切分） | 同上（与 CyGNet 同一「过去=train+val、未来=test」数据公平对比） | filtered MRR **0.6539** ≈ 平均第 **1.53** 名，Hits@10 **0.7911**（79% 进前 10）；P2 静态基线（随机切分）0.2734 仅参考、口径不同不可直接比 | 作固定对照、不「调」；定向+稀疏图下重跑三者，观察 copy/CyGNet 是否反超（不预设赢家） |
| ① 新兴/热门技术识别 | 突发信号检出的是**泛化/消歧类通用概念**（"Identification (biology)"、"Work (physics)"），非真技术趋势 | Kleinberg 突发 + 三路融合（突发 + TKG + 回归增速加权） | `build_concept_monthly_counts` → `future_growth_top_k`（未来 6 月增速 top-k 真值） | precision@k **0.0000**（Kleinberg 单独、三路融合均为 0）：检出 top-k 与真值交集为空 | 更大数据 + 更好信号（补真引用数/star 时序）；融合暂不改善，留 P5 数据积累后重评 |
| ③ 技术指标时序外推 | 月度活动量序列短；`cited_by_count` 未入 works.jsonl、star 快照稀疏 → 只能以「活动量」为代理 | HistGradientBoosting 回归（sklearn，轻量替代 XGBoost） | `build_concept_monthly_counts` → `build_lag_features`（前 lag 月）→ 回测（前 N-horizon 训、后 horizon 测） | RMSE **0.7310** = 概念月度活动量预测的均方根误差（相对归一化频次量级）；MAE/MAPE 同口径 | 补 `cited_by_count`（openalex.normalize）、多日 star 快照，得真引用数/star 时序再回归 |
| ④ 成熟度/S曲线阶段 | （未做） | （未做） | （未做） | （留 P6） | 留 P6：趋势图 + S 曲线阶段标注 + 周报 |

**【判定：优化方向是「基于数据特性与原理综合考量」，不是「硬选算法、改数据去适配」】**，三点依据：

1. **不是「算法输了就换算法」**。P3 的结论不是「CyGNet 不好」，而是经多组单变量对照（时间衰减 copy、负采样 vs 全词表 softmax、30/50/100 轮、DistMult 打分、oracle 融合上限 0.545）确认的**稳健事实**：在「无向共现 + 单关系」这一数据形状下，三者的真实排序是 RotatE > copy-only > CyGNet，且不是实现瑕疵。
2. **改数据是为了「让数据忠实于问题」，不是为了赢**。目标②问的是「技术间**新关联**」，而 `relates_to` 无向共现自 P3 起就明确标注为「关联代理」（`project_t2t` 的诚实声明），天然缺失方向与语义。定向 uses/improves 是**更贴近问题本身的构造**——这是修正数据设计的捷径，不是「调到赢」。
3. **三者对比始终保留、口径不放松**。优化后重跑的是**同样的三算法、同样的「同时态同协议」**（CyGNet 时态 vs RotatE 时态），并保留共现投影作消融对照——没有「预先把赢家固定成 CyGNet 再改数据」。真正的「调到赢」红线（如无原则调 `tkg_min_cooccur` 直到 copy 翻盘）在计划里被明确禁止，须如实报告。

**序列化 generate（GRU）的建议**：**数据量增加后再用**。真 CyGNet 的 generate 分支是序列编码器（GRU 编码实体历史），能捕捉「近期重复」——这是静态 RotatE 完全没有的能力，也是模型侧唯一可能反超的手段；但当前 545 实体 / 10856 事实的规模下，序列模型易过拟合、每实体历史样本不足，收益不保证。故 P3.5 默认关（`tkg_sequence_generate=False`），待 P5 每日增量积累数据、定向图变丰富后，再作为模型侧增强启用。

## 14. P3优化、P4收尾

### 14.1 数值标准「0.1621 < 0.2390」这个水平表示什么
三个问题分别答：


这是 **filtered MRR（Mean Reciprocal Rank，平均倒数排名）**。含义是：把「预测 (s, r, ?, t) 的 tail」当作一次排名任务，在所有候选概念里给每个概念打分排序，看正确 tail 排第几，再取 `1/排名` 的平均。

- `1 / 0.1621 ≈ 6.2` → CyGNet 平均把正确 tail 排到 **第 6 名左右**
- `1 / 0.2390 ≈ 4.2` → RotatE 平均排到 **第 4 名左右**

候选集是定向图的转导词表 **545 个概念**，纯随机猜的 MRR 约 `1/273 ≈ 0.004`。所以 0.16 / 0.24 **远高于随机**——两个模型都确实学到了结构，不是没信号；但绝对水平偏低，这是「新链接预测」任务本身难造成的（86.5% 的正确 tail 是训练里从没见过的 (s,r) 组合）。

「❌」指的是验收口径：标准是 **CyGNet 必须 > RotatE（同时态、同 filtered 协议）**，而 0.1621 < 0.2390，所以判未达标。这里「同协议」= 两者都用同一套时态切分（train/val/test = 800/110/226）+ 同一套 filtered 剔除（剔除 train+val+test 里已存在的三元组），比较是公平的。

### 14.2. 不调整 P3 优化，能回到 0.47/0.54/0.65 吗

**技术上能，一行配置的事，但回到去也没用。**

- 共现图（`cooccur`）的代码路径**完整保留作消融对照**，把 `tkg_edge_source` 切回 `cooccur` 即可复现。事实上 P4 walk-forward 在共现图上跑出的 CyGNet 是 **0.9459**（copy-only 0.9419），比原 P3 单次切分的 0.4790 还高——因为 walk-forward 的测试窗更靠近期、复现占比更高。
- 原 P3 共现图的四个数（我这边记录的是）：CyGNet **0.4790**、copy-only **0.5435**、DistMult **0.576**、RotatE **0.6539**（你写的「0.73」我这里无对应记录，最接近是 0.654，若你指别的口径我再核）。

**但关键点**：回到共现图**照样过不了 A2**——共现图上 CyGNet 0.4790 **仍然 <** RotatE 0.6539（P3 当时就是因为这个验收未达标）。那 0.5~0.7 的高数字是「测试集 99% 是复现查询」的数据特性造成的：copy 直接背下历史就能高分，不代表 CyGNet 比 RotatE 强。换句话说，**高数字 ≠ 达标**，而且高数字是复现图的假象——这正是当时要做定向图优化的原因。

所以「回到 0.47/0.54/0.65」不是出路：既通不过验收，也不是更诚实的水平。

### 14.3. B1-TKG 回退的「时态跨度不足」具体指什么

具体是**定向边没追到最新数据**，不是图建错了：

- 定向 tech→tech 边靠 LLM 二次 pass（`_run_openalex_tech_pairs`）从 OpenAlex works 抽取，但**那次抽取只覆盖到 ~2025-06 的 works**。
- 结果定向图里 **2025 全年只有 15 条事实、2026 一条都没有**。
- walk-forward 需要「近期连续时间窗」来当 test 折；没有 2026、2025 只有 15 条 → 最靠右的 test 窗口要么为空、要么全是 train 里没出现过的全新概念（被转导协议整体剔除）→ **没有任何有效折** → 只能回退到共现图。

根因是抽取时间没追平数据：`works.jsonl` 其实已经含 2026-09 的作品，只是定向 pass 没重跑。**重跑 `--stage extract`** 就能把 2025-06 → 2026-09 的定向对补进 `triples`，定向图时态跨度补全后 B1-TKG 就大概率不用回退了。

### 14.4. P4/P3 指标优化实施后验（2026-09-23 重跑 extract 的结果）

按 `P4_P3_METRIC_OPT_PLAN.md` §5 顺序落地后，重跑 `extract → align → evaluate` 实测：

**① 定向图时态跨度已补全（P0-2 达成）。** 重跑后定向事实从 15 条 → **969 条**（933 条去重边），时间分布 2023-01 → 2026-09（含 2026-09 的 9 条），不再是「2025 全年 15 条 + 2026 一条没有」。

**② 但 B1-TKG 仍回退共现图 —— 且原因变了。** 上一条 14.3 说「时态跨度补全后大概率不用回退」，实测**没有兑现**：walk-forward 现在能切出 1 个有效折（train=960, test=9），但那 9 条 test 事实的 head/tail **全是在 train 里从没出现过的新实体**，被转导协议（`encode_ids(train)` 建词表 + test 未知实体剔除）整体剔除 → CyGNet/RotatE 都报「test 无已知实体三元组」→ MRR 为空 → 回退共现图。

这恰好印证了 §14.1 的「86.5% 正确 tail 是 (s,r) 新组合」：**定向 tech→tech 边本质是新链接**，近期新边端点必然无历史，copy 机制无史可复。回退消息已改为如实区分两种成因（时态不足 / test 实体无历史）。

**③ 专利前向引用图（P0-1）是正解，但全量历史被网络阻断。** 本地 USPTO XML 已抽出 **210,392 条 `cited_by` 前向引用边**（奠基专利被反复引用的「高重复」正是 copy 燃料）；但本地 XML 只有单周时态跨度（全部 time=2026-09-15），PatentsView S3 bulk 下载在本环境返回 **403**、BigQuery 需账号。`patent_citation` 边源 + 引用时序回归 + S 曲线代码全就绪（`PATENT_CITATION_SOURCE=patentsview` 网络放开即可跑全量，届时 P1-2 换真引用真值、P2-1 在 `cited_by` 图上补 CyGNet vs RotatE 与 AIPatent 直接可比）。

**④ P1-1 已回填。** `cited_by_count` 此前被 normalize 漏掉；写 `backfill_cited_by_count.py` 用 `ids.openalex` 过滤器回拉，2008 条 work 全部补齐（0–79061，均值 622，`W4385245566`=Transformer 论文=79061 校验正确）。

**⑤ P1-2 引用时序与 P1-3 对标已落地（等全量数据生效）。** `_run_citation_metrics` 已接入 evaluate（单月数据下正确跳过回归、S 曲线 5000 项全标 emerging）；`benchmark_comparison.md` 给出 ICEWS/AIPatent/Science4Cast 口径对齐表与诚实声明。

**一句话结论**：代码与「免网络」的数据路线全部落地并端到端验证通过；**唯一未解的是 P0-1 全量引用时态**，卡在 PatentsView S3 403（需换网络或 BigQuery 导出），这是让定向边「既有方向又有高重复」、从而让 CyGNet 在时态协议下 > RotatE 的最后一块拼图。
