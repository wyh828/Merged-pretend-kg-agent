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
