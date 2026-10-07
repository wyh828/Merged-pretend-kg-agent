> 本机适配说明：工程路径已改为 `F:/Predictive agents`；以下阶段设计与实验数字仍为上游历史记录。本机执行结果见 README 的「本机修订 00」。

> 本文保留上游设计和历史结果，未经本机复现；当前进展和本机验证见 [项目入口](../../README.md)。

# P2 多源 + 动态 KG + 实体对齐 —— 完整构建计划

## Context（为什么做这件事）

P1 已交付「单源（OpenAlex）+ 静态 KG + 两个基线」：结构化抽取（零 LLM）→ Neo4j → RotatE + Kleinberg。P2 按 PROJECT_PLAN 七「分阶段路线图」推进第二个有业务逻辑的阶段：

- **目标**：接入 arXiv / USPTO / GDELT / GitHub / RSSHub 中文新闻五源；四元组 `(s,r,o,t,source)` + 时间戳落库；跨源实体对齐；引入 LLM 抽取补技术实体/关系。
- **验收标准**（计划书原文）：五源实体对齐、增量更新。
- **范围**：数据层扩到五源 + 图谱层扩到多源动态；**预测层不变**（仍 P1 的 RotatE/Kleinberg 基线，跑在更大的图上；重型 TKG 留 P3）。

### 已确认关键决策

| 项 | 结论 | 依据 |
|---|---|---|
| 数据源 | P1 OpenAlex 保留；P2 新增 arXiv / USPTO / GDELT / GitHub / RSSHub 中文新闻 | PROJECT_PLAN 2.1 |
| 各源采集方式 | arXiv/GDELT/GitHub/RSSHub 走 REST/OAI-PMH/文件下载，统一 `httpx` + `tenacity`；**USPTO 改本地 XML 解析（无 key）**；仅 GitHub trending 页需 HTML（Scrapy 兜底，P2 可跳过） | PROJECT_PLAN 2.2 / TECH_ROADMAP 2.1 |
| USPTO 数据形态 | **本地 bulk XML**（`data/raw/` 已存周书目 XML，无 key）：授权 `ipgb*.xml`（PTBLXML）+ 申请 `ipab*.xml`（APPBLXML）；CPC 主文件(32G)/PatentsView TSV/AIPD 种子集备选，P2 只用首页 XML | 本计划（key 已免，数据已本地化） |
| LLM 抽取 | **DeepSeek API**（OpenAI 兼容、`response_format=json_object`），抽取技术实体/关系 + 中文新闻实体/tone | P1_PLAN 已定档 |
| 实体/关系类型 | 实体 = 技术/方法/模型/框架/数据集/机构/人物；关系 = 使用/改进/对比/属于/针对/竞品/因果（`belongs_to` P1 已有） | PROJECT_PLAN 3.2 |
| 四元组 | P1 边已带 `time`+`source`；P2 使其正式化（多 source 值 + 补 `created_at` 摄取时间，供 P4 快照） | PROJECT_PLAN 3.4 |
| 实体对齐 | 强 ID 锚点（DOI/专利号/GitHub URL/新闻 URL）→ string 匹配 → LLM 消歧，映射到统一 `entity_id` | PROJECT_PLAN 3.3 |
| 对齐落点 | 新增独立 `align` 阶段（extract 与 build_graph 之间），可单独 `--stage align` | 本计划（阶段清晰、可独立测试） |
| 采集开关 | `collect_sources`（逗号分隔）配置驱动，各源可独立关闭/限量为 0 | 本计划（免改 CLI，沿用 P0/P1 的 `--stage` 用法） |

---

## 目录结构（P2 新增/改动）

```
techtrend/
  config.py                 # 改：新增五源采集 / LLM 抽取 / 对齐参数；LLM 默认值切 DeepSeek
  sources/
    __init__.py             # 改：导出全部客户端
    openalex.py             # 复用（不改）
    arxiv.py                # 新：arXiv OAI-PMH 客户端（Atom 解析 / from-until 增量）
    uspto.py                # 新：USPTO 客户端（本地 bulk XML 解析，无 key）
    gdelt.py                # 新：GDELT GKG 客户端（日文件下载 / unzip / CSV 解析）
    github.py               # 新：GitHub Search API 客户端（created/star 过滤）
    rsshub.py               # 新：RSSHub RSS 客户端（httpx 拉 RSS / feedparser 解析）
  extraction/
    __init__.py             # 改：导出结构化 + LLM 抽取
    structured.py           # 复用（改：entity_id 缺省=短 ID，供对齐）
    llm.py                  # 新：LLMExtractor（DeepSeek，JSON schema，few-shot）
    schema.py               # 新：实体/关系类型常量（技术实体 + 7 关系）
  graph/
    __init__.py             # 改：导出 alignment
    neo4j_client.py         # 改：schema 泛化（per-label 唯一约束 + 新节点/边标签）
    loader.py               # 改：按 entity_id MERGE（多源节点/边）
    alignment.py            # 新：跨源实体对齐（强 ID / string / LLM）
  stages/
    __init__.py             # 改：注册 align 阶段（6 阶段）
    collect.py              # 改：按 collect_sources 多源采集
    extract.py              # 改：结构化 + LLM 抽取合并
    align.py                # 新：AlignStage（调 graph.alignment）
    build_graph.py          # 改：读对齐后 triples/nodes
    predict.py              # 复用（不改；跑在更大图上）
    report.py               # 复用（改标题措辞 P1→P2）
```

