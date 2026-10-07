> 本机适配说明：工程路径已改为 `F:/Predictive agents`；以下阶段设计与实验数字仍为上游历史记录。本机执行结果见 README 的「本机修订 00」。

> 本文保留上游设计和历史结果，未经本机复现；当前进展和本机验证见 [项目入口](../../README.md)。

# P1 单源 + 静态 KG + 基线 —— 完整构建计划

## Context（为什么做这件事）

P0 已交付可运行空 pipeline（目录/依赖/配置/日志/五阶段桩）。P1 按 PROJECT_PLAN 七「分阶段路线图」推进第一个有业务逻辑的阶段：

- **目标**：单源（OpenAlex）采集 → 静态知识图谱 → RotatE 链接预测 + Kleinberg 突发检测两个基线跑通。
- **验收标准**（计划书原文）：跑出基线 filtered MRR / precision@k。
- **范围**：只做 OpenAlex 一个源；**不引入 LLM 抽取**（推迟 P2 与多源/实体对齐一起做）。

### 已确认关键决策

| 项 | 结论 | 依据 |
|---|---|---|
| 三元组来源 | OpenAlex **结构化字段**（concept/author/institution/citation），零 LLM、零幻觉 | 需求澄清 |
| LLM 抽取 | 推迟 P2；provider 定档 **DeepSeek API**（OpenAI 兼容、json 输出） | 需求澄清 |
| 采集框架 | `httpx`(同步 Client) + `tenacity` 重试（P1 单源低频；asyncio 并发留 P2） | PROJECT_PLAN 2.2 |
| 图谱存储 | Neo4j 本地 Docker（`bolt://localhost:7687`），官方驱动 `neo4j` | PROJECT_PLAN 3.1 |
| RotatE | pykeen（一次跑出 filtered MRR/Hits@K） | PROJECT_PLAN 4.2(1) |
| Kleinberg 突发 | 自实现（纯 Python/numpy，Kleinberg 2002 两状态自动机） | PROJECT_PLAN 4.2(4) |
| 评估切分 | 时态切分（train 早 / test 晚，禁止 shuffle，防泄漏） | PROJECT_PLAN 5.1 |

## 目录结构（P1 新增/改动）

```
techtrend/
  config.py                 # 改：新增 OpenAlex / 预测参数
  sources/
    __init__.py             # 新
    openalex.py             # 新：OpenAlex 客户端（过滤/分页/限速/重试/增量游标）
  extraction/
    __init__.py             # 新
    structured.py           # 新：结构化三元组抽取（works → triples）
  graph/
    __init__.py             # 新
    neo4j_client.py         # 新：驱动封装（连接/约束/幂等 MERGE）
    loader.py               # 新：triples → Neo4j
  prediction/
    __init__.py             # 新
    kleinberg.py            # 新：Kleinberg 突发检测
    rotatE.py               # 新：pykeen 包装（TriplesFactory/时态切分/取指标）
    metrics.py              # 新：precision@k / recall@k
  stages/
    collect.py              # 改：实现 CollectStage → 调 sources.openalex
    extract.py              # 改：实现 ExtractStage → 调 extraction.structured（非 LLM）
    build_graph.py          # 改：实现 BuildGraphStage → 调 graph.loader
    predict.py              # 改：实现 PredictStage → 调 prediction.*
    report.py               # 改：P1 最小——把 baseline_metrics.json 落成 report.md
```

## 数据流与阶段接口契约

| 阶段 | 输入 | 输出（文件） | run() 返回 dict |
|---|---|---|---|
| collect | config 起止日期 | `data/raw/openalex/<date>/works_<cursor>.jsonl` + `data/interim/works.jsonl` | `{"stage","status":"ok","works":N,"from_date","to_date"}` |
| extract | `works.jsonl` | `data/interim/triples.jsonl`（每行 `{head,head_type,relation,tail,tail_type,time,source}`） | `{"stage","status":"ok","triples":N,"relations":{rel:count}}` |
| build_graph | `triples.jsonl` | Neo4j（节点/边） | `{"stage","status":"ok","nodes":N,"edges":M}` |
| predict | `triples.jsonl`(RotatE)；works 的 concept 月度频次(Kleinberg) | `output/baseline_metrics.json` + `output/burst_concepts.csv` | `{"stage","status":"ok","filtered_mrr","hits_at_1/3/10","precision_at_k","recall_at_k"}` |
| report | `baseline_metrics.json` | `output/report.md` | `{"stage","status":"ok","report_file":"output/report.md"}` |

阶段仍经 `pipeline.py` 顺序串行，各自可 `--stage` 单独跑（复用 P0 CLI）。`pipeline.py` 仅把日志里「P0 空脚手架」措辞改为「P1」。

## 配置扩展（config.py + .env.example）

`config.py` 的 `Settings` 新增：

```python
# OpenAlex 采集
openalex_from_date: str | None = None      # 增量起点，如 "2023-01-01"（首次无游标时的种子）
openalex_concept_ids: str = "C154945302,C41008148"   # 逗号分隔（AI/CS）
openalex_max_works: int = 1000
openalex_per_page: int = 200

# 预测（RotatE / Kleinberg）
rotate_embedding_dim: int = 128
rotate_epochs: int = 50
rotate_train_ratio: float = 0.8
burst_bin: str = "month"
burst_s: float = 2.0
burst_gamma: float = 1.0
burst_future_months: int = 6
```

