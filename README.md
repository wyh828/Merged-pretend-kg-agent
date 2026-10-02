# tech-trend-kg-agents

多源数据驱动的技术趋势预测系统 —— 通过论文/专利/新闻/GitHub 多源数据构建动态知识图谱，多智能体协同预测技术趋势。

> 当前本机版本基于 Merged-pretend-kg-agent 最新获取提交，包含十阶段流程。完整目标见 [PROJECT_PLAN.md](PROJECT_PLAN.md)；本机检查范围见 [function_review_00.md](Attempt/docs/function_review_00.md)。

## 本机环境与运行（Windows PowerShell）

项目根目录：`F:\Predictive agents`。所有相对存储路径按项目根目录解析。

```powershell
Set-Location 'F:\Predictive agents'
# 本次已建立 .venv；独立重建时使用本机可用的 Python：
& 'D:\ide\Anaconda\python.exe' -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
# .env 已创建，仅含路径和关闭的调度/推送开关；按 .env.example 填入服务配置。
& '.\.venv\Scripts\python.exe' main.py --list
& '.\.venv\Scripts\python.exe' main.py --stage visualize
& '.\.venv\Scripts\python.exe' -m pytest tests -q --basetemp=output/test_tmp_00 -p no:cacheprovider
```

本次验证环境为 Python 3.13.9，`.venv` 使用 `--system-site-packages` 复用本机 Anaconda 的已装包；
环境快照见 `Attempt/docs/local_environment_00.txt`。独立重建命令不复用系统包，需重新安装全部依赖。
Neo4j（`bolt://localhost:7687`）需要单独配置，数据库密码和 API key 写在根目录 `.env`。
默认不启动定时任务或对外推送。完整采集/训练需相应数据与外部服务。

看板：`output/dashboard.html`；分析文档：`output/report.md` / `eval_report.md` / `weekly_report.md`。
以下原仓库的阶段数字为历史记录，不能视为本机已复现的实验结果。

## 本机修订 00（2026-10-03）

当前分支 `codex/merged-local-00`，上游提交 `1b87827418a5603b2df709a234d769171d655c94`。
旧版本完整保存于 `.local_backups/pre_merged_import_00/`，旧提交保留于 `codex/checkpoint-before-merged-00`。
原远端 `origin` 保留，新增 `merged-upstream` 指向新仓库；本次仅本地操作，未推送。

代码阅读与核验规则已加入 AGENTS.md：先读接口、调用关系、输入输出和目标计划；复现单个问题，修订后运行专项检查，通过再进入下一项。函数清单共 448 项、模块导入 81 项；清单不代表所有函数的真实业务行为已验证。

当前流程：collect → extract → align → build_graph → predict → evaluate → collaborate → report → notify → visualize。

| 阶段 | 阻塞与问题 | 本机成果与验证 | 后续优化方法 |
|---|---|---|---|
| L0 获取与保护 | 原工程含未提交改动和数据 | 新分支基于上游 HEAD；完整旧文件、Git bundle、patch 与元数据备份 | 旧数据迁入前校验 schema，不直接覆盖 |
| L1 路径与环境 | 路径依赖 CWD；旧解释器失效；缺主干依赖；PyKEEN 默认写用户目录 | 根目录定位 `.env`/数据/输出/日志，工程内模型缓存；依赖安装、pip check 和路径专项测试通过 | 使用环境快照建立完全隔离环境 |
| L2 阶段编排 | 报错仍退出 0；report 早于 evaluate；每日漏 collaborate；拒绝审校仍推送 | 失败返回 1；十阶段顺序统一；拒绝后跳过报告/推送；专项测试通过 | 外部服务联调后检查真实 manifest |
| L3 函数接口 | 采集器协议错误缩进；USPTO 请求参数不匹配；LLM 异常 JSON 崩溃；源失败仍报 ok | 修复并分别测试；同日 raw 快照使用 `_00/_01` 独立保留；Crossref DOI 不再截断碰撞，来源与对齐正确 | 实际 API/LLM 验证；检查作者实体与数据覆盖 |
| L4 数值与时序存储 | NDCG 指数溢出；专利空样本崩溃；列排序前填充导致错误累积值 | 同尺度消除避免溢出，保留 NDCG 公式；先排序再填充；专项测试通过 | 完整日历补齐及评估口径需复核 |
| L5 报告与看板 | 已有看板，文档未整合；缺对照却判断输赢；末折缺失图表崩溃 | 复用 HTML/SVG，看板整合报告、回测报告、LLM 报告、周报、三份计划；增加榜单/协同表；缺数据显示未验证；专项测试通过 | 用真实产物核验图表、报告结论和数据时效 |
| L6 全流程与研究评估 | 尚无本机 Neo4j/API 配置或新数据；疑似时间泄漏与指标口径不一致 | 81 模块导入、RotatE/CyGNet 各 1 轮 CPU 合成样本检查通过；未宣称真实预测成功 | 等待用户确定数据/服务复用方式与评估修订许可，再逐项修订并生成独立实验版本 |