---

## 数据流与阶段接口契约

六阶段顺序：`collect → extract → align → build_graph → predict → report`。

| 阶段 | 输入 | 输出（文件） | run() 返回 dict |
|---|---|---|---|
| collect | config 各源参数 + 各源增量游标 | `data/raw/<source>/<date>/...` + `data/interim/{works,arxiv,patents,news,github}.jsonl` | `{"stage","status":"ok","sources":{source:count},...}` |
| extract | 五个 interim 源文件 | `data/interim/triples.jsonl` + `nodes.jsonl`（多 source 合并） | `{"stage","status":"ok","triples":N,"relations":{rel:count},"llm_calls":M}` |
| align | `triples.jsonl` + `nodes.jsonl` | 回写 `triples.jsonl`/`nodes.jsonl` 加 `head_id`/`tail_id`/`entity_id`；`data/interim/alignment.jsonl` 审计 | `{"stage","status":"ok","entities":N,"merged":M,"aligned_by_anchor":A,"aligned_by_string":S}` |
| build_graph | 对齐后 `triples.jsonl` + `nodes.jsonl` | Neo4j（扩展 schema：多源节点/边） | `{"stage","status":"ok","nodes":N,"edges":M}` |
| predict | `triples.jsonl`(RotatE)；concept 月度频次(Kleinberg) | `output/baseline_metrics.json` + `output/burst_concepts.csv`（同 P1） | 同 P1 |
| report | `baseline_metrics.json` | `output/report.md` | 同 P1 |

- 仍经 `pipeline.py` 顺序串行，各阶段可 `--stage` 单独跑（复用 P0 CLI）。
- `pipeline.py` 仅把日志措辞「P1」改「P2」；`main.py` argparse description 同步。

### 四元组与统一实体 ID

- 三元组行（extract 输出）统一为：`{head, head_type, relation, tail, tail_type, time, source}`。
  - `source` 取值：`openalex` / `arxiv` / `uspto` / `gdelt` / `github` / `rsshub`。
  - `time` = 各源的发布日期/时间（ISO 字符串，跨源统一比较）。
  - 每条在 write 时补 `created_at`（摄取时间戳，P4 快照/防泄漏用）。
- 对齐后三元组增加 `head_id`/`tail_id`（canonical 实体 ID）；节点增加 `entity_id`。
- **统一 `entity_id`**：所有节点用单一 `entity_id` 作为 Neo4j MERGE 主键（P1 的 `openalex_id` 降为来源溯源属性，P1 节点 `entity_id` = 原 `openalex_id` 短 ID）。LLM 抽取的实体在 align 后获得 `entity_id`。

---

## 配置扩展（config.py + .env.example）

`Settings` 新增字段（LLM 三字段已存在，改默认值；数据源 key 字段已存在，P2 起用）：

```python
# 多源采集开关（P2）
collect_sources: str = "openalex,arxiv,uspto,gdelt,github,rsshub"  # 逗号分隔；去掉某源即跳过

# arXiv（OAI-PMH）
arxiv_from_date: str | None = None
arxiv_categories: str = "cs.AI,cs.LG,cs.CL,cs.CV"
arxiv_max_records: int = 500

# USPTO（本地 bulk XML，已存 data/raw，无需 key）
uspto_raw_dir: str = "data/raw"             # 周书目 XML 所在目录
uspto_grant_glob: str = "ipgb*/ipgb*.xml"   # 授权首页（PTBLXML）
uspto_app_glob: str = "ipab*/ipab*.xml"     # 申请首页（APPBLXML）
uspto_cpc_prefix: str = "G06N"              # CPC 前缀过滤（AI/ML，逗号分隔可多）
uspto_max_records: int = 200                # 每次处理上限（控图规模）
uspto_keep_weeks: int = 4                   # raw 只保留最近 N 周 XML，更早归档/删除（瘦身）

# GDELT（GKG）
gdelt_from_date: str | None = None
gdelt_max_records: int = 500
gdelt_theme_filter: str = "ARTIFICIAL_INTELLIGENCE,MACHINE_LEARNING"  # GKG Themes 过滤

# GitHub（Search API）
github_from_date: str | None = None
github_min_stars: int = 50
github_max_repos: int = 200
github_topics: str = "machine-learning,deep-learning,llm,artificial-intelligence"

# RSSHub 中文新闻
rsshub_base_url: str = "http://localhost:1200"
rsshub_routes: str = "/36kr/newsflashes,/jiqizhixin"   # 逗号分隔；以 RSSHub 官方路由为准
rsshub_max_items: int = 200

# LLM 抽取（P2 起用，默认切 DeepSeek）
llm_base_url: str = "https://api.deepseek.com/v1"     # 原 None → 改默认
llm_model: str = "deepseek-chat"                      # 原 None → 改默认
llm_max_tokens: int = 2048
llm_batch_size: int = 20
llm_max_docs_per_run: int = 500
llm_temperature: float = 0.0

# 实体对齐（P2）
align_name_threshold: float = 0.90   # string 相似度阈值
align_enable_llm: bool = False       # LLM 消歧（成本高，默认关；先强 ID + string）
```

