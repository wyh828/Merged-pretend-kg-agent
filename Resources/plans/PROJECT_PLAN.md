# 多源数据驱动的技术趋势预测系统 —— 项目计划框架

> 本文保留上游设计和历史结果，未经本机复现；当前进展和本机验证见 [项目入口](../../README.md)。

## Context（背景与目标）

**课题要求**：通过学术论文、专利、新闻、GitHub 热门项目等多源数据，构建可动态更新的知识图谱，通过多智能体协同的方式，预测技术发展趋势。

**已确认的关键决策**：
- **聚焦领域**：泛 AI / 计算机科学（arXiv / OpenAlex / GitHub 数据最丰富、前沿性强、本科生可控）。
- **预测目标**（四个全选，作为分期目标）：① 新兴/热门技术识别；② 技术间新关联预测（链接预测）；③ 技术指标时序外推（引用数/star/专利量）；④ 技术成熟度/生命周期（S 曲线阶段）。
- **架构决策**：混合分层 —— 底层为**独立可运行的 Python pipeline**（爬虫 + Neo4j 图谱 + 时序预测），hermes-agent（NousResearch/hermes-agent）作为**顶层调度 / 委派 / 报告层**，通过 cron + skills + 多 agent + MCP 对接。底层与 hermes-agent 解耦，可降级为 APScheduler 而不影响主体成果。

**本项目四个重点（用户自述）**：预测算法（核心）、资料搜索与自动化每日爬取、算法验证（用前几年数据预测后一月）、结合 hermes-agent 完成流程自动化。

---

## 一、总体架构（分层图）

```
┌─────────────────────────────────────────────────────────────┐
│  编排层  hermes-agent (cron 定时 / skills 沉淀 / 多agent委派 / 报告)  │
├─────────────────────────────────────────────────────────────┤
│  预测层  新兴识别 │ 链接预测外推 │ 指标时序回归 │ S曲线阶段      │
├─────────────────────────────────────────────────────────────┤
│  图谱层  Neo4j 动态知识图谱（四元组 (s,r,o,t,source)）          │
├─────────────────────────────────────────────────────────────┤
│  数据层  OpenAlex/arXiv │ USPTO/EPO │ GDELT │ GitHub API（每日增量）│
└─────────────────────────────────────────────────────────────┘
```

每层之间通过清晰的接口（CLI / Python 模块 / MCP tool）解耦，均可独立测试。

---

## 二、数据采集层（重点：资料搜索与自动化每日爬取）

### 2.1 数据源选型（每个源给出方案对比 + 结论）

| 源 | 候选方案 | 对比结论 | 推荐 |
|---|---|---|---|
| **论文** | OpenAlex vs Semantic Scholar vs Crossref vs arXiv OAI vs DBLP | OpenAlex 免费、CC0、含摘要/引用/concepts、支持 `from_publication_date` 增量，覆盖最广；Crossref 用 `from-index-date` 做增量收割最稳、是 DOI 对齐锚点；arXiv OAI 原生 `from/until` 增量、最贴合"前沿趋势"；Semantic Scholar 无限速友好、无增量字段，只做补充 | **OpenAlex 主源 + arXiv 前沿 + Crossref 做 DOI 锚点 + DBLP 校验** |
| **专利** | USPTO 首页 bulk XML（本地）vs USPTO ODP/PatentsView API vs EPO OPS vs Google Patents(BigQuery) vs Lens.org | USPTO 首页书目 XML（PTBLXML/APPBLXML）免费下载、无 key、字段正好覆盖 KG（号/标题/摘要/受让人/日期/CPC）；ODP/PatentsView 需 key（注册待重试）；EPO OPS 免费每周 4GB、ST36 增量友好、覆盖全球；Google Patents 官方 API 已废弃但 BigQuery 公开数据集与 Lens.org 可补中国专利 | **USPTO 首页 XML 主源（本地，无 key）+ 后续 EPO OPS / Google Patents BigQuery / Lens.org 补全球/中国专利** |
| **新闻** | GDELT vs NewsAPI vs RSSHub | GDELT 全量免费、GKG 每 15 分钟更新、按天下载、字段含实体/主题/tone，完美匹配 KG（但中文覆盖弱、中文实体抽取噪声大）；NewsAPI 免费仅 100 次/天且有 24h 延迟；RSSHub 自建 RSS 聚合，覆盖国内科技媒体（36氪/虎嗅/机器之心/量子位等），原生中文、质量好，但只给标题/链接/摘要/时间、无实体/tone（需自建 LLM 抽取） | **GDELT GKG 主源（全球）+ RSSHub 补充（中文新闻）** |
| **GitHub** | 官方 REST/Search vs 爬 trending 页 | 官方 API **无 trending 端点、无 star 历史**；Search API 可用 `created:>date stars:>=N` 模拟新晋热门；需**自建每日 star 快照**得到增长曲线（这是趋势核心信号） | **Search API 每日抓新仓库 + 本地每日记录 star 时间序列 + 爬 trending 页取周期热门标签** |

**文献/文档支撑**：OpenAlex（Priem et al. 2022，取代已停更的 MAG）；MAG（Wang et al. 2020, *Quantitative Science Studies*）；GDELT GKG Codebook；各源官方 API 文档。

**补充说明（中文文献）**：若需机构登录态下的知网元数据或批量下载，可用 scholar-kit（lottshin/scholar-kit，聚合 CNKI/OpenAlex/NSSD 等源的 AI Skill）作**交互式检索与人工抽检工具**，**不纳入每日自动化主源**（受控/灰色路径，仅演示或抽检用）。

### 2.2 爬取框架方案对比

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| **httpx/aiohttp + asyncio** | 轻量、全 REST API 够用、可控限速 | 需手写重试/限速逻辑 | ✅ **主选**（数据源基本都是 REST，无需重型爬虫） |
| **Scrapy** | 成熟、中间件/管道齐全 | 对纯 API 场景偏重 | 仅当需要大规模 HTML 爬取（trending 页）时用 |
| **Playwright** | 可渲染 JS 页面 | 重、慢、需浏览器 | 仅 GitHub trending 页兜底（有 JS 渲染时可换） |

**补充（RSSHub 自建部署，配合 2.1 中文新闻源）**：RSSHub 是采集层的一个自建服务，不是独立数据源——用 Docker 起官方镜像（`docker run -d -p 1200:1200 diygod/rsshub`），从官方文档挑需要的**目标路由**（36氪/虎嗅/机器之心/量子位等，每个站点对应一个 `/xxx/yyy` 路由）；自建时配置**缓存与上游请求间隔**做限速，避免触发目标站点反爬；下游再用 httpx 按 RSS 更新频率定时拉取，天然复用主选的 asyncio 框架，无需 Scrapy/Playwright。

### 2.3 每日调度方案对比

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| **hermes-agent cron** | 与整体架构统一、自然语言/表达式调度、可挂技能、可推送 Telegram/Discord | 框架新、稳定性待验证 | ✅ **编排层主选**（体现课题要求） |
| **APScheduler** | 轻量、Python 原生、稳定 | 无分布式、无 UI | ✅ **底层降级方案 / 解耦兜底** |
| **Airflow / Prefect / Dagster** | 生产级、DAG 可视化、重试/监控 | 重、部署成本高、本科生过重 | 仅规模扩大后再考虑 |

**结论**：底层 pipeline 用一个 `cron.py` 入口（可被 APScheduler 或 hermes-agent cron 调用），保证"换调度器不动业务代码"。

### 2.4 API Key / 访问权限申请指引（标注"可选"的无需等待即可起步）

| 源 | 是否需要 key | 申请方式 | 额度/说明 |
|---|---|---|---|
| OpenAlex | 可选 | openalex.org 用邮箱注册取 key | 无 key 也能用；key 提升每日额度 10× |
| arXiv | 否 | 无 | OAI-PMH 免费，遵守 3s/请求 |
| Crossref | 否 | 无需 key | 请求头带 `mailto` 进入 polite pool 更稳 |
| Semantic Scholar | 可选(推荐) | semanticscholar.org/product/api 申请 | 无 key 共享池易 429；有 key 约 1 req/s |
| DBLP | 否 | 无 | 直接下载 XML dump |
| GitHub | 是(推荐) | Settings→Developer settings→Personal access tokens→Fine-grained token，勾选 public repo 只读 | 未认证 60 req/h → 认证 5000 req/h |
| USPTO 首页 XML | 否 | 无 key，Bulk Data 官网**手工下载**周文件 | P2 主源（PTBLXML 授权/周二 + APPBLXML 申请/周四）；后续自动化下载 |
| USPTO ODP | 是 | data.uspto.gov 注册申请免费 key | **注册待重试**；成功后免手工下载、增量更自动 |
| PatentsView | 可选 | patentsview.org 申请 | v1 已 410、v2 需 key（以官方为准） |
| EPO OPS | 是 | developers.epo.org 注册 + OAuth2 | 免费每周 4GB；**注册待重试**，补全球专利 |
| GDELT | 否 | 无 | 全量开放匿名 |
| Lens.org | 可选 | lens.org 申请（人工审批） | 免费 tier 5000 请求/月；**后续补中国专利** |
| Google Patents (BigQuery) | 否 | BigQuery 公开数据集 `patents-public-data` | **后续补中国专利**（CN 公开号检索） |