专项测试、模块检查、命令与风险说明见 [local_import_00.md](Attempt/docs/local_import_00.md)、[function_review_00.md](Attempt/docs/function_review_00.md)，环境见 [local_environment_00.txt](Attempt/docs/local_environment_00.txt)。

本机验证结果：54 项测试通过；compileall、pip check、git diff --check 通过；81 模块无导入错误；两个模型的合成样本 CPU 检查通过。实际运行 `main.py --stage evaluate` 在无 triples 数据时退出码为 1；`--stage visualize` 可生成空状态看板和周报。CPU 检查出现 PyTorch/PyKEEN 的无加速器、保守 batch_size 提示，不影响小样本检查；不据此保证大数据训练的资源需求。

测试环境阻塞记录：普通运行测试成功；一次提权复查使用默认系统临时目录时发生 ACL 冲突（39 项通过、15 项 fixture 建立失败）。改用上述工程内 `--basetemp` 并关闭 pytest 缓存后 54 项全部通过。重复运行会清理该临时测试目录，因此它只用于合成测试，不能放真实数据或实验产物。

**当前限制**：真实数据全量流程尚未完成；外部 API、Neo4j、LLM、云备份、通知与定时未联调。合成样本指标仅用于执行检查，不能用于研究结论。评估方法问题和未检验的函数逐项列于审查文档。

## 上游历史架构与实验记录（以下内容未经本机复现）

五阶段数据流（P1）：

```
collect     OpenAlex /works → data/interim/works.jsonl（cursor 增量、按 id 去重）
extract     结构化三元组抽取（非 LLM）→ data/interim/triples.jsonl + nodes.jsonl
build_graph triples + nodes → Neo4j（MERGE 幂等 upsert）
predict     RotatE 链接预测（filtered MRR/Hits@K）+ Kleinberg 突发 → output/baseline_metrics.json
report      baseline_metrics.json → output/report.md
```

## 目录结构

```
main.py / cron.py        入口（CLI / 定时）
techtrend/               主包
  config.py              pydantic-settings 配置（读 .env）
  io.py                  JSONL 读写小工具
  logging_config.py      统一日志（控制台 + logs/pipeline.log）
  pipeline.py            阶段编排
  sources/openalex.py    OpenAlex 客户端（过滤/分页/限速/重试/增量游标）
  extraction/structured.py  结构化三元组抽取 + 节点注册表
  graph/neo4j_client.py  Neo4j 驱动封装（约束/幂等 MERGE）
  graph/loader.py        triples → Neo4j
  prediction/kleinberg.py  Kleinberg 突发检测（两状态自动机，自实现）
  prediction/rotatE.py   RotatE 链接预测（pykeen 包装 + 时态/随机切分）
  prediction/metrics.py  precision@k / recall@k
  stages/                五个阶段实现
data/ output/ logs/      运行时目录（gitignore 忽略）
```

## 阶段归属

| 阶段 | P1 状态 | 实现内容 |
|---|---|---|
| collect | ✅ | OpenAlex 单源采集（cursor 增量 + 去重） |
| extract | ✅ | 结构化三元组抽取（concept/author/institution/citation，非 LLM） |
| build_graph | ✅ | 写入 Neo4j（四元组 + MERGE 幂等） |
| predict | ✅ | RotatE 链接预测 + Kleinberg 突发两个基线 |
| report | ✅ | 最小摘要 report.md |

## 关键实现决策（相对 P1_PLAN 的调整，均有理由）

1. **RotatE 用随机切分而非时态切分**：P1 图谱以 Paper 为头实体，Paper 是「一次性」实体
   （只在自身发表时间出现），时态切分后 test 实体几乎全不在 train 中，transductive
   评估退化为空集。静态 KG 嵌入（RotatE）标准做法本就是随机切分（FB15k/WN18 范式）；
   时态切分保留给 P3 的 TKG 外推。`temporal_split` 仍保留在代码中。
2. **引用三元组限量**（`EXTRACT_MAX_REFS`，默认 10/篇）：引用论文无元数据且数量爆炸
   （1000 篇 work 原始 citations 超 11 万条），限量控图谱规模。
3. **Kleinberg 评估剔除筛选概念**（AI/CS）：它们出现在几乎所有 work，突发排名被无信息占据。
4. **OpenAlex 分页改用 `page` 偏移**：2026 起 OpenAlex 不再返回 `next_cursor`。