`.env.example` 同步补五源采集 / LLM / 对齐三段（带注释）；`LLM_API_KEY` 注明「DeepSeek，P2 抽取起用」。各源 key 申请指引沿用 PROJECT_PLAN 2.4（**USPTO 除外**——已本地化到 `data/raw/`，配 `uspto_raw_dir`/glob 即可，不再有 key）。

### API Key 申请清单（P2）

所有 key 填 `.env`（gitignored）。字段在 config.py / `.env.example` 均已就位，只需填值。

| .env 字段 | 用途 | 必需程度 | 申请方式 | 无 key 后果 |
|---|---|---|---|---|
| `LLM_API_KEY`（DeepSeek） | LLM 抽取技术实体/关系 + 中文 tone | **已就位**（本次已填 .env） | platform.deepseek.com | 无 key 只跑结构化抽取，技术实体缺失 |
| `GITHUB_TOKEN` | GitHub Search API（5000 req/h） | **已就位**（本次已填 .env） | GitHub → Settings → Developer settings → Fine-grained token，public repo 只读 | 无 key 降到 60 req/h，易限流 |
| `USPTO_API_KEY` | 专利采集（原 PatentsView v2 / ODP） | **已废弃**（改本地 XML） | — | USPTO 走 `data/raw/` 本地周书目 XML，无需 key |
| `SEMANTIC_SCHOLAR_KEY` | 补充论文源 + DOI 对齐锚 | 可选 | semanticscholar.org/product/api | 共享池易 429，仅补充 |
| `OPENALEX_API_KEY` | 主源 10× 额度 | **已就位**（.env 已有） | openalex.org 邮箱注册 | 无 key 仍可用（1 req/s） |
| `OPENALEX_MAILTO` | polite pool（填邮箱，非申请） | 可选 | 无需申请 | 仅限速差异 |
| `EPO_OPS_KEY` | 专利补充（USPTO 备选） | 可选 | developers.epo.org（OAuth2） | 不影响（USPTO 主源） |

无需 key：arXiv、GDELT、Crossref、DBLP、**USPTO（本地 XML）**。**本次已就位：OpenAlex key、GitHub token、DeepSeek LLM key（.env 均已填）**。

---

## USPTO 数据选型（本地 bulk XML，已存 data/raw）

USPTO 从「PatentsView/ODP API（需 key）」改为「**本地 bulk XML（无 key）**」——周书目文件已下载到 `data/raw/`。按「挑最小、不下全文/PDF」原则，选型如下：

| 本地文件 | USPTO 产品 | 大小 | 内容 | 决定 |
|---|---|---|---|---|
| `data/raw/ipgb*/ipgb*.xml` | PTBLXML（授权书目首页） | ~162M / 周 | 授权专利：号/标题/摘要/受让人/发明人/日期/CPC | ✅ **主用**（字段正好覆盖 KG） |
| `data/raw/ipab*/ipab*.xml` | APPBLXML（申请书目首页） | ~91M / 周 | 公开申请：同上（kind A1） | ✅ **配套**（申请+授权） |
| `data/raw/US_PGPub_CPC_MCF_XML_*` | CPCMCAPP（CPC 主文件） | 32G / 月 | 公开号 → CPC 映射 | ❌ 跳过（首页 XML 已内联 CPC，且体量过大） |
| `data/raw/ai_model_predictions.dta` | ECOPATAI/AIPD | 1.2G / 年 | 1976–2020 AI 专利 ML 预分类（Stata） | 备选：一次性「AI 种子集」（`pandas.read_stata`，P3 冷启动） |
| `data/raw/g_draw_desc_text_2025.tsv` | PVGPATTXT（附图说明） | 777M | 设计专利图注（非技术文本） | ❌ 跳过（无 KG 价值） |
| `data/raw/g_uspc_at_issue.tsv` | PVGPATDIS（USPC 分类） | 2.0G | 授权 USPC 旧分类 | ❌ 跳过（CPC 已在 XML） |

