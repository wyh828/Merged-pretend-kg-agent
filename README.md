# tech-trend-kg-agents

多源数据驱动的技术趋势预测系统 —— 通过论文/专利/新闻/GitHub 多源数据构建动态知识图谱，多智能体协同预测技术趋势。

> 完整方案见 [PROJECT_PLAN.md](PROJECT_PLAN.md)；本阶段（P1）已实现「单源 + 静态 KG + 基线」，实施细节见 [P1_PLAN.md](P1_PLAN.md)。

## 环境搭建（conda + 完整路径，免 activate）

```bash
# 1. 建专用环境到 E 盘（Python 3.12）
conda create -p E:\conda_envs\techtrend python=3.12 -y

# 2. 装依赖（完整路径，不依赖 conda activate）
E:\conda_envs\techtrend\python.exe -m pip install -r requirements.txt

# 3. 配置（复制模板后填入 OpenAlex key / Neo4j 密码等）
copy .env.example .env
```

## Neo4j（P1 起用，本地 Docker）

```bash
docker run -d --name neo4j-techtrend -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/<你的密码> -v neo4j_data:/data neo4j:5
```

> Neo4j 5 不接受默认密码 `neo4j`，需自定义（与 `.env` 的 `NEO4J_PASSWORD` 一致）。
> 浏览器控制台 `http://localhost:7474`，bolt `bolt://localhost:7687`。

## 运行

```bash
E:\conda_envs\techtrend\python.exe main.py                    # 跑全部阶段
E:\conda_envs\techtrend\python.exe main.py --list             # 列出阶段
E:\conda_envs\techtrend\python.exe main.py --stage collect    # 只跑某阶段
E:\conda_envs\techtrend\python.exe cron.py                    # 定时入口（P5 接 hermes-agent）
```

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
- **实况核实**：conda 环境 `E:\conda_envs\techtrend`（Python 3.12）**已装齐主干全部依赖**
  （tenacity 9.1.4 / pykeen 1.11.1 / neo4j 6.3.1 / feedparser 6.0.14 / RapidFuzz 3.14.6 /
  scikit-learn 1.9.1 / torch 2.12.1 / numpy / pandas / httpx 等），`import main` 已验证通过。
  提示中的「缺 tenacity/neo4j…」是**陈旧信息**——实为误用了系统 `py` 3.12.3 而非 conda 解释器所致。
- **最优解法**：`E:\conda_envs\techtrend\python.exe -m pip install -r requirements.txt`
  （补齐 aiohttp / apscheduler / pytest 这 3 个，其余已满足）；之后一律用
  `E:\conda_envs\techtrend\python.exe` 跑，不用裸 `python`/`py`。
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