`.env.example` 同步补 OpenAlex/预测两段（带注释）；`LLM_*` 保留并加注「P2 起用，已定档 DeepSeek API（base_url=https://api.deepseek.com/v1）」。

## 依赖变更（requirements.txt）

取消注释（P1 实际安装）：
- `httpx` `tenacity` `python-dateutil`（采集）
- `neo4j`（图谱）
- `numpy` `pandas` `scikit-learn` `torch` `pykeen`（预测）

`openai` **保持注释**（LLM 抽取推迟 P2）。

## 各模块详细设计

### 1. sources/openalex.py —— OpenAlex 客户端

> API key 存 `.env`（gitignored），勿写进文档/代码。

```python
class OpenAlexClient:
    def __init__(self, mailto: str | None, per_page: int = 200):
        self.client = httpx.Client(base_url="https://api.openalex.org", timeout=30,
                                   headers={"User-Agent": f"mailto:{mailto}"} if mailto else {},
                                   params={"per-page": per_page})
    def fetch_works(self, from_date: str | None, concept_ids: list[str],
                    max_works: int) -> list[dict]:   # cursor 分页 + tenacity 重试
    def _reconstruct_abstract(self, inv: dict | None) -> str | None  # inverted_index → 文本
    def normalize(self, work: dict) -> dict          # 字段裁剪 + 归一化
    def close(self)
```

- 端点 `GET /works`；`mailto` 进 polite pool（无 key 约 1 req/s、有 key 10 req/s）。
- 过滤 `filter=from_publication_date:<date>,concepts.id:<ID>`；循环取 `meta.next_cursor` 直到空或达 `max_works`。
  - 概念 ID 建议 AI=`C154945302`、CS=`C41008148`，**实现时用 `/concepts`（或 `/topics`）端点核对**——OpenAlex 已把 concepts 迁到 topics/keywords，若 `concepts.id` 过滤失效改用 `primary_topic.id`/`topics.id`。
- `select=id,doi,title,abstract_inverted_index,publication_date,concepts,authorships,referenced_works,cited_by_count`。
- 重试：tenacity 指数退避，仅 429/5xx 重试。
- 增量游标：上次 `from_publication_date` 存 `data/.openalex_cursor`，下次从该日期续；按 `work.id` 去重保证幂等。`config.openalex_from_date` 仅作首次无游标时的种子。
- 归一化落 `data/interim/works.jsonl`（每行一个 work），`abstract_inverted_index` 还原为纯文本（P2 LLM 用，P1 结构化抽取不依赖）。

归一化 works.jsonl 行结构：

```json
{"id": "https://openalex.org/W...", "title": "...", "publication_date": "2023-01-01",
 "abstract": "...",
 "concepts": [{"id": "C...", "name": "...", "score": 0.9}],
 "authorships": [{"author": {"id": "A...", "name": "..."},
                  "institutions": [{"id": "I...", "name": "..."}]}],
 "referenced_works": ["https://openalex.org/W..."]}
```

### 2. extraction/structured.py —— 结构化三元组抽取（非 LLM）

```python
RELATION_RULES = {                       # 关系 → 来源字段
    "belongs_to":      "concepts",       # 取 score 前 N 的 concept
    "authored_by":     "authorships[].author",
    "affiliated_with": "authorships[].institutions",
    "cites":           "referenced_works",
}
def extract_triples(works: Iterable[dict]) -> list[dict]   # 逐 work 映射为三元组
def dedupe_earliest(triples: list[dict]) -> list[dict]     # 同 (h,r,t) 只留最早 time
```

- 实体类型固定四类：`Paper` / `Concept` / `Author` / `Institution`（技术实体 P2 LLM 补）。
- 每条 `{head, head_type, relation, tail, tail_type, time=publication_date, source="openalex"}`。
- **无 LLM、无 abstract 依赖，纯字段映射**；LLM 抽取留 P2。
- 输出 `data/interim/triples.jsonl`。

### 3. graph/neo4j_client.py + loader.py —— 写入 Neo4j

```python
class Neo4jClient:
    def __init__(self, uri, user, password)
    def verify_connectivity(self)
    def create_schema(self)            # 唯一约束 + 索引
    def upsert_triples(self, triples) -> tuple[int, int]   # MERGE 批量 upsert → (nodes, edges)
    def close(self)

# loader.py
def load_triples(client, triples) -> dict   # {"nodes":N, "edges":M}
```

- Schema：
  - 节点标签 `Paper`(openalex_id, title, pub_date)、`Concept`(openalex_id, name)、`Author`(openalex_id, name)、`Institution`(openalex_id, name)。
  - 关系类型 `BELONGS_TO` / `AUTHORED_BY` / `AFFILIATED_WITH` / `CITES`，属性 `{time, source}`。