- **只用两套周书目 XML**（`ipgb` + `ipab`），合计 ~250M/周，覆盖 KG 全部所需字段（专利号/标题/摘要/受让人/日期/CPC）；**不下全文/PDF**。
- 周增量：新周文件（`ipgb<YYYYMMDD>_wkNN`）落到 `data/raw/` 即被 collect 拾取，游标记文件名日期（`data/.uspto_cursor`）。
- 实测字段覆盖：`ipgb` 周文件 ~7.5k 件（`invention-title` 7513 / `abstract` 6895 / `assignees` 7036 / `main-cpc` 6889），`ipab` ~11.1k 件（`abstract`/`invention-title`/`main-cpc` 全覆盖 11130，`assignees` 4104——申请早期受让人可能缺失，属正常）。

### USPTO 周文件下载与更新（人工在环 → 后续自动化）

USPTO 首页书目 XML 需**按时下载更新**（USPTO Bulk Data 官网下载页，非 API、无需 key）：

| 需下载文件 | 产品 | 频率 | 用途 | 必需 |
|---|---|---|---|---|
| `ipgb<YYYYMMDD>_wkNN/ipgb<YYYYMMDD>.xml` | PTBLXML 授权书目 | **每周二** | 授权专利首页（主用） | ✅ 必下 |
| `ipab<YYYYMMDD>_wkNN/ipab<YYYYMMDD>.xml` | APPBLXML 申请书目 | **每周四** | 公开申请首页（配套） | ✅ 必下 |
| `US_PGPub_CPC_MCF_XML_*` | CPCMCAPP CPC 主文件 | 每月 | 全量 CPC（首页已内联） | ❌ **不下载**（32G，冗余） |
| `ai_model_predictions.dta` | ECOPATAI/AIPD | 每年 | AI 专利种子集 | 可选（P3 冷启动） |
| `g_*.tsv` | PatentsView 消歧/长文本 | 每季/每年 | 实体消歧/长文本 | ❌ **不下载**（首页够用） |

- 下载到 `data/raw/` 下按周目录存放（`ipgb20260915_wk37/` 命名，文件名含日期即被 collect 拾取）。
- **自动化升级路线**（后续，不阻塞 P2）：先手工下载；下一步用 Playwright/浏览器 **自动打开 USPTO 下载页 → 人在环点下载/过验证码**（USPTO 有验证码/JS，全自动直连不稳定）；再下一步 ODP API key 注册成功后切 API 免人工。

### USPTO 数据瘦身与冗余清理（下载量过大）

原始 bulk 体量巨大（CPC 主文件 32G、PatentsView TSV 2.7G、AIPD 1.2G），P2 从三层控体积：

1. **下载侧只取最小**：只下两套首页书目 XML（~250M/周），不下全文/PDF/CPC 主文件/PatentsView 大 TSV（见上表）。
2. **解析侧流式 + 字段裁剪**：`iterparse` 流式，逐条**只保留 CPC 前缀命中（`G06N` 等 AI/ML）**的记录，且只提取 KG 需要的 7 个字段（号/标题/摘要/受让人/发明人/日期/CPC），丢弃优先权/IPC/附图说明/代理机构等冗余字段——不整棵树进内存，也不把冗余字段写进 `patents.jsonl`。
3. **原始文件落盘后清理**：解析完的周 XML **归档/删除**，`data/raw/` 只保留最近 `uspto_keep_weeks`（默认 4）周；已下载但判定冗余的 `US_PGPub_CPC_MCF_XML_*`(32G)、`g_draw_desc_text_*.tsv`、`g_uspc_at_issue.tsv` 可**直接移出 data/raw 或删除**（对 KG 无贡献）。

清理逻辑并入 CollectStage 收尾（或独立 `techtrend/cleanup_raw.py`，P2 先内联在 collect）。

### 后续专利数据源扩展（补全球/中国专利，不阻塞 P2）

P2 先用本地 USPTO 首页 XML 跑通；**之后**再扩展：

- **USPTO / EPO OPS API 注册重试**：ODP key、EPO OPS（OAuth2，每周 4GB ST36 周前文件）此前注册未成，**之后再试**；成功后可免手工下载、增量更自动。
- **中国专利覆盖**：USPTO 不含中国专利，后续用 **Google Patents（BigQuery 公开数据集 `patents-public-data`）** 与 **Lens.org**（免费 5000 请求/月，人工审批）补中国/全球专利；二者均支持 CN 公开号检索，可作对齐锚点（`cn:...`）。
- 仅登记 roadmap，P2 不实现（避免数据源过载）。

---

## 依赖变更（requirements.txt）

- 取消注释：`openai>=1.40`（DeepSeek 走 OpenAI 兼容接口）。
- 新增：`feedparser>=6.0`（arXiv OAI-PMH Atom + RSSHub RSS 解析）、`rapidfuzz>=3.9`（对齐 string 匹配；无网可退 `difflib`）。
- GDELT 解压用标准库 `zipfile`，不新增依赖。
- USPTO 本地 XML 用标准库 `xml.etree.ElementTree`（流式 `iterparse`），不新增依赖。
- 若启用 AIPD 种子集（`ai_model_predictions.dta`），用 `pandas.read_stata`（pandas 已装）；P2 默认不启。