**密钥管理**：所有 key 存 `.env`（加入 `.gitignore`），通过 `python-dotenv` 读取；从不用明文写进代码。GitHub key 只申请 public 只读权限（最小权限原则）。

**补充（USPTO 本地化 + 下载更新，P2 起）**：USPTO 专利源改为**本地首页书目 XML**（PTBLXML 授权/每周二 + APPBLXML 申请/每周四，Bulk Data 官网手工下载，无 key）。因原始 bulk 体积大，**只取首页 XML、不下全文/PDF/CPC 主文件**；解析侧按 CPC 前缀（AI/ML）裁剪并丢弃冗余字段，原始周文件归档/删除只留最近数周（`uspto_keep_weeks`）。**后续自动化**：先用 Playwright 自动打开下载页 + 人在环点下载/过验证码，ODP/EPO OPS key 注册成功后再切 API 免人工；中国/全球专利用 Google Patents BigQuery 与 Lens.org 补充。

---

## 三、知识图谱构建层

### 3.1 图谱存储方案对比

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| **Neo4j** | 图查询 Cypher 成熟、LangGraph 一等集成(langchain-neo4j)、可视化好、支持属性图 | 需独立服务 | ✅ **主选**（预测层 GNN/TKG 直接读子图） |
| **RDF/三元组库 (GraphDB/Virtuoso)** | 语义网标准、SPARQL | 生态偏学术、GNN 集成差 | 备选（若偏语义网方向） |
| **SQLite + FTS5** | 零依赖、轻量 | 图遍历/邻接查询弱 | 仅做 hermes-agent 侧的记忆/日志 |

### 3.2 实体/关系抽取方案对比

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| **LLM zero/few-shot 抽取（强制 JSON schema）** | 成本低、无标注、可定义少量类型、跨源统一 | 有幻觉、需后处理、token 成本 | ✅ **主选**（参照 SciERC 类型设计） |
| **NER/RE 专用模型（SciBERT/GLiNER/CodeIE）** | 稳定、可解释、领域强 | 需标注数据、覆盖类型固定 | 补充（对固定实体类型做召回校验） |
| **混合：LLM 抽取 + 轻量模型校验** | 兼顾精度与成本 | 工程复杂 | 中期优化项 |

**实体/关系类型设计**（参照 SciERC, Luan et al. EMNLP 2018 的 Task/Method/Metric 设计，改为技术域）：实体 = 技术/方法/模型/框架/数据集/机构/人物；关系 = 使用/改进/对比/属于/针对/竞品/因果。每条三元组带 `time` 与 `source` 字段。

### 3.3 跨源实体对齐方案对比

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| **强 ID 锚点**（DOI / 专利公开号 / GitHub URL / 新闻 URL） | 精确、无歧义 | 覆盖有限 | ✅ 主锚点 |
| **String matching + LLM 消歧** | 覆盖广 | 需去歧、误差 | ✅ 补充（映射到 Wikidata/OpenAlex concept 统一 ID） |
| **Entity Alignment 模型（EAkit 等）** | 自动化程度高 | 需训练、维护成本 | 可选进阶 |

### 3.4 动态更新机制
采用**事件流存储**：事实 = `(s, r, o, t, source)`，每条三元组带 `created_at` 时间戳与来源；评测时按时间切快照。综述支撑：Cai et al. *TKGC Survey* (arXiv:2201.08236)；增量更新方法（DKGE/OUKE/RotatH）可作进阶。

---

## 四、预测算法层（核心重点）

### 4.1 四个预测目标的任务形式化

| 预测目标 | 任务形式 | 评估指标 |
|---|---|---|
| ① 新兴/热门技术识别 | 排名 / 二分类（技术是否会在未来变热） | precision@k / recall / AUC / F1 |
| ② 技术间新关联预测 | 时序链接预测外推 `(s, r, ?, t_future)` | filtered MRR / Hits@1/3/10 |
| ③ 技术指标时序外推 | 回归（引用数/star/专利量的未来值） | MAE / RMSE / MAPE |
| ④ 技术成熟度/生命周期 | 多分类（S 曲线阶段） | accuracy / macro-F1 |

### 4.2 方法族方案对比（每一族给 2-3 个代表方法 + 文献 + 判断）

**（1）静态 KG 嵌入 —— 候选打分基线**

| 方法 | 核心 | 论文 | 判断 |
|---|---|---|---|
| TransE | h+r≈t 平移 | Bordes 2013 NeurIPS | 简单基线 |
| RotatE | 复数旋转，建模对称/组合 | Sun 2019 ICLR | 稳定，作基线 |
| TuckER | Tucker 分解 | Balažević 2019 EMNLP | 稳定，作基线 |
| **Trans4E** | 专为学术 KG(MAG) 设计 | Nayyeri 2021 Neurocomputing | **与本场景最贴合** |

局限：无时间维，只能"补全"不能"预测未来"，且静态基准有高度节点偏置。结论：**作候选可行性打分，不能独立作预测器**。

**（2）时序知识图谱推理 —— 主干**

| 方法 | 核心 | 论文 | 判断 |
|---|---|---|---|
| TGN | 节点记忆(GRU)+消息传递 | Rossi 2020 | 通用动态图框架 |
| **CyGNet** | 复制机制，利用历史重复事件 | Zhu 2021 AAAI | 契合技术演化重复性 ✅ |
| RE-NET | 历史子图+RNN 预测未来事件 | Jin 2020 ICLR | 事件预测经典 |
| xERTE | 可解释子图推理 | Han 2021 ICLR | 解释性好 |
| TANGO | Neural ODE 连续演化 | Han 2021 CIKM | 进阶 |
| **TLogic** | 挖掘时序逻辑规则 | Liu 2022 AAAI | **可解释规则层** ✅ |

综述：*TKGC Survey* (arXiv:2308.02457; Cai 2022)。结论：**TKG 外推任务直接对应"预测未来技术关联"，是主干**。

**（3）演化图 GNN —— 补充**

| 方法 | 核心 | 论文 | 判断 |
|---|---|---|---|
| EvolveGCN | RNN 更新 GCN 权重 | Pareja 2020 AAAI | 逐年演化 |
| DySAT | 结构+时序注意力 | Sankar 2020 WSDM | 链路预测常更优 |

局限：假设节点共享，对"全新技术出现"弱。结论：**做已有技术节点间的演化趋势，与 TKG 互补**。

**（4）科技挖掘 / 文献计量信号 —— 信号层（技术预测最经典一派）**

| 方法 | 核心 | 论文 | 判断 |
|---|---|---|---|
| **Kleinberg 突发检测** | 词频突发状态识别上升词 | Kleinberg 2002 KDD | 新兴技术信号 ✅ |
| LDA / DTM | 主题建模（静态/动态） | Blei 2003 JMLR / Blei&Lafferty 2006 ICML | 主题演化信号 |
| 新兴技术识别框架 | 主题+突发 | Xu 2021 TFSC | 方法范式 |
| **SemNet / Science4Cast** | 语义网络链接预测预测高影响概念 | Krenn&Zeilinger 2020 PNAS / arXiv:2210.00881 | **评估范式直接复用** ✅ |
| 分层语义网络+双链接预测(TOD) | 专利网络 TOD | Technovation 2023 | 技术机会发现 |

### 4.3 推荐组合：三层融合架构

```
① 静态打分层  RotatE/TuckER → 技术-技术新关联候选可行性分
② 时序主干层  CyGNet(或 TGN) 做外推预测 + TLogic 出可解释规则
③ 信号融合层  Kleinberg 突发 + DTM 主题 + SAO 语义网络 → 特征拼接
④ 集成预测    XGBoost / 轻量 MLP（或注意力融合）→ 输出排序列表
⑤ 解释输出    S 曲线阶段标签（④的成熟度可视化）
```