- 唯一约束（`Paper.openalex_id` 等四类）+ `Concept.name` 索引；`MERGE` 幂等 upsert（重跑不重复）。
- openalex_id 存 `https://openalex.org/...` 的末段（如 `W...`/`C...`/`A...`/`I...`）。

### 4. prediction/*.py —— 两个基线

**rotatE.py（链接预测）**
```python
def build_triples_factory(triples) -> TriplesFactory      # 实体/关系 ID 编码
def temporal_split(triples, train_ratio=0.8) -> (train, test)  # 按 time 排序切分，禁止 shuffle
def run_rotate(train, test, dim=128, epochs=50) -> dict   # pykeen.pipeline → filtered 指标
```
- `pykeen.pipeline.pipeline(model="RotatE", training=train, testing=test, ...)`；从 `result.metric_results` 取 **filtered** MRR / Hits@1/3/10。
- 时态切分：按 `time` 升序，train=早 80%、test=晚 20%，时间不重叠。

**kleinberg.py（突发检测）+ metrics.py（评估）**
```python
def build_concept_monthly_counts(works) -> pd.DataFrame      # concept × month 频次矩阵
def kleinberg_bursts(series, s=2.0, gamma=1.0) -> list[dict] # 两状态自动机 → 突发区间+权重
def detect_top_bursts(df, top_k) -> pd.DataFrame             # 按突发权重降序
# metrics.py
def precision_at_k(ranked, truth, k) -> float
def recall_at_k(ranked, truth, k) -> float
```
- Kleinberg 输入：OpenAlex concept 月度频次（collect 的 works 按 `publication_date` 分月统计 concepts 计数）。
- 评估 ground truth：以「未来窗口（`burst_future_months`，默认后 6 月）频次增速 top-k concept」为真值；与突发 top-k 求交集 → precision@k / recall@k。时间轴切分点取「最近 6 个月之前的全部历史」。
- 输出 `output/baseline_metrics.json`（含 filtered MRR/Hits@1/3/10、precision@k/recall@k、突发概念表）+ `output/burst_concepts.csv`。

### 5. 各 stage 实现

- 每个 stage 替换桩：`run()` 调对应模块、打关键日志、返回上表契约 dict；失败时返回 `{"stage","status":"error","error":msg}` 并让日志报错（pipeline 继续跑后续阶段，便于逐阶段定位）。
- `stages/__init__.py` 的 `get_default_stages` 不变（五阶段顺序不变）。

## 实施顺序（任务分解）

1. `config.py` + `.env.example` + `requirements.txt`（取消注释并安装依赖）。
2. `sources/openalex.py` → 实现 `CollectStage`（先跑通 `--stage collect`，核对 works 数量/日期/去重）。
3. `extraction/structured.py` → 实现 `ExtractStage`（核对四关系分布）。
4. 起 Neo4j Docker → `graph/neo4j_client.py` + `loader.py` → 实现 `BuildGraphStage`（浏览器查节点/边）。
5. `prediction/kleinberg.py` + `metrics.py` → `prediction/rotatE.py` → 实现 `PredictStage`。
6. `report.py` 最小摘要 + `pipeline.py` 日志措辞。
7. 端到端全量验证 + 写本 `P1_PLAN.md`。

## 验证方式（端到端）

```bash
# 1. 起 Neo4j（本地 Docker）
docker run -d --name neo4j-techtrend -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/<密码> -v neo4j_data:/data neo4j:5

# 2. 装依赖（沿用 P0 conda 环境 + 完整路径）
& 'F:\Predictive agents\.venv\Scripts\python.exe' -m pip install -r requirements.txt

# 3. 逐阶段跑 + 全量
& 'F:\Predictive agents\.venv\Scripts\python.exe' main.py --stage collect      # works.jsonl 数量/日期/去重
& 'F:\Predictive agents\.venv\Scripts\python.exe' main.py --stage extract      # triples.jsonl 四种关系分布
& 'F:\Predictive agents\.venv\Scripts\python.exe' main.py --stage build_graph  # http://localhost:7474 查节点/边
& 'F:\Predictive agents\.venv\Scripts\python.exe' main.py --stage predict      # baseline_metrics.json 含 filtered MRR/Hits@K/precision@k
& 'F:\Predictive agents\.venv\Scripts\python.exe' main.py                      # 全量跑通，exit 0
```

**验收标准**：`output/baseline_metrics.json` 内出现非空 filtered MRR、Hits@1/3/10、precision@k/recall@k。

## 风险与注意

- pykeen + torch 较重，CPU 版起步即可。
- OpenAlex 无 key 1 req/s、有 key 10 req/s；cursor 分页须正确跟随 `next_cursor`。
- concepts→topics 迁移：若 `concepts.id` 过滤失效，切 `primary_topic.id`/`topics.id`。
- Kleinberg 自实现需对拍：先用合成突发序列（前平后涨）验证能检出正确区间。
- 时态切分严格禁止 shuffle；P4 再补 purge/embargo，P1 先保证时间不重叠。
- `data/interim/` 目录需在 collect 阶段自动 `mkdir(parents=True, exist_ok=True)`（P0 只有 `data/.gitkeep`）。