---

## 各模块详细设计

### 1. sources/arxiv.py —— arXiv OAI-PMH 客户端

```python
class ArxivClient:
    def __init__(self, per_page: int = 100, timeout: float = 30.0)
    def fetch_works(self, from_date: str | None, categories: list[str],
                    max_records: int) -> list[dict]
    def normalize(self, entry: dict) -> dict
    def close(self)
```

- 端点 `http://export.arxiv.org/api/query`；查询 `search_query=cat:cs.AI+OR+cat:cs.LG+...` + `submittedDate:[YYYYMMDD0000+TO+YYYYMMDD2359]`（或 `sortBy=submittedDate&sortOrder=descending`），`start`/`max_results` 分页。
- 响应为 Atom XML，用 `feedparser` 解析（`feed.entries` 每条含 `id`/`title`/`summary`（abstract，纯文本）/`categories`/`published`）。
- 遵守 3s/请求限速（tenacity + 固定间隔）；增量游标存 `data/.arxiv_cursor`（同 OpenAlex 模式）。
- 归一化行：`{"id":"arxiv:2301.00001","title":...,"abstract":...,"categories":["cs.AI"],"publication_date":...}`。**abstract 为纯文本，可直接喂 LLM**。

### 2. sources/uspto.py —— USPTO 客户端（本地 bulk XML，无 key）

```python
class UsptoClient:
    def __init__(self, raw_dir: Path, grant_glob: str = "ipgb*/ipgb*.xml",
                 app_glob: str = "ipab*/ipab*.xml")
    def fetch_patents(self, from_date: str | None, cpc_prefix: str,
                      max_records: int) -> list[dict]      # 解析本地 XML（非网络）
    def _parse_biblio(self, elem: Element) -> dict | None   # 单条首页字段提取
    def normalize(self, record: dict) -> dict
    def close(self)
```

- **数据源形态**：USPTO 周书目 XML 已本地化到 `data/raw/`（无需 key、无网络、无限速）：
  - 授权首页 `ipgb*/ipgb*.xml`（PTBLXML，根 `<us-patent-grant>`，kind B1/S1/D…）；
  - 申请首页 `ipab*/ipab*.xml`（APPBLXML，根 `<us-patent-application>`，kind A1）。
- **解析方式**：`xml.etree.ElementTree.iterparse` 流式逐 `<us-patent-grant>`/`<us-patent-application>` 产出（单文件 91–162M，避免整棵 DOM 进内存）；取字段：
  - `publication-reference/document-id` → `doc-number`（专利号/公开号）、`kind`、`date`（出版日）；
  - `invention-title` → 标题；`abstract/p` → 摘要（纯文本，喂 LLM）；
  - `us-parties` 下 `applicants/assignees/inventors` → 名称列表；
  - `classifications-cpc/main-cpc` → 拼 `section+class+subclass+main-group+subgroup` 成 CPC 码（如 `G06N`）。
- **过滤**：`cpc_prefix`（默认 `G06N`，AI/ML 主分类）前缀匹配 + `from_date` + `max_records` 截断。
- **增量**：以文件名日期为单位（`ipgb20260915` 等），游标 `data/.uspto_cursor` 记最后处理文件；新增周文件追加处理。
- 归一化行：`{"id":"uspto:<doc-number>","title":...,"abstract":...,"assignees":[...],"inventors":[...],"publication_date":...,"cpc":["G06N"],"kind":"A1"}`。

### 3. sources/gdelt.py —— GDELT GKG 客户端

```python
class GdeltClient:
    def __init__(self, timeout: float = 60.0)
    def fetch_news(self, from_date: str | None, theme_filter: list[str],
                   max_records: int) -> list[dict]
    def normalize(self, row: list[str]) -> dict
    def close(self)
```

- 按天下载 GKG 文件：`http://data.gdeltproject.org/gdeltv2/<YYYYMMDDHHMMSS>.gkg.csv.zip`（默认取当日 0 点文件），`httpx` 下载 → `zipfile` 解压 → `csv` 读。
- GKG 列含 `GKGRECORDID`/`DATE`/`V2Themes`（逗号分隔主题）/`V2Locations`/`V2Persons`/`V2Organizations`/`V2Tone`（含 tone 均值）；按 `theme_filter` 过滤出 AI/CS 相关行。
- **体量大**：只取前 `max_records` 行 + 主题过滤后截断；日期游标 `data/.gdelt_cursor`。
- 归一化行：`{"id":"gdelt:<GKGRECORDID>","title":None,"text":<拼接 Persons/Orgs/Themes>,"entities":{...},"themes":[...],"tone":float,"publication_date":...}`。中文覆盖弱，实体/tone 依赖后续 LLM 抽取。