## 下一阶段（P2）

多源（arXiv/USPTO/GDELT/GitHub + RSSHub 中文新闻）+ 动态 KG + 实体对齐 + LLM 抽取
（DeepSeek API）。详见 [TECH_ROADMAP.md](TECH_ROADMAP.md)。

---

# 合并进度与阶段记录（pretend-agent × tech-trend-kg-agents）

> 把「她的信号引擎（相对份额 + 动量 + 排序评估 + 研报叙事）」注入「我的图引擎骨架
> （Neo4j + TKG + 严格验证）」，并补上双方都缺的「真正的多智能体协同」。逐阶段记录
> **阻塞问题 → 合并成果 → 后续优化方法**，数字均为本仓种子数据真实重跑结果（非硬编 source 旧数字）。

## 环境阻塞（`--list` 依赖缺口）—— 已解决

- **阻塞现象**：`main.py --list` 在 import 阶段退出，报 `No module named 'tenacity'`。
- **实况核实**：上游历史验证环境（Python 3.12；本机为 Python 3.13.9）**已装齐主干全部依赖**
  （tenacity 9.1.4 / pykeen 1.11.1 / neo4j 6.3.1 / feedparser 6.0.14 / RapidFuzz 3.14.6 /
  scikit-learn 1.9.1 / torch 2.12.1 / numpy / pandas / httpx 等），`import main` 已验证通过。
  提示中的「缺 tenacity/neo4j…」是**陈旧信息**——实为误用了系统 `py` 3.12.3 而非 conda 解释器所致。
- **最优解法**：`F:\Predictive agents\.venv\Scripts\python.exe -m pip install -r requirements.txt`
  （补齐 aiohttp / apscheduler / pytest 这 3 个，其余已满足）；之后一律用
  `F:\Predictive agents\.venv\Scripts\python.exe` 跑，不用裸 `python`/`py`。
- **证据**：补齐后 `main.py --list` 列出 10 个阶段（含新 `collaborate`）；`pytest tests/` 11 用例全绿。

## 阶段 0 —— 统一仓库 + 引入 `techtrend/signal` 子包（已完成并推送）

- **成果**：双项目并入单仓 `Merged-pretend-kg-agent`，信号侧代码归入 `techtrend/signal/`，`origin/main` 已推送。

## 阶段 1 —— 信号层注入（救目标① p@k=0）

- **成果**：新增 `techtrend/prediction/signal.py` —— Concept 级「相对注意力份额 + EMA/MACD 动量」打分器
  （`share_t = (count_t+1)/(Total_t+N)` 解头部霸榜；EMA(3)/EMA(6) 求 `relative_growth` 动量），
  入口与 Kleinberg 同构；`config.fusion_signal_source = "share"` 作消融开关；融合与排名回测均已接线。
- **阻塞（已修复）**：`_robust_normalize` 在真实数据（5498 concept，频次重尾：大量 0 / 少数巨值）
  上 IQR 极小 → z 爆炸 → `math.exp(-z)` 抛 `OverflowError`，导致 share/fusion 的 p@k 全为 `null`。
  修复：sigmoid 前将 z 截断到 `[-35, 35]`（|z|>35 时 sigmoid 已饱和到 0/1，忠实原数学、只补数值稳定性），
  并新增回归测试 `test_robust_normalize_no_overflow_on_extreme_skew`。
- **真实结果（诚实口径）**：predict 阶段融合单窗口口径下 `fusion_precision_at_k = 0.0`
  （与 Kleinberg 基线 `precision_at_k = 0.0` 持平）；walk-forward 排名回测下 share `p@k = 0.0333`
  vs Kleinberg `p@k = 0.1333`。**结论：Concept 级（5498 概念）份额动量信号并未改善 p@k**——
  正是 MERGE_PLAN 预留的「Concept 级份额噪声仍使 p@k≈0」情形。
- **后续优化方法**：按红线「不调到赢」，不硬调参数凑数，启用 MERGE_PLAN 预留的**降级方案**：
  「退回主题级榜单（5–6 主题粗粒度，信号信噪比更高）+ Concept 级 TKG 外推双层」；并对 Concept 级信号
  做降噪（最小活跃量阈值、平滑窗口自适应、按学科分桶消除跨域份额污染）后再评。

## 阶段 2 —— 评估体系对齐（补排序指标）

- **成果**：`metrics.py` 新增 `spearman_rho` / `ndcg_at_k` / `top1_lift`；`evaluate` 每折对
  share-momentum 排名 vs 未来增速真值补算 NDCG@3/5、Spearman ρ、Top-1 Lift；`eval_report.md`
  新增「排序类指标」分区。