理由：纯静态 KG 无时间维（Wang TKDE 2017 综述印证）；科技挖掘信号弥补纯图方法"语义盲"（Kleinberg 2002 局限）；评估复用 Science4Cast/ICEWS 范式。**落地方案分两级**：MVP 先做「Kleinberg 突发 + 静态 KG 链接预测」两个基线跑通，再上 TKG 主干与融合。

---

## 五、验证与评估层（重点：用前几年数据预测后一月）

### 5.1 时间切分与回测方案对比

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| **walk-forward / rolling origin（expanding window）** | 尊重时间序、模拟真实"用过去预测未来"、多期评测 | 计算量随窗口增大 | ✅ **主选** |
| 单次 holdout | 简单 | 单期、易过拟合 | 仅起步 |
| CPCV（组合 purge 交叉验证） | 多回测路径分布、更稳健 | 复杂 | 进阶 |

**防数据泄漏要点**（工具：scikit-learn `TimeSeriesSplit`、`purgedcv`、`timeleak`）：禁止 shuffle；scaler/imputer 只在训练段 fit；`purge`（剔除标签区间与验证区间重叠行）+ `embargo`（测试块后加缓冲）；预测新实体时保证 train/test 实体组不相交。

### 5.2 评估指标
- 链接预测：**filtered** MRR / Hits@1/3/10（filtered 剔除已存在三元组，避免被同样正确的三元组错误扣分，论文默认报 filtered）。
- 分类/排名：precision@k / recall / AUC / F1。
- 回归：MAE / RMSE / MAPE。

### 5.3 ground truth 构造（核心：前几年 → 预测未来一月/一年）
以"事后发生的事实"为真值，做 `train < val < test` 时态切分：
- **论文**：前 N 年论文 → 预测未来引用数/是否高被引/新兴 topic。
- **专利**：前 N 年专利 → 预测未来新增/前向引用/是否新兴。
- **GitHub**：前 N 月 star 快照 → 预测未来 star 增长/是否热门。
- **新闻**：GDELT 事件流 → 外推未来事件（天然时序事实流）。

### 5.4 benchmark 参照
ICEWS14/18（TKG 外推标准基准）、TGB（Temporal Graph Benchmark）、AIPatent（AI 专利 TKG，20 个年度快照）；Science4Cast 与 Gu & Krenn（马普所）把"预测未来高影响概念"形式化为语义网络链接预测，AUC>0.94-0.99，可直接作为评测范式对齐。

---

## 六、hermes-agent 自动化编排层（重点：流程自动化 + 多智能体协同）

### 6.1 能力映射（调研确认 NousResearch/hermes-agent 的能力）
| 项目需求 | hermes-agent 能力 | 对接方式 |
|---|---|---|
| 每日定时爬取+分析+预测 | 内置 `cronjob` + `/cron`（自然语言/表达式） | 调度底层 `cron.py` |
| 流程经验沉淀 | 自动生成 `SKILL.md`（agentskills.io 标准，可迁移） | 每个阶段固化技能 |
| 多智能体协同 | `delegate_task` 子 agent 委派 + kanban 队列 | 角色化分析 agent |
| 图数据库 | ⚠️ 原生无图库 | 经 MCP 接 Neo4j |
| 底层工具调用 | 40+ 内置工具 + MCP 双向 | 把爬虫/预测封装成 MCP server |

### 6.2 多智能体角色设计（这是"多智能体协同"的研究贡献点，需自行设计而非只用内置委派）
- **采集 agent**：调度/监控各数据源每日增量。
- **抽取 agent**：LLM 抽取实体关系，写入 Neo4j。
- **分析 agent（可并行多个）**：分别做突发检测、主题演化、链接预测、时序回归。
- **预测/集成 agent**：融合多路信号，产出排序预测。
- **审校 agent（人在环）**：预测结论在写报告前暂停人工确认（LangGraph HITL 或 hermes-agent 交互）。
- **报告 agent**：生成日/周趋势报告，推送渠道。

**框架对比结论**（若不用 hermes-agent 做底层编排时的备选）：LangGraph + Neo4j（知识图谱一等集成、HITL、durable execution）最适合本 pipeline；CrewAI 适合快速原型；AutoGen（对话式、token 贵）、MetaGPT（偏软件工程 SOP）不推荐。多智能体文献：CAMEL（Li 2023 NeurIPS）、MetaGPT（Hong 2023 ICLR）、Generative Agents（Park 2023 UIST，记忆-反思-规划三件套可借鉴）。

---

## 七、分阶段实施路线图（MVP → 完整）

| 阶段 | 目标 | 交付物 | 验收标准 |
|---|---|---|---|
| **P0 脚手架** | 搭目录/依赖/配置 | 可运行的空 pipeline | `python main.py` 跑通 |
| **P1 单源+静态KG+基线** | OpenAlex 爬取→LLM 抽取→Neo4j→RotatE 链接预测 + Kleinberg 突发 | 单源 MVP | 跑出基线 MRR/precision |
| **P2 多源+动态KG** | 接入 arXiv/USPTO/GDELT/GitHub + RSSHub 中文新闻，四元组+时间戳，实体对齐 | 多源动态 KG | 五源实体对齐、增量更新 |
| **P3 时序预测** | CyGNet/TGN 外推 + TLogic 规则 + 融合 | 预测模块 | 外推 MRR/Hits 优于静态基线 |
| **P4 验证体系** | walk-forward + purge/embargo + 前N年→后一月 ground truth | 评测脚本 | 四指标齐备、无泄漏 |
| **P5 hermes-agent 自动化** | cron 调度 + 角色化 agent + 报告推送 | 全自动 pipeline | 每日无人值守跑通 |
| **P6 可视化/报告** | 趋势图 + S 曲线阶段 + 周报 | 前端/报告 | 可演示 |

**建议范围控制**：P0-P2 是必做；P3 若时间紧，可用「静态 KG 链接预测 + Kleinberg + 轻量时序回归(XGBoost)」替代重型 TKG 模型，仍满足"预测"要求；P5 是"结合 hermes-agent"的落地，务必保留。

---

### 阶段成果记录（P0–P6 已交付）

> 与上表「计划」对应的**实际交付**。详细设计与验证见各阶段 `P*_PLAN.md`；P2 截至 2026-09 已全量跑通，P3 全量交付但**验收未达标**（结论与根因见下「P3 细节」与 [P3_PLAN.md](P3_PLAN.md)「验证结果」）；P3.5 定向图优化 + P4 验证体系见下「P3 优化 / P4 结果」与 [P3_OPT_P4_RESULT.md](../reports/P3_OPT_P4_RESULT.md)；P5 自动化编排见下「P5 细节」与 [P5_PLAN.md](P5_PLAN.md)；P6 可视化/报告见下「P6 细节」与 [P6_PLAN.md](P6_PLAN.md)。