### 4. sources/github.py —— GitHub Search API 客户端

```python
class GithubClient:
    def __init__(self, token: str | None, timeout: float = 30.0)
    def fetch_repos(self, from_date: str | None, topics: list[str],
                    min_stars: int, max_repos: int) -> list[dict]
    def normalize(self, repo: dict) -> dict
    def close(self)
```

- `GET /search/repositories?q=created:>DATE+stars:>=N+topic:AI`（`Accept: application/vnd.github+json`，token 进 `Authorization` 头）。
- 未认证 60 req/h → 认证 5000 req/h（token 从 `.env`）；tenacity 处理 403/429。
- **自建每日 star 快照**：`data/interim/github_stars.jsonl` 追加当日 `{full_name, stars, fetched_at}`，供 P3 star 时序（趋势核心信号，从一开始就记录）。
- 归一化行：`{"id":"github:<owner>/<repo>","name":full_name,"description":...,"url":html_url,"stars":N,"topics":[...],"created_at":...}`。description 喂 LLM。

### 5. sources/rsshub.py —— RSSHub 中文新闻客户端

```python
class RssHubClient:
    def __init__(self, base_url: str, timeout: float = 30.0)
    def fetch_items(self, routes: list[str], max_items: int) -> list[dict]
    def normalize(self, item: dict, route: str) -> dict
    def close(self)
```

- 前置：Docker 起 RSSHub（`docker run -d -p 1200:1200 diygod/rsshub`），选中文科技媒体路由（36氪/虎嗅/机器之心/量子位）。
- `httpx` 拉 `{base_url}{route}`（RSS/Atom），`feedparser` 解析；每 item 取 `title`/`link`/`summary`/`published`。
- 归一化行：`{"id":"rsshub:<link>","title":...,"text":<summary 去 HTML>,"url":link,"publication_date":...}`。中文 `text` 喂 LLM 抽实体/tone。

> 各源客户端均沿用 OpenAlexClient 风格：`__init__`（挂 client/headers/params）→ `fetch_*`（分页/限速/重试）→ `normalize`（字段裁剪归一化）→ `close` + `__enter__/__exit__`；在 `sources/__init__.py` 统一导出。

### 6. extraction/schema.py —— 实体/关系类型常量

```python
TECH_ENTITY_TYPES = ("Technology", "Method", "Model", "Framework", "Dataset", "Institution", "Person")
DOC_ENTITY_TYPES  = ("Paper", "Patent", "Repo", "News")        # 源文档节点
P1_ENTITY_TYPES   = ("Concept", "Author")                       # P1 已固化

RELATION_RULES_LLM = {            # LLM 抽取的 7 关系 → 中文语义
    "uses":        "使用",
    "improves":    "改进",
    "compares":    "对比",
    "belongs_to":  "属于",
    "targets":     "针对",
    "competes":    "竞品",
    "causes":      "因果",
}
RELATION_MENTIONS = "mentions"    # 新闻类兜底：News → 实体（仅被提及）
```

### 7. extraction/llm.py —— LLM 抽取（DeepSeek）

```python
class LLMExtractor:
    def __init__(self, api_key: str, base_url: str, model: str,
                 max_tokens: int = 2048, temperature: float = 0.0)
    def extract(self, doc: dict) -> list[dict]        # 单文档 → 技术三元组
    def extract_batch(self, docs: list[dict]) -> list[dict]  # 批量（限 llm_batch_size）
    def extract_tone(self, text: str) -> float | None  # 中文新闻情感（-1..1）
```

- 用 `openai.OpenAI(base_url=..., api_key=...)`；`chat.completions.create` + `response_format={"type":"json_object"}`。
- **Prompt 设计**（few-shot + 强制 JSON schema）：
  - 输入：`title` + `abstract`/`text`（英文论文摘要 / GitHub 描述 / 中文新闻正文）。
  - 输出：`{"triples":[{"head_type","relation","tail","tail_type"}]}`；`tail` 为实体名（无 ID，align 阶段补 `entity_id`）。
  - 关系限 schema.py 的 7 种 + `mentions`；实体类型限 `TECH_ENTITY_TYPES`。
  - 英文/中文通用（中文新闻单独走 `extract_tone`）。
- 成本控制：`llm_max_docs_per_run` 上限；逐条 try/except（单条失败不阻断整批）；tenacity 重试 429/5xx。
- **无 key 时**（`llm_api_key` 为空）：LLM 抽取整体跳过并 warning，只跑结构化抽取——维持 P0/P1「无 key 也能跑通」原则。

### 8. graph/neo4j_client.py 改造（schema 泛化）