- **真实数字（walk-forward 3 折）**：
  - share 排名：`p@k = 0.0333 ± 0.0471`，`NDCG@3 = 0.6423 ± 0.2875`，`NDCG@5 = 0.5225 ± 0.2214`，
    `Spearman ρ = 0.2151 ± 0.0038`，`Top-1 Lift = 1.3305 ± 1.4415`；
  - Kleinberg 消融：`p@k = 0.1333`；
  - 图上指标（分区不混比）：`tkg_mrr = 0.8966 ± 0.0741`，`rmse = 1.7244`，`leak_ok = true`。
- **口径**：0.8966（图上 TKG MRR）与 0.6423（榜单 NDCG@3）分属两套评估、永不同表比大小。
- **后续优化方法**：NDCG 高而 p@k 低 → 信号对「序」有信息但对「命中的稀疏真值」召回不足，
  可引入「概念热度→主题聚合」的软标签扩大正样本，或改用 learning-to-rank 拟合「是否进入下期榜单」。

## 阶段 3 —— 数据源补齐（CrossRef，第 7 源）

- **成果**：新增 `techtrend/sources/crossref.py`（DOI 锚点 + `mailto` polite pool + `cursor=*` 增量游标 +
  JATS 摘要去标签），与 OpenAlex 以 DOI 强锚点对齐去重；`collect` 已注册 `crossref` 源。
- **阻塞**：需联网拉取 CrossRef；本次真实重跑未启用该源，代码已编译通过。
- **后续优化方法**：网络可用时 `--stage collect --source crossref` 冒烟接入；增量游标持久化到
  `crossref_cursor` 字段做断点续采。

## 阶段 4 —— 报告层统一（DeepSeek 研报叙事）

- **成果**：`stages/report.py` 新增可选 LLM 研报解读（确定性四目标总览 + DeepSeek 榜单解读/回测可靠性/
  行动建议，写 `report_llm.md`）。
- **阻塞**：`.env`（含 `LLM_API_KEY`）未随数据拷贝（Sensitive-Source Provenance 拒绝），无 key，
  报告阶段如实跳过 LLM 并标注「未启用 LLM」，保持确定性回退（`report.md` 正常产出）。
- **后续优化方法**：提供 key 后走 DeepSeek（OpenAI 兼容接口）把 `fusion_ranking.csv` + `eval_metrics.json`
  落成研报叙事；接口已预留，无需改代码。

## 阶段 5 —— 多智能体协同（确定性，核心突破点）

- **成果**：新增 `techtrend/orchestration/collab.py`（信号 agent `concept_share_momentum` × 链接预测 agent
  `cygnet.future_link_scores` 两路独立打分 → `zscore_rank` 归一 → 交叉质证）与 `stages/collaborate.py`
  （evaluate 之后、notify 之前注册为第 8 阶段），产出 `collab_consensus.json` + `collab_conflicts.json`。
- **真实结果**：`signal = 5498`、`link = 799`，交叉质证后 `agree = 66`、`signal_only = 2683`、
  `tkg_only = 334`、`neither = 2560`、`conflicts = 3017`。两路对同一批候选技术给出独立结论 + 可审计共识/冲突。
- **后续优化方法**：冲突项（signal_only/tkg_only）接入现有 HITL 审校门（`review_enable_hitl`）人工复核；
  LLM 化协同（双 agent 用 DeepSeek 生成论证再裁决）作为后续，接口在 `collab.py` 已预留。

## 端到端验收汇总

| 验收项 | 结果 |
|---|---|
| `--list` 列出 10 阶段 | ✅（含 `collaborate`） |
| `pytest tests/` | ✅ 11 passed（信号数学/排名 + 协同质证 + 溢出回归） |
| `--stage predict` | ✅ `fusion_p@k = 0.0`（诚实：Concept 级信号未改善） |
| `--stage evaluate` | ✅ 排序指标全产出，`leak_ok = true` |
| `--stage collaborate` | ✅ agree=66 / conflicts=3017 |
| `--stage report` | ✅ `report.md` 产出（LLM 因无 key 跳过，已标注） |

## 数据诚信声明

- 本轮数字全部来自**拷贝种子数据（works.jsonl 14 MB / triples.jsonl 30 MB）真实重跑**，未硬编 source 旧数字。
- `patent_citations.jsonl`（1.08 GB，仅目标③引用回归/S 曲线）未拷贝，引用相关数字沿用 source 已有值。
- 每个依赖网络/依赖 key 的步骤均如实标注「未跑通」，不宣称可复现。