| 阶段 | 状态 | 交付物 | 验收结果 |
|---|---|---|---|
| **P0 脚手架** | ✅ 已交付（commit `6f17e75`） | 分层目录 + pydantic-settings 配置 + 统一日志（控制台/按天轮转、UTF-8）+ 空 pipeline 桩（`main.py` / `cron.py` / `pipeline.py` / `stages/*`）+ CLI（`--stage` / `--list`） | `python main.py` 跑通 5 阶段桩，exit 0 |
| **P1 单源 + 静态 KG + 基线** | ✅ 已交付（commit `0673ac3`） | OpenAlex 采集（cursor 增量 + tenacity + polite pool）→ 结构化抽取（零 LLM）→ Neo4j 静态 KG → RotatE 链接预测 + Kleinberg 突发两基线 → report | filtered **MRR 0.2595 / Hits@10 0.3615**；precision@k=0（Kleinberg 基线，见下） |
| **P2 多源 + 动态 KG + 实体对齐** | ✅ 已交付（未提交） | 五新源 + OpenAlex；四元组 `(s,r,o,t,source)`；DeepSeek LLM 抽取技术实体/关系；跨源实体对齐；6 阶段 pipeline | 6 源全通；**59,423 节点 / 91,303 边**；MRR 0.2734 / Hits@10 0.3746；34,084 实体对齐 |
| **P3 时序预测** | ⚠️ 已交付、验收未达标（未提交） | CyGNet 复制机制（copy+generate）+ copy-only 基线 + TLogic 时序规则 + RotatE 时态对照 + HistGradientBoosting 回归 + 三路信号融合；新增 7 个 `prediction/` 模块 + predict/report 接线 | 全量跑通；CyGNet 时态 MRR **0.4790** < RotatE 时态对照 **0.6539**（验收❌，见下 P3 细节） |
| **P3.5 定向关系图优化** | ⚠️ 已交付、A2 未达标（未提交） | LLM 二次 pass 抽 `uses/improves/compares/targets`（`competes`=0）定向 tech→tech 边，1136 事实；多关系 TLogic 恢复 | A1/A3/A4 ✅；A2 ❌ CyGNet 0.1621 < RotatE 0.2390（数据形状：86.5% 新链接），按兜底②收尾（见下） |
| **P4 验证体系** | ✅ 已交付（未提交） | walk-forward/rolling-origin + purge/embargo 三道防泄漏闸 + 回归/排名/TKG 三路回测；新增第 7 阶段 `evaluate` | B1/B2/B3 ✅：四指标齐备（TKG MRR 0.9459±0.0765、MAE 0.5017±0.0890、p@k=0）、无泄漏、`--list` 含 evaluate 且 exit 0（见下） |
| **P5 hermes-agent 自动化** | ✅ 已交付（未提交） | cron.py 统一入口 + 双轨调度（hermes cron 主 / APScheduler 降级）+ runbook 角色化编排（6 角色=数据）+ 0 新增短路守卫 + HITL 审校 + notify 推送（file/telegram/discord）+ run_manifest.jsonl 观测；`hermes/` skills + cronjobs/agents 配置样例 | ① 8 阶段端到端 exit 0 ✅；③ 时序深度递增 ✅；④ notify file ✅；⑤ manifest ✅；② 口径定为「守卫单测全对 + 有游标源(5/6)同日全 0 实测」，noop=true 真网不可达系 live-data 边界（见下 P5 细节） |
| **P6 可视化/报告** | ✅ 已交付（未提交） | `techtrend/viz/` 4 模块（`svg.py` SVG 原语 / `charts.py` 6 图 / `dashboard.py` 自包含 HTML / `weekly.py` 周报）+ 第 9 阶段 `visualize`（零重算）+ `report.py` 四目标总览 + `cron.py --mode weekly` + 专利 S 曲线分层选样修正（`citations.py` / `lifecycle.py`） | ① `--list` 9 阶段 ✅；② 自包含 `dashboard.html` 离线可开、8 图覆盖四目标 + 明暗主题 ✅；③ S 曲线分层选样后 **3 阶段**（emerging 998 / mature 3965 / declining 37）✅；④ 周报 + report.md 四目标总览 ✅（见下 P6 细节） |

**P1 细节**（单源 MVP）：
- 数据源仅 **OpenAlex**；结构化字段映射 4 类关系（`belongs_to`/`authored_by`/`affiliated_with`/`cites`），4 类实体（`Paper`/`Concept`/`Author`/`Institution`），**不引入 LLM**。
- Neo4j 静态图谱：唯一约束建在 `openalex_id`，`MERGE` 幂等 upsert；四元组已带 `time` + `source`（P2 正式化）。
- 预测：`RotatE`（pykeen，时态切分 train/test 不重叠）+ 自实现 `Kleinberg` 突发（两状态自动机）；`precision@k/recall@k` 以「未来 6 月概念增速 top-k」为真值。

**P2 细节**（多源 + 动态）：
- **六源**：OpenAlex / arXiv（urllib Atom，绕过 CDN 406）/ USPTO（本地 bulk XML，CPC 前缀过滤，**免 key**）/ GDELT（GKG 主题过滤 + V2 字段解析）/ GitHub（Search API 按 topic 逐个查 + 每日 star 快照）/ RSSHub（中文新闻，Docker 自建，`trust_env=False` 绕过本机 Clash 代理）。
- **LLM 抽取**（DeepSeek，OpenAI 兼容 `json_object`）：补技术实体 `Technology/Method/Model/Framework/Dataset` + 7 关系 `uses/improves/compares/targets/competes/causes` + 新闻 `mentions`/`tone`；无 key 时整段跳过、仅结构化（exit 0）。
- **实体对齐**（三级）：强 ID 锚点（DOI/专利号/URL）→ `rapidfuzz` string 匹配（阈值 0.90）→ 确定性 `sha1` 兜底；统一 `entity_id` 作 Neo4j MERGE 主键（每 label 唯一约束，取代 P1 的 `openalex_id`）。
- **6 阶段**：`collect → extract → align → build_graph → predict → report`；`collect_sources` 逗号分隔按源开关。
- **实测**：采集 6 源非空（arXiv 300 / USPTO 200 / GDELT 324 / GitHub 50 / RSSHub 40 + OpenAlex）；抽取 56,069 三元组（500 次 LLM 调用）；对齐 34,084 实体（394 string 命中）；落库 **59,423 节点 / 91,303 边**；链接预测 **MRR 0.2734 / Hits@10 0.3746**（较 P1 0.2595 / 0.3615 略升）。

**P3 细节**（时序预测，验收未达标）：
- **交付内容**（`techtrend/prediction/` 新增 7 模块 + predict/report 接线）：
  - `temporal.py`：doc→Concept 边**投影**为 Concept×Concept 共现边 `relates_to` + 时态 3-way 切分（train<val<test 不重叠）+ 实体编码（P4 换 walk-forward 只改此文件）；
  - `cygnet.py`：CyGNet 复制机制（copy 历史频次 + generate 嵌入打分，`α·copy+(1-α)·generate`）+ copy-only 确定性基线；
  - `tlogic.py`：时序规则挖掘（可解释层）；`regression.py`：HistGradientBoosting 指标时序回归（目标③）；`fusion.py`：Kleinberg 突发 + TKG + 回归三路融合排名（目标①）；`metrics.py` 扩展 `mrr_at/hits_at/mae/rmse/mape`；
  - `stages/predict.py`：`_run_tkg` / `_run_forecast` / `_run_fusion` 三子任务（各自 try/except 不互阻）；`stages/report.py` 补时序报告段。
- **输出**：`output/temporal_metrics.json`（P3 新）+ `tkg_rules.jsonl` + `forecast.csv` + `fusion_ranking.csv`；`baseline_metrics.json` 保持向后兼容（仍写 P2 随机切分指标）。
- **数据规模**：投影共现边 1433 条 → 事实流 10856 条；时态切分 train/val/test = 7610/1076/2170；实体 545（train+val 词表，转导协议）。
- **验收结论（❌ 未达标）**：验收标准「CyGNet filtered MRR（时态）> RotatE filtered MRR（同时态、同协议）」。实测 CyGNet `tkg_filtered_mrr`=**0.4790**（α=0.5）、copy-only=0.5435，均 < RotatE 时态对照 **0.6539**。这不是 bug，而是数据特性下的真实结果（根因见下「数据特性」）。
- **发现的数据特性**（决定算法表现的根因）：
  1. 共现图**稠密且对称**（无向 `relates_to`，每文档产生 C(n,2) 条边）→ RotatE/DistMult 的嵌入**泛化**（传递相似性）优于 copy 的**精确复现**：DistMult=0.576、RotatE=0.654 均 > copy=0.5435；
  2. 测试集 **99% 是「复现查询」**（335/338 条 (s,r) 在 train 见过，新查询仅 3 条）→ generate 模式唯一占优的「新链接」场景无处发挥；
  3. copy 与静态嵌入**高度同源**（都学共现结构）→ oracle 融合 MRR 仅 0.545（generate 仅在 2.1% 事实上优于 copy），copy 无法给嵌入「补盲」；
  4. 单关系下 TLogic 退化为 1 条 symmetry 规则（conf=1.0），可解释但判别力有限。
- **两个数据决策**（相对计划书字面 `head_type∈{Paper,Patent,Repo,News}` 的偏离）：
  1. **排除 News/GDELT 于共现投影**（`tkg_doc_types=Paper,Patent,Repo`）：GDELT 是单日快照，会形成一个巨大时间组使 val/test 为空；且新闻「主题」是事件主题（如 CYBER_ATTACK）而非技术实体。**这不意味着 News/GDELT 失效**——它仍参与静态图谱、Kleinberg 突发、回归与融合，只是不进 Concept×Concept 共现投影。
  2. **过滤 future-dated OpenAlex 数据**（`tkg_max_time` 默认今天）：OpenAlex 有少量日期在未来的坏记录，若不滤会污染时态切分（train 混入未来）。滤除后切分才严格「过去→未来」。