- `_NODE_LABELS` 扩为：`Paper, Concept, Author, Institution, Patent, Repo, News, Technology, Method, Model, Framework, Dataset, Person`。
- `_EDGE_TYPES` 扩为：P1 的 `BELONGS_TO, AUTHORED_BY, AFFILIATED_WITH, CITES` + 新 `USES, IMPROVES, COMPARES, TARGETS, COMPETES, CAUSES, MENTIONS`。
- **唯一约束改在 `entity_id`**（每 label 一条 `FOR (x:Label) REQUIRE x.entity_id IS UNIQUE`）；`openalex_id`/`uspto_id`/`github_url`/`url` 降为溯源属性。
- `_RELATION_SPECS` 补新关系的 `head_label`/`tail_label`（如 `USES: Paper/Patent/Repo→Technology/Method/Model/Framework/Dataset`；`MENTIONS: News→任意技术实体`）。
- `upsert_triples` 的 MERGE 主键从 `openalex_id` 改为 `entity_id`（`MERGE (x:Label {entity_id:$eid})`），节点属性写 `name/title/pub_date/source` 等。

### 9. graph/loader.py 改造

```python
def load_triples(client, triples, nodes) -> dict  # 签名不变，内部按 entity_id MERGE
```

- 对齐后 triples 用 `head_id`/`tail_id`（缺省回退 `head`/`tail`）；nodes 用 `entity_id`（缺省 `id`）。
- 节点属性按类型分支写（Paper→title/pub_date、Patent→title/pub_date、Repo→name/url/stars、News→name/url、技术实体→name）。

### 10. graph/alignment.py —— 跨源实体对齐

```python
def normalize_name(name: str) -> str                     # 小写/去空白/去标点
def align_entities(nodes: list[dict], triples: list[dict],
                   threshold: float = 0.90,
                   use_llm: bool = False) -> tuple[list[dict], list[dict], list[dict]]
    # → (对齐后 nodes, 对齐后 triples, alignment 审计行)
```

三级流水线（先到先得，后级只处理未对齐的）：

1. **强 ID 锚点**：源文档节点天然唯一（`arxiv:...`/`uspto:...`/`github:...`/`rsshub:<url>`/`gdelt:<id>`），直接赋 `entity_id`；同一 DOI 的论文跨 OpenAlex/arXiv 合并（arXiv 无 DOI 时按 arXiv id 锚）。
2. **String 匹配**：技术实体（Technology/Method/Model/Framework/Dataset）与 OpenAlex `Concept` 做 `normalize_name` + `rapidfuzz.ratio`，≥ `threshold` 则映射到 `Concept` 的 `entity_id`（把 LLM 实体对齐到 OpenAlex 概念统一 ID）；`Institution`/`Person` 同理对 `Institution`/`Author`。未命中者生成确定性 `entity_id`（如 `sha1(source|type|name)` 前 12 位）。
3. **LLM 消歧**（可选，`align_enable_llm`）：对 string 匹配的模糊区间（0.75~0.90）交给 LLM 判断是否同一实体；默认关闭控成本。

- 输出 `data/interim/alignment.jsonl`：每行 `{entity_id, type, name, source, anchor_id}`，供审计「五源对齐」验收。
- 对齐后 nodes 补 `entity_id`；triples 补 `head_id`/`tail_id`。

### 11. 各 stage 改造

- **CollectStage**：读 `collect_sources`，逐源调客户端写对应 interim 文件；每源独立 try/except（单源失败记 `status:"error"` 不影响他源）；汇总 `{"sources":{name:count|"error"}}`。增量游标每源一个 `data/.<source>_cursor`。
- **ExtractStage**：① 结构化抽取（OpenAlex 复用；arXiv/USPTO 的 category/cpc 映射为 `belongs_to` Concept，作者/机构映射 `authored_by`/`affiliated_with`）；② LLM 抽取（arXiv 摘要、GitHub 描述、USPTO 摘要、RSSHub/GDELT 新闻正文）；合并去重（同 `dedupe_earliest`）写 `triples.jsonl`/`nodes.jsonl`。
- **AlignStage**（新）：调 `graph.alignment.align_entities`，回写对齐结果 + `alignment.jsonl`。
- **BuildGraphStage**：读对齐后文件，调 `load_triples`。
- **PredictStage / ReportStage**：逻辑不变；`report.py` 标题「P1」→「P2」，`predict.py` 的 `_run_kleinberg` 排除项沿用筛选概念。

---

## 实施顺序（任务分解）

1. `config.py` + `.env.example` + `requirements.txt`（feedparser/openai/rapidfuzz 取消注释并安装）。
2. `sources/arxiv.py` → CollectStage 接多源框架 → 先跑通 `--stage collect` 只开 `arxiv`（`collect_sources=arxiv`），核对 `arxiv.jsonl` 数量/日期/去重。
3. 逐个接入 `github.py` → `uspto.py`（本地 XML：先跑通 `ipgb`/`ipab` 两文件、核对 CPC 前缀过滤与日期截断）→ `gdelt.py` → `rsshub.py`（每接一个跑一次 collect 核对，独立调试）。
4. `extraction/schema.py` + `extraction/llm.py` → ExtractStage 结构化+LLM 合并（先无 key 跑结构化，再填 key 跑 LLM，核对关系分布）。
5. `graph/neo4j_client.py` schema 泛化 + `loader.py` 改造 → BuildGraphStage（浏览器查多源节点/边标签）。
6. `graph/alignment.py` + `align.py` → 六阶段串起来（核对 `alignment.jsonl` 对齐命中数）。
7. `predict.py`/`report.py` 措辞 + `pipeline.py`/`main.py` 文案 P1→P2。
8. 端到端全量验证 + 写本 `P2_PLAN.md`。

---

## 验证方式（端到端）

```bash
# 1. 前置服务：Neo4j（沿用 P1）+ RSSHub（中文新闻源）
docker run -d --name neo4j-techtrend -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/<密码> -v neo4j_data:/data neo4j:5
docker run -d --name rsshub -p 1200:1200 diygod/rsshub     # P2 新增

# 2. 装依赖（沿用 P0/P1 conda 环境 + 完整路径）
& 'F:\Predictive agents\.venv\Scripts\python.exe' -m pip install -r requirements.txt

# 3. 逐源 collect 核对
& 'F:\Predictive agents\.venv\Scripts\python.exe' main.py --stage collect   # 看 sources 汇总：五源各多少条 / 谁 error
& 'F:\Predictive agents\.venv\Scripts\python.exe' main.py --stage extract   # triples.jsonl：关系分布含 uses/improves/...（有 key 时）
& 'F:\Predictive agents\.venv\Scripts\python.exe' main.py --stage align     # alignment.jsonl：anchored/string/llm 命中计数
& 'F:\Predictive agents\.venv\Scripts\python.exe' main.py --stage build_graph  # http://localhost:7474 查多源节点/边
& 'F:\Predictive agents\.venv\Scripts\python.exe' main.py --stage predict   # baseline_metrics.json 仍产出（大图上）
& 'F:\Predictive agents\.venv\Scripts\python.exe' main.py                   # 六阶段全量跑通，exit 0
```

**验收标准**：
1. `collect` 五源（含 OpenAlex）各产出非空 interim 文件、时间戳正确、重跑增量不重复。
2. Neo4j 出现 `Patent`/`Repo`/`News` 文档节点与 `Technology/Method/Model/Framework/Dataset/Person` 技术实体节点，以及 `USES/IMPROVES/.../MENTIONS` 边。
3. `alignment.jsonl` 中同一技术实体跨源（如 arXiv 论文与 OpenAlex concept 同名）共享同一 `entity_id`。
4. 无 LLM key 时 `main.py` 仍 exit 0（仅 LLM 抽取跳过并 warning；USPTO 走本地 XML 不再依赖 key）。

---

## 风险与注意

- **USPTO 数据本地化（免 key）**：P2 直接解析 `data/raw/` 已存的周书目 XML（`ipgb`/`ipab`），**无需 key**；周更新需手工下载新周文件到 `data/raw/`（后续可补自动下载器），缺文件时该周跳过、不阻断。
- **不要用 CPC 主文件（32G）**：`US_PGPub_CPC_MCF_XML_*` 体量巨大且首页 XML 已内联 CPC，除非需全量 CPC 补全否则跳过；PatentsView 的 `g_draw_desc_text`（图注）/`g_uspc_at_issue`（旧 USPC）对 KG 无价值，同样跳过。
- **AIPD 种子集为 Stata（.dta）**：`ai_model_predictions.dta`（1.2G）需 `pandas.read_stata`，仅作一次性「AI 专利种子」；P2 默认不启，留 P3 冷启动用。
- **GDELT GKG 体量巨大**：必须主题过滤 + `max_records` 截断 + 只取日文件首段，否则单次下载/解析过重。
- **LLM 幻觉与成本**：强制 JSON schema + 关系/实体白名单 + 温度 0；`llm_max_docs_per_run` 控成本；幻觉后处理靠「关系类型白名单过滤 + 实体名去重」。
- **对齐阈值调参**：`align_name_threshold` 过高合并不足、过低误合并；先用强 ID 锚点保证确定性，string 匹配阈值从 0.90 起步对拍。
- **GitHub star 无历史**：P2 起自建每日快照 `github_stars.jsonl`（否则 P3 无趋势信号）。
- **arXiv 3s/请求、GitHub 60/5000 req/h 限速**：tenacity 退避 + 固定间隔；token 只申请 public 只读最小权限。
- **Neo4j schema 迁移**：`entity_id` 主键改动会与 P1 已建约束冲突——需先 `DROP CONSTRAINT` P1 的 `openalex_id` 约束（或重开容器/清库）再建新约束，计划中明确为一次性迁移。