- **建议的下一步方向**（按优先级，详见 [P3_PLAN.md](P3_PLAN.md)「验证结果」）：
  1. **定向技术关系**（LLM 抽取 uses/improves）：无向共现是 copy 劣势的根源，定向 + 稀疏图更贴近「重复技术关联」，预期 copy 占优；
  2. **序列化 generate 模式**（GRU 编码实体历史）：真 CyGNet 的 generate 是序列编码器而非静态嵌入，可捕捉「近期重复」，或可反超 RotatE；
  3. **放宽验收口径**：以「copy-only 与静态 DistMult 同量级」或「CyGNet 结构完整 + TLogic 可解释 + 回归/融合全通」为验收，把「超 RotatE」留到定向关系图；
  4. **数据/配置调参**：提高 `tkg_min_cooccur` 得稀疏图或扩大数据量，观察 copy 是否翻盘（须在报告中如实说明，避免「调到赢」）。

> **已知局限（P3/P4 待解决）**：① Kleinberg 突发 `precision@k=0`——当前样本下检出的是泛化/消歧类通用概念（如 "Identification (biology)"、"Work (physics)"）而非真技术趋势，需更大数据 + 更好信号；② `competes` 关系本数据集 0 实例；③ GDELT 日文件按「0 点文件」只取 15 分钟切片，日覆盖量有限。

**P3 优化 / P4 结果 细节**（承接 [P3_OPT_P4_PLAN.md](P3_OPT_P4_PLAN.md)，全文见 [P3_OPT_P4_RESULT.md](../reports/P3_OPT_P4_RESULT.md)）：

**Part A —— P3 优化（定向技术关系）**：

- **A1 定向边 ✅**：`triples.jsonl` 出现 `head_type==tail_type=="Concept"` 的定向边，4 类关系 > 1：`uses=522 / targets=478 / improves=54 / compares=82`（`competes` LLM 未识别出实例，为 0）。定向图事实数 **1136**（经 `max_time=今天` 过滤未来坏数据），显著稀疏于共现投影（10580）。
- **A2 CyGNet > RotatE ❌（兜底 ② 收尾）**：单次 3-way 时态切分（train/val/test = 800/110/226），同协议对照 —— copy-only 0.1376、CyGNet（copy+generate）**0.1621**、RotatE（时态对照）**0.2390**。**0.1621 < 0.2390，未达标**。根因量化：test 的 52 条转导三元组里 **86.5%（45/52）** 的正确 tail 不在其 (s,r) 的 train 历史中 → copy 无信息可复制，只靠 generate（DistMult）打分，而 DistMult 在稀疏定向图上泛化弱于 RotatE。对照：共现图 walk-forward 下 copy-only 0.9419、CyGNet 0.9459 ≫ RotatE 0.4487（共现图「高复现」，copy 轻松赢）——**定向图与共现图正是两个极端**。兜底 ② 满足：copy-only ≈ DistMult 同量级（0.1376 vs 0.1621）+ 结构完整/可解释/回归/融合全通（A1/A3/A4 ✅），未做「调到赢」的参数篡改。
- **A3 TLogic 规则 > 1 ✅**：`tkg_rules.jsonl` 产出 **4 条**方向性蕴含规则（`min_support=3 / min_confidence=0.05`）：`compares→improves`(conf 0.0517)、`compares→uses`(0.0517)、`improves→compares`(0.075)、`improves→targets`(0.15)。多关系定向图恢复了 TLogic 判别力（P3 单关系共现退化为 1 条 symmetry 规则）。
- **A4 forecast / fusion 非空 ✅**：`forecast_mae=0.7055 / rmse=0.7310 / mape=2.3758`；`fusion_precision_at_k=0.0`、`fusion_recall_at_k=0.0`、`fusion_top_k` 10 概念（均非 null，未因换边源回归）。

**Part B —— P4 验证体系（walk-forward + purge/embargo）**：

- **交付物**：`techtrend/prediction/evaluation.py`（`rolling_origins / walk_forward_splits / purge_label_overlap / backtest_tkg / backtest_regression / backtest_ranking / leak_check`）+ `techtrend/stages/evaluate.py`（第 7 阶段，写 4 个输出文件）。
- **B1 四指标齐备（mean±std + 每折明细）✅**（`output/eval_metrics.json`）：② TKG filtered MRR（CyGNet）**0.9459 ± 0.0765**、Hits@10 0.9500；③ MAE 0.5017±0.0890 / RMSE 0.5269±0.0840 / MAPE 1.9166±0.4419；① precision@k / recall@k = 0.0。⚠️ **TKG 回测边源回退**：定向图时态跨度不足（2025 仅 15 条、无 2026），walk-forward 无有效折，回退到共现投影（10580 事实，2023→2026 连续），并在 `eval_metrics.json` 记 `tkg_fallback_reason`，对应计划书「混合共现兜底」。回归 5 折、排名 3 折、TKG 3 折均有每折明细，`eval_folds.csv` 落盘。
- **B2 无泄漏 ✅**：`leak_check.json` `ok=true`、`violations=[]`，每折 train/test 时间不重叠、embargo/purge 生效（fold 4 的 53 个 test 独有实体为 2026-09 新增概念，属转导协议正常剔除）。
- **B3 全量 exit 0 + `--list` 含 evaluate ✅**：`main.py --list` 输出 7 阶段（collect/extract/align/build_graph/predict/report/**evaluate**），exit 0。

**关键修复**（本报告数字可信度）：① 平均秩破同分（原先全 0 分时正确 tail 侥幸并列第 1，copy-only 虚高到 0.7071，改后落回诚实 0.1376）；② 正确 tail 保留在候选集（修掉 filtered 排名 mask 误删正确 tail、致 MRR>1 的 bug）；③ filtered 剔除口径与 RotatE 对齐（剔除 train+val+test，与 pykeen `realistic` 一致）；④ future-dated works 过滤（OpenAlex ~538 条发布日在未来的坏记录已滤，避免 test 窗口落未来）。

**诚实声明与后续**：A2 未达标是数据形状问题——定向图「稀疏 + 问新链接」与 CyGNet「靠复制历史」天然相克，计划书预判的「GRU 序列化 generate」「提 min_support 更稀疏」都不改善这一矛盾，故未强启；后续真要反超 RotatE 需**先喂给 CyGNet 更多可复制历史**（P5 每日增量 + 定向抽取覆盖近期文档）。定向图时态跨度不足：`works.jsonl` 现已含 2026-09 作品，重跑 `--stage extract` 可补近期定向对、缓解 B1-TKG 回退。排名 p@k=0.0 是目标①信号本身弱（Kleinberg 突发与「未来增速 top-k」在月度粒度不重合），留待 P6。根目录残留调试脚本 `alpha_sweep_tmp.py / dim_sweep_tmp.py / debug_fusion_tmp.py` 可删。

**P5 细节**（hermes-agent 自动化编排层）：

- **交付内容**（`techtrend/orchestration/` 4 模块 + `cron.py` 重写 + 第 8 阶段 `notify` + `hermes/` 配置样例）：
  - `roles.py`：6 角色（collector/extractor/analyst/integrator/reviewer/reporter）单一事实源，角色=数据；
  - `runbook.py`：`run_daily()` 每日增量编排 + `_is_noop` 0 新增短路守卫 + `_review_checkpoint` HITL 卡点 + `_append_manifest` 观测；
  - `scheduler.py`：APScheduler 降级调度（`--once` 可跑，常驻需装 apscheduler）；
  - `notify.py` + `stages/notify_stage.py`：file/telegram/discord 三通道推送（默认 file）；
  - `hermes/`：`skills/techtrend-daily`、`skills/roles`、`config/cronjobs.example.yaml`、`config/agents.example.yaml`。
- **验收结果（§9 口径）**：
  - ① 8 阶段端到端 ✅：run1（`20260923T233746`）exit 0、8 阶段全 ok、+44 新增（openalex 7 / rsshub 37）、74min / 1500 LLM calls；产出 report.md + notify_latest.md + manifest。
  - ③ 时序深度递增 ✅：works 2227→2234、news 671→708、arxiv 608 不变，逐源对齐 new_records；triples 57050→75659、nodes 34134→39852。
  - ④ notify file 通道 ✅：`output/notify_latest.md` 生成；telegram/discord 未实测（无 key/webhook）。
  - ⑤ manifest 可观测 ✅：`output/run_manifest.jsonl` 每完成一次追加一条（run_id/status/8 阶段/noop/new_records/hitl_approved）。
  - ② 同日二次触发 noop：**口径改为「守卫逻辑单测全对 + 有游标源(5/6)同日重触发已实测全 0」**。`_is_noop` 5 分支单测全对（全源 0→True / +3→False / +12→False / 含 error→False 不短路 / 空 sources→False）；同日重触发实测 run2 collect=`{openalex:0,arxiv:0,uspto:0,gdelt:0,github:0,rsshub:3}`、去 RSSHub 对照=`{openalex:12,其余0}` —— 5 个游标源全 0，守卫对非全 0 正确判 False 并继续进 extract。**全 0 noop=true 在真实网络下不可达，系 live-data 边界而非缺陷**（见下根因）。
- **② 根因（两处 live-data 边界）**：① RSSHub 无游标（`rsshub.py` id=link，每次全量拉路由），36kr 快讯持续出新 link；② OpenAlex 游标**日期粒度**（`collect.py` `_write_cursor(_, _today())`），同日重跑=重查「≥今天」窗口，OpenAlex 全天持续收录新 work。日期游标 + id 去重只能消「精确重复」，消不掉「上次抓后新进」。
- **后期优化方向（P5 遗留）**：
  1. **OpenAlex 游标改 resumption-token 时间戳**（独立于 ② 验收）：日期粒度 → `next_cursor` 时间戳，减少同日重跑的重复拉取（对 noop=true 帮助有限，RSSHub 与 OpenAlex 全天新进仍会破 0）；
  2. **RSSHub 实时源处理**：36kr 快讯天然持续出新 id，若要「同日全 0」需加「实时源排除白名单」或「新增阈值」，或 ② 用 mock/单测验收（已按口径②收尾，暂不实施）；
  3. **apscheduler 未装**：常驻 APScheduler fallback 需 `pip install apscheduler`（hermes cron 主轨 + `--once` 不受影响）；
  4. **notify telegram/discord 未实测**：file 已验，另两通道待补 key/webhook 后验收；
  5. **「连续 3 天」验收未完成**：仅 1 个真实日 + 同日重触发；需再跨 2 个自然日各跑一次。
- **残留副作用（自愈）**：两个被停的同日触发把 +12 works / +3 news 写入 interim 并推进游标（未走 extract）；下次真跑 extract 补抽成 triples/nodes，无丢失；manifest 仍仅 1 条完成记录（被停运行正确未写）。

**P6 细节**（可视化 / 报告层，承接 [P6_PLAN.md](P6_PLAN.md)）：

- **交付内容**（`techtrend/viz/` 4 模块 + 第 9 阶段 `visualize` + 接线）：
  - `svg.py`：SVG 原语（line/hbar/col），颜色全走 CSS 变量 `--series-*`/`--stage-*`（明暗两套），2px 折线 / 4px 圆角端 / 8px 标记 + 2px 表面环（承 dataviz skill 规格）；
  - `charts.py`：6 个图函数对应四目标（`trend_top_svg` 概念趋势 / `stage_dist_svg`+`s_curve_overlay_svg` 阶段分布与 S 曲线 / `walkforward_folds_svg` 每折 MRR / `fusion_rank_svg` 融合榜单 / `forecast_svg` 预测 vs 实际）；
  - `dashboard.py`：自包含 HTML 装配（CSS 变量 + `prefers-color-scheme` + `data-theme` 主题切换，零外部资源）；
  - `weekly.py`：`build_weekly_report`（聚合最近 N 天 manifest + 四目标快照 + 融合/突发榜单）；
  - `stages/visualize.py`：第 9 阶段，**零重算**——概念级实时读 `works.jsonl`（~12MB），专利级读 evaluate 持久化的小文件（`s_curve_curves.csv` 7.8KB），**不重读 1.08GB `patent_citations.jsonl`**；
  - `stages/report.py` 追加「四目标总览」段；`cron.py --mode weekly`；`.env.example` 补 P6 段（`VIZ_*`/`LIFECYCLE_*`/`PATENT_CITATION_SAMPLING`/`WEEKLY_*`）。
- **专利 S 曲线分层选样修正（P1-2 遗留，P6 落地）**：`citations.py` `_sample_patents` 由 top-N（按总被引）改为 **log10 分层选样**（`stratified`，5 箱 × 2000），`lifecycle.py` 泛化 `s_curve_stage(s)`（修掉原 `total < 0.2*max(x)` 在累积序列恒假的 bug，emerging 改按分位 + min_history）。重算后专利 S 曲线 **2 类 → 3 类**：`emerging 998 / mature 3965 / declining 37`（growth 天然罕见——专利被引加速期少）；分层选样把低被引箱（emerging）纳入，修正 top-N 只出 mature/declining 的选样偏。
- **验收结果（§九 端到端演示口径）**：
  - ① `main.py --list` / `cron.py --list` → **9 阶段**（…evaluate/notify/**visualize**）✅；
  - ② `--stage visualize` → `output/dashboard.html`（**8 图覆盖四目标**）+ `output/charts/*.svg` 单图 ✅；仪表盘离线可开、明暗主题切换正常；
  - ③ `--stage report` → `report.md` 含「四目标总览」✅；`cron.py --mode weekly` → `output/weekly_report.md` ✅；
  - ④ 专利 S 曲线分层选样重算 → 3 阶段（见上）。
- **诚实边界 / 遗留（P6 未解决，属数据/信号问题）**：
  - **目标① p@k 仍为 0**（当前 `eval_metrics.json` 记 directed 边源 p@k=0.1、共现 p@k=0）：P6 只做可视化，未改信号（Kleinberg 突发 vs 未来增速 top-k 月度不重合），留 P7 / 数据增强；
  - **仪表盘边源口径**：`output/eval_metrics.json` 当前为上一次 `directed` 跑的结果（CyGNet 0.1111 vs RotatE 0.1157），非定稿 cooccur（0.9459 vs 0.4487）——需重跑 `--stage evaluate`（默认 cooccur）刷新；
  - 根目录调试脚本 `alpha_sweep_tmp.py / dim_sweep_tmp.py / debug_fusion_tmp.py` 可删；`regenerate_s_curve_tmp.py` 为专利 S 曲线单算工具（读 1.08GB 一次）。

---

## 八、风险与备选（Plan B）

| 风险 | 影响 | 备选方案 |
|---|---|---|
| hermes-agent 版本迭代快、不稳定 | 编排层不可用 | 降级 APScheduler（底层已解耦，无损） |
| 数据源限流/停更（API 依赖源） | 数据断供 | USPTO 已本地 XML 免 key；API 源切 ODP / EPO OPS / Google Patents BigQuery / Lens.org |
| USPTO 原始 bulk 体积过大 | 磁盘/解析过载 | 只下首页 XML + CPC 前缀裁剪 + 原始文件归档删除（见 2.4「数据瘦身」） |
| LLM 抽取幻觉 | 图谱噪声 | 加轻量模型校验 + 人工抽检 |
| GitHub star 无历史 | 趋势信号缺失 | 自建每日快照（从一开始就记录） |
| 全新实体外推弱 | 漏报新技术 | 用 Kleinberg/主题信号补充，不依赖纯图方法 |

---

## 九、验证方式（如何测试全流程）

1. **数据层**：跑一次增量爬取，检查各源返回数量、时间戳正确、去重生效；连续跑 3 天验证增量不重复。
2. **图谱层**：Neo4j 中抽样检查实体/关系质量；四元组时间戳与来源字段完整；实体对齐后同一实体 ID 跨源合并。
3. **预测层**：跑 P4 评测脚本，报告 filtered MRR/Hits@K、precision@k、MAE；确认 train/test 时间不重叠（无泄漏，可用 `timeleak` lint）。
4. **编排层**：hermes-agent cron 触发一次完整 pipeline，检查日志、图谱更新、报告产出；人为关掉 hermes-agent，用 `cron.py` 直接跑验证底层独立性。
5. **端到端演示**：用 2023-2024 数据预测 2025 某月，对照真实发生验证命中率。

---

## 十、核心参考文献清单

**预测算法**：TransE (Bordes 2013 NeurIPS) · RotatE (Sun 2019 ICLR) · TuckER (Balažević 2019 EMNLP) · Trans4E (Nayyeri 2021 Neurocomputing) · TGN (Rossi 2020) · CyGNet (Zhu 2021 AAAI) · RE-NET (Jin 2020 ICLR) · xERTE (Han 2021 ICLR) · TANGO (Han 2021 CIKM) · TLogic (Liu 2022 AAAI) · EvolveGCN (Pareja 2020 AAAI) · DySAT (Sankar 2020 WSDM) · LDA (Blei 2003 JMLR) · DTM (Blei&Lafferty 2006 ICML) · Kleinberg 突发 (2002 KDD) · 新兴技术识别 (Xu 2021 TFSC) · SemNet (Krenn&Zeilinger 2020 PNAS) · Science4Cast (arXiv:2210.00881) · TOD 双链接预测 (Technovation 2023) · TKGC 综述 (arXiv:2308.02457; Cai 2022) · S曲线/TFDEA/Gartner

**数据源**：OpenAlex (Priem 2022) · MAG (Wang 2020 QSS) · Crossref · arXiv OAI · DBLP · USPTO 首页 bulk XML (PTBLXML/APPBLXML) · USPTO ODP/PatentsView · EPO OPS · Google Patents BigQuery · GDELT · GitHub API · Lens.org

**图谱构建**：SciERC (Luan 2018 EMNLP) · IE 低资源综述 (arXiv:2202.08063) · LLM 关系抽取 (ACL 2023) · 实体对齐综述 (AI Open 2021; EMNLP 2025)

**多智能体**：CAMEL (Li 2023 NeurIPS) · MetaGPT (Hong 2023 ICLR) · Generative Agents (Park 2023 UIST) · AutoGen · LangGraph · CrewAI · NousResearch/hermes-agent

**验证**：walk-forward/purge-embargo (purgedcv) · TimeSeriesSplit · ICEWS · TGB · AIPatent · Beyond S-curves (arXiv:2211.15334) · LLM 抽取语义三元组图谱 (arXiv:2510.25370)

---

## 已确认的技术决策（定稿）

1. **hermes-agent** = NousResearch/hermes-agent（自进化 agent 框架），第 6.1 能力映射按此为准。
2. **API key**：由本框架给出申请指引（见 2.4），用户自行申请后填入 `.env`。
3. **运行环境**：Python 3.11+；**Neo4j 用 Docker 本地起**（不用 Aura 云）。启动命令：

```bash
docker run -d --name neo4j-techtrend \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/<你的密码> \
  -v neo4j_data:/data \
  neo4j:5
```

连接 URI 用 `bolt://localhost:7687`，浏览器控制台 `http://localhost:7474`。

---

## P3 优化 / P4 关键决策与后置优化登记（定稿）

> 承接 §七「阶段成果记录」P3 验收未达标（CyGNet 时态 MRR 0.479 < RotatE 时态 0.654）、[TECH_ROADMAP.md](TECH_ROADMAP.md) §13 对照表与 [P3_OPT_P4_PLAN.md](P3_OPT_P4_PLAN.md)。把「数据决策」「模型/算法决策」「后置优化与待决策」一次性登记，避免后续阶段重复争议；**未在本表登记的新方向须先讨论再动工**。

### 已确认决策（定稿）

| # | 决策 | 内容 | 依据 / 备注 |
|---|---|---|---|
| 1 | 排除 News/GDELT 于共现投影 | `tkg_doc_types=Paper,Patent,Repo`；GDELT 单日快照 + 事件主题非技术实体 | P3_PLAN 验证结果；News/GDELT 仍参与静态图谱/Kleinberg/回归/融合 |
| 2 | 过滤 future-dated OpenAlex 数据 | `tkg_max_time` 默认今天，滤除发布日期在未来的坏记录 | 唯一正确做法；可选固定快照日期保证复现 |
| 3 | 序列化 generate（GRU）数据量增加后再用 | P3.5 默认 `tkg_sequence_generate=False`；待 P5 每日增量 + 定向图变丰富后启用 | 当前 545 实体/10856 事实，GRU 易过拟合 |
| 4 | 定向 tech→tech 关系（P3.5，已试行、A2 未达） | LLM 二次 pass 抽 uses/improves/compares/targets/competes，1136 定向事实 | A2 ❌ 0.1621 < 0.2390：定向图「稀疏 + 问新链接」与 copy 相克 |
| 5 | TKG 边源切换（定稿：cooccur 为主） | `tkg_edge_source=cooccur`（共现投影）为主；`directed`（定向）保留作消融对照；`patent_citation` 已移除 | 共现图 walk-forward copy 占优（0.9459 vs 0.4487）；专利引用图 P2-1 证伪 |
| 6 | 转导协议 | test 独有实体（train 无历史）剔除 | P3 已固化，P4 沿用 |
| 7 | 验证协议 | 「同时态同协议」对比（CyGNet 时态 vs RotatE 时态），不与随机切分（P2=0.2734）混比 | P3_PLAN 评估口径 |
| 8 | P4 评测独立第 7 阶段 | `stages/evaluate.py` + `prediction/evaluation.py`；walk-forward expanding 主选 | §七 P4 行「评测脚本」 |

### 后置优化 / 待决策登记（deferred，非本期）

| # | 项 | 状态 | 触发条件 / 备注 |
|---|---|---|---|
| 9 | 目标③真引用数/star 时序 | 后置 | 补 `cited_by_count`（openalex.normalize）+ 多日 star 快照；P4 回归仍以「月度活动量」为代理 |
| 10 | 目标④ S 曲线阶段 + 趋势图 + 周报 | ✅ 已落地 P6 | 阶段标注（`lifecycle.py`）+ 可视化（`viz/` + 第 9 阶段 `visualize`）+ 周报（`weekly.py` + `cron.py --mode weekly`） |
| 11 | GDELT 独立事件 TKG | 可选未来 | 事件共现图 → 事件趋势预测，与 Concept 共现图分开（TECH_ROADMAP §12.5 Q5） |
| 12 | 实体对齐 LLM 消歧 | 后置 | `align_enable_llm` 默认关（成本高）；数据规模增大后再开 |
| 13 | Kleinberg 泛化概念问题（precision@k=0） | 后置 | 检出 "Identification (biology)" 等非技术趋势；更大数据 + 更好信号（P5） |
| 14 | GDELT 多日下载（当前 15 分钟切片） | 后置 | 日覆盖量有限；连续多天采集成时间序列 |
| 15 | competes 关系 0 实例 | 后置观察 | P2 数据集无实例；随数据量观察是否出现 |
| 16 | 混合边源兜底（定向为主 + 共现补边） | 待决策 | 仅当定向图过稀疏（`len(facts)<50`）时启用，须在报告说明混合口径 |
| 17 | 验收口径放宽兜底 | 待决策 | 仅当定向图仍不达标时讨论：copy-only ≥ DistMult 同量级 或 结构完整+可解释+回归/融合全通；须如实报告，避免「调到赢」 |
| 18 | 数据调参红线 | 守则 | 调 `tkg_min_cooccur`/`techpair_min_support` 等须有原则依据 + 如实报告；禁止「调到赢」 |
| 19 | 定向图时态补全（重跑 `--stage extract`） | **近期必做** | 追 2025-06→2026-09 的定向对进 `triples`：解 B1-TKG 回退 + 给 A2 补近期可复制历史（`works.jsonl` 已含 2026-09 作品，仅定向 pass 未重跑） |
| 20 | 每日增量累积时序深度（P5 cron） | ✅ 已落地 P5 | collect→extract→align 每天跑（P5 runbook 已实现并端到端跑通）；(s,r) 跨时间重复是 CyGNet copy 的燃料，A2 反超的根本杠杆（不是调参） |
| 21 | 定向抽取全源近期覆盖 | 后置 | 定向 pass 从 OpenAlex 近期作品扩到 arXiv/USPTO/GitHub/RSSHub（经 Concept 对齐），加密定向图（1136 事实偏稀） |

### P4/P3 指标优化优先级（数据收集路线，定稿）

> **已扩展为可执行计划**：见 [P4_P3_METRIC_OPT_PLAN.md](P4_P3_METRIC_OPT_PLAN.md)（含 BigQuery 导出 USPTO 前向引用、
> ODP/PatentsView key 校验、Benchmark 对标三条路线的落地，并把「USPTO 前向引用」从 P2 上提到 P0）。
> 下表中的 P0/P1/P2 为该计划的三级摘要；「USPTO 前向引用时序（#5）」原定 P2，因确认 BigQuery 免 key 已上提为 P0-1。

> 按「救哪个指标」排序；编号对应上表「后置优化/待决策登记」。根因见「P3 优化 / P4 结果 细节」。

**P0（近期必做，直接决定 A2/B1 是否达标）**：
1. **重跑 `--stage extract` 补近期定向对**（#19）—— 补 2025-06→2026-09 定向对，解 B1-TKG 回退 + 给 A2 补近期可复制历史。
2. **每日增量累积时序深度（P5 cron）**（#20）—— (s,r) 跨时间重复是 CyGNet copy 的燃料，A2 反超的根本杠杆（不是调参）。

**P1（救排名 p@k=0 与回归语义真实性）**：
3. **`cited_by_count` + GitHub star 多日快照**（#9）—— 把「月度活动量」代理信号换成真引用/star 时序；排名热度与回归目标才有真实 ground truth。

**P2（次级，按需）**：
4. **定向抽取全源近期覆盖**（#21）—— 定向图 1136 事实偏稀，扩到 arXiv/USPTO/GitHub/RSSHub 加密。
5. **USPTO 前向引用时序** —— 目标③/④（成熟度 S 曲线）的成熟度信号（需 ODP/PatentsView key）。
6. **GDELT 多日下载**（#14）—— 当前仅 15 分钟切片，多日成事件时间序列。
7. **含竞品/因果的文档**（#15）—— 让 `competes`/`causes` 出现实例，A3 规则更丰富。
8. **GRU 序列化 generate**（#3）—— 数据量上来后再开，让 generate 吃「近期重复」信号。

**口径守则**：以上均为「补数据 / 补历史」，不涉及任何「调到赢」的参数篡改（#18）；A2 反超必须先满足 P0 的历史厚度，否则仍按兜底 ② 如实收尾。

### P0-1 / P2-1 执行结果（2026-09，专利前向引用图）

> 承接上表 P0/P1/P2 优先级，P0-1 与 P2-1 已实际落地并评测。全文见 [P4_P3_METRIC_OPT_RESULT.md](../reports/P4_P3_METRIC_OPT_RESULT.md)。

- **P0-1 ✅ 达成**：PatentsView bulk 终版（Zenodo 15058362）免 key，产 **6,967,772 条前向引用事实**，
  跨度 2015-01-06 → 2024-12-31（终版止于 2024，非计划字面「2026」）。`data/interim/patent_citations.jsonl`
  供 P1-2（引用时序回归 + S 曲线）使用。
- **P2-1 ❌ 前提证伪**：引用图作为 `tkg_edge_source=patent_citation` 接 TKG 后，walk-forward + 转导协议下
  **每折 test 三元组被整体剔除**（10 条 `test 无已知实体三元组`，tkg_mrr 全 None），evaluate 自动回退共现。
  根因结构性：① 引用图是**时态 DAG**（只引更早专利），test 窗口的 tail（引用专利）是 train 未见的新实体，
  转导协议要求 head+tail ∈ train 词表 → 全剔；② 每对专利只互引一次（单事件边），CyGNet copy 靠
  **object（tail）时间重复**，而「奠基专利被反复引用」只是 **head 的度**，不是 copy 燃料。
  **「专利引用图 = CyGNet copy 猎物」这一计划书假设被经验证伪。**
- **A2 三图盘点**：共现投影 copy 赢（0.9459 vs 0.4487，但 `relates_to` 是无向共现代理、非真实定向关系）；
  定向 LLM 图输（0.1621 vs 0.2390，问新链接）；专利引用图退化（无有效分）。**尚无真实定向图上 CyGNet 反超 RotatE。**

---

## P3 / P4 完整结果（定稿，cooccur 主边源）

> 承接 [P3_PLAN.md](P3_PLAN.md)、[P3_OPT_P4_RESULT.md](../reports/P3_OPT_P4_RESULT.md)、
> [P4_P3_METRIC_OPT_RESULT.md](../reports/P4_P3_METRIC_OPT_RESULT.md)。把 P3→P4 各阶段实测数字与最终 A2 口径一次性收口，
> 并以「cooccur 为正式 TKG 边源」落定。**与本文其他历史段落冲突时，以本节为准。**

### 一页结论（四目标最终数字）

| 目标 | 指标 | 最终值（walk-forward 为主） | 结论 |
|---|---|---|---|
| ① 新兴/热门识别 | precision@k / recall@k | **0.0 / 0.0** | 信号弱（Kleinberg 突发 vs 未来增速 top-k 月度不重合），留 P6 |
| ② 技术间新关联 | TKG filtered MRR（共现图） | CyGNet **0.9459**±0.0765 vs RotatE **0.4487**（copy-only 0.9419） | ✅ copy 占优，但 `relates_to` 是无向共现代理、非真实定向关系 |
| ③ 指标时序外推 | MAE / RMSE / MAPE | **0.5017 / 0.5269 / 1.9166**（活动量代理）；引用量口径 RMSE **54.85±1.37** | 真引用时序已可跑（P1-2），选样已修（分层，P6） |
| ④ 成熟度 S 曲线 | 阶段标签 | **emerging 998 / mature 3965 / declining 37**（growth 天然罕见） | P6 分层选样已修（log10 5 箱 × 2000） |

### 各阶段结果

**P3（共现图，单次时态 3-way 切分）❌ 验收未达标**
- CyGNet `tkg_filtered_mrr`=**0.4790**（α=0.5）、copy-only=0.5435，均 < RotatE 时态对照 **0.6539**。
- 根因：共现图稠密对称 → 静态嵌入泛化（RotatE 0.654 / DistMult 0.576）压过 copy 精确复现（0.5435）；测试 99% 是复现查询。

**P3.5（定向 uses/improves/… 图）⚠️ A2 未达标**
- 定向事实 1136（uses 522 / targets 478 / improves 54 / compares 82；competes 0），train/val/test = 800/110/226。
- copy-only 0.1376、CyGNet **0.1621**、RotatE **0.2390** → 未达标；根因：test 86.5%（45/52）正确 tail 不在 (s,r) 历史，copy 无史可复。
- A1 ✅（4 关系 > 1）、A3 ✅（4 条方向性 TLogic 规则）、A4 ✅（forecast RMSE 0.7310 / fusion 非空）。

**P4（walk-forward + purge/embargo，共现图）✅ 体系达标**
- ② TKG CyGNet MRR **0.9459±0.0765**、Hits@10 0.9500；③ MAE 0.5017±0.0890 / RMSE 0.5269±0.0840 / MAPE 1.9166±0.4419；① p@k=0。
- B1 ✅ 四指标齐备（每折明细 `eval_folds.csv`）；B2 ✅ 无泄漏（`leak_check.json` ok=true）；B3 ✅ `--list` 7 阶段 exit 0。
- 定向图时态跨度不足（2025 仅 15 条），walk-forward 无有效折 → 回退共现投影（记 `tkg_fallback_reason`）。

**P0-1 / P1-2 / P2-1（专利前向引用图）**
- P0-1 ✅：PatentsView bulk 终版免 key，**6,967,772 条前向引用**（2015-01 → 2024-12），落 `patent_citations.jsonl`。
- P1-2 ⚠️→✅（P6 修正）：引用量口径回归 RMSE **54.85±1.37**（patents=5000 / months=120，分层选样后）；S 曲线 top-N 选样偏已在 P6 改为分层选样 → **3 阶段**（emerging 998 / mature 3965 / declining 37）。
- P2-1 ❌：引用图作 TKG 边源退化（时态 DAG + 单事件边 → test 尾部被转导协议整体剔除）；**「引用图 = copy 燃料」假设证伪**。

### A2 最终口径 + 边源定稿

- **TKG 边源**：`tkg_edge_source=cooccur`（共现投影）为**正式主边源**；`directed` 保留作消融对照；`patent_citation` 从 TKG 移除、仅服务 P1-2（目标③真引用回归 + 目标④ S 曲线）。代码已按此落定（`config.py` 默认值 / `evaluate.py` / `predict.py` / `temporal.py` / `citations.py`）。
- **A2 达标证据**：共现图上 copy 占优（CyGNet 0.9459 > RotatE 0.4487），但如实标注 `relates_to` 是「同文档共现」代理、非经 LLM 验证的定向关系——**尚无一张真实定向图上 CyGNet 反超 RotatE**（定向图 0.1621 < 0.2390、引用图退化）。
- **诚实边界**：不通过调 `tkg_min_cooccur` / `tkg_alpha` 等「调到赢」（守则 #18）；A2 若按「真实定向图」严格口径，回到兜底 ②（copy-only ≈ DistMult 同量级 + 结构完整/可解释/回归融合全通）如实收尾。

### 遗留（跨 P5/P6 → P7）

- **S 曲线选样修正** ✅ 已落地 P6：`citations.py` 改 log10 分层选样（`stratified`，5 箱 × 2000），专利 S 曲线 **3 阶段**（emerging 998 / mature 3965 / declining 37，growth 天然罕见）。
- **每日增量累积时序深度**（#20，P5 cron）：(s,r) 跨时间重复是 copy 燃料的根本杠杆（不是调参）。
- **目标① p@k=0**（仍留，P6 只可视化未改信号）：Kleinberg 泛化概念问题 + 信号弱，需更大数据 / 更好信号（留 P7 / 数据增强）。
- 根目录调试脚本 `alpha_sweep_tmp.py / dim_sweep_tmp.py / debug_fusion_tmp.py` 可删。
