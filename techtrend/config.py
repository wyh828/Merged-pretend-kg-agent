"""集中配置：pydantic-settings 从 .env 读取，全部字段有默认值。

保证无 .env、无任何 key 时 `python main.py` 也能干净跑通。
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 项目路径
    data_dir: Path = Path("data")
    output_dir: Path = Path("output")
    log_dir: Path = Path("logs")
    log_level: str = "INFO"

    # ---- 信号层（阶段0 合并引入：her 的「话题/源配置层」接入点，只读指针）----
    signal_topics_path: str = "techtrend/signal/configs/topics.yaml"
    signal_sources_path: str = "techtrend/signal/configs/sources.yaml"

    # Neo4j（P1 起用）
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j"

    # OpenAlex 采集
    openalex_mailto: str | None = None      # 进 polite pool（可选）
    openalex_api_key: str | None = None     # premium key（可选，额度 10×）
    openalex_from_date: str | None = None   # 增量起点，如 "2023-01-01"（首次无游标时的种子）
    openalex_concept_ids: str = "C154945302,C41008148"  # 逗号分隔（AI/CS）
    openalex_max_works: int = 1000
    openalex_per_page: int = 200

    # CrossRef（阶段 3 合并，第 7 源；DOI 锚点 + mailto polite pool + 增量游标）
    crossref_mailto: str | None = None        # 进 polite pool（推荐填真实邮箱）
    crossref_from_date: str | None = None     # 增量起点，如 "2023-01-01"（无游标时的种子）
    crossref_max_records: int = 500
    crossref_per_page: int = 100

    # 结构化抽取（P1）
    extract_max_concepts: int = 5     # belongs_to 每条 work 取 score 前 N 个 concept
    extract_max_refs: int = 10        # cites 每条 work 取前 N 条引用（控图谱规模）

    # 预测（RotatE / Kleinberg）
    rotate_embedding_dim: int = 128
    rotate_epochs: int = 50
    rotate_train_ratio: float = 0.8
    burst_bin: str = "month"
    burst_s: float = 2.0
    burst_gamma: float = 1.0
    burst_future_months: int = 6
    burst_top_k: int = 10

    # ---- 时序预测（P3）----
    # TKG 外推（CyGNet / TLogic）
    predict_enable_tkg: bool = True
    tkg_relation: str = "relates_to"     # 投影边关系名
    tkg_doc_types: str = "Paper,Patent,Repo"  # 参与投影的文档类型（默认排除 News：GDELT 单日快照 + 事件主题非技术实体）
    tkg_max_time: str | None = None      # 过滤 time > 此日期 的坏数据（None = 自动用今天日期）
    tkg_min_cooccur: int = 2             # 投影边最小共现次数（降噪）
    tkg_max_entities: int = 5000         # 按度截断，控 TKG 规模
    tkg_train_ratio: float = 0.7
    tkg_val_ratio: float = 0.1           # test = 1 - train - val
    tkg_embedding_dim: int = 128
    tkg_epochs: int = 30
    tkg_neg_samples: int = 10            # 每条正例的负采样数
    tkg_alpha: float = 0.5               # copy vs generate 融合权重（亦可训练）

    # ---- 定向技术关系（P3.5 优化）----
    techpair_enable: bool = True          # 是否启用定向 tech→tech 抽取（需 llm_api_key，无 key 自动跳过）
    techpair_relations: str = "uses,improves,compares,targets,competes"  # 定向关系白名单（逗号分隔）
    techpair_min_support: int = 1         # 定向边最小计数（定向边极稀疏，跨文档重复罕见，默认 1 保边；可调高降噪）
    techpair_openalex_max_docs: int = 1000  # OpenAlex works 定向对抽取上限（有摘要才抽；arXiv/USPTO 均为近期快照无时态分布，OpenAlex 是定向图时间跨度来源）
    tkg_edge_source: str = "cooccur"      # TKG 边源：cooccur(共现投影，正式主边源) | directed(定向 tech→tech，消融对照)；专利引用图经 P2-1 证伪，不再作为 TKG 边源
    tkg_sequence_generate: bool = False   # 序列化 generate（GRU）开关；默认关（数据量小易过拟合）
    tkg_gru_hidden: int = 64              # GRU 隐层（tkg_sequence_generate=True 时生效）

    # ---- 专利前向引用图（P0-1，免 key）----
    patent_citation_source: str = "uspto_local"  # 引用数据来源：uspto_local(本地 XML 抽取) | patentsview(bulk 下载) | bigquery(解析导出 CSV)
    patent_citation_max_edges: int = 2000000     # 本地 XML 抽取后向引用对上限（控内存/耗时）
    patent_citation_min_time: str | None = None  # 前向引用时态下界（如 "2010-01-01"；None=不设下界，含全部年份）
    patent_citation_max_patents: int = 5000      # 只保留被引次数 top-N 的奠基专利（控图规模 + 保留高重复结构）
    patent_citations_file: str = "data/interim/patent_citations.jsonl"  # 前向引用图产物（head=被引专利, relation=cited_by, tail=引用专利, time=引用日）

    # TLogic 规则层
    tlogic_min_support: int = 3          # 定向图 800 事实下 support≥3（≈0.4% 边）即视为反复出现的方向性模式
    tlogic_min_confidence: float = 0.05  # 定向关系天然远低于对称共现（~1.0），0.05 为方向性蕴含合理下限
    tlogic_max_len: int = 3              # 规则体原子数上限

    # 指标时序回归（目标③）
    forecast_horizon: int = 6            # 预测未来月数
    forecast_min_history: int = 12       # 最少历史箱数
    forecast_top_k: int = 100            # 只对最活跃 top-k 实体做回归
    forecast_lag: int = 6                # 滞后特征窗口

    # 融合（目标①集成）
    fusion_weights: str = "burst=0.3,tkg=0.4,forecast=0.3"  # 逗号分隔 name=weight
    fusion_top_k: int = 10
    # 融合第一路信号源（阶段1 合并）：share(相对份额动量，默认) | kleinberg(突发，消融对照)
    fusion_signal_source: str = "share"

    # ---- 多智能体协同（阶段 5 合并）----
    collab_signal_weight: float = 0.5   # 共识分中信号 agent 的权重（1-该值 = 链接预测 agent）

    # ---- 验证体系（P4）----
    eval_enable: bool = True
    eval_n_splits: int = 5              # walk-forward 折数
    eval_test_months: int = 1           # 每折测试窗口（"后一月"）
    eval_step_months: int = 1           # 折间步长（rolling origin 前进量）
    eval_embargo_months: int = 1        # TKG：train 与 test 间缓冲（剔除近邻事实）
    eval_purge_months: int = 6          # 回归：label 重叠剔除窗口（≈ forecast_horizon）
    eval_mode: str = "expanding"        # expanding | rolling
    eval_rolling_window_months: int = 24  # rolling 模式的训练窗口长
    eval_min_train: int = 200           # 每折最少训练事实，否则跳过该折

    # 数据源 key（全部可选）
    github_token: str | None = None
    uspto_api_key: str | None = None
    epo_ops_key: str | None = None
    semantic_scholar_key: str | None = None

    # 多源采集开关（P2，逗号分隔；去掉某源即跳过）
    collect_sources: str = "openalex,arxiv,uspto,gdelt,github,rsshub"

    # arXiv（OAI-PMH / Atom）
    arxiv_from_date: str | None = None
    arxiv_categories: str = "cs.AI,cs.LG,cs.CL,cs.CV"
    arxiv_max_records: int = 500

    # USPTO（本地 bulk XML，已存 data/raw，无需 key）
    uspto_raw_dir: str = "data/raw"             # 周书目 XML 所在目录
    uspto_grant_glob: str = "ipgb*/ipgb*.xml"   # 授权首页（PTBLXML）
    uspto_app_glob: str = "ipab*/ipab*.xml"     # 申请首页（APPBLXML）
    uspto_cpc_prefix: str = "G06N"              # CPC 前缀过滤（AI/ML，逗号分隔可多）
    uspto_max_records: int = 200                # 每次处理上限（控图规模）
    uspto_keep_weeks: int = 4                   # raw 只保留最近 N 周 XML

    # GDELT（GKG）
    gdelt_from_date: str | None = None
    gdelt_max_records: int = 500
    # GKG Themes 过滤（真实主题名：TECH_*/SOC_EMERGINGTECH/WB_* ICT·软件·创新 + 网络攻击）
    gdelt_theme_filter: str = (
        "TECH_AUTOMATION,TECH_SUPERCOMPUTING,TECH_VIRTUALREALITY,"
        "SOC_EMERGINGTECH,SOC_TECHNOLOGYSECTOR,"
        "WB_133_INFORMATION_AND_COMMUNICATION_TECHNOLOGIES,"
        "WB_669_SOFTWARE_INFRASTRUCTURE,WB_665_SOFTWARE_AS_A_SERVICE,"
        "WB_676_CLOUD_COMPUTING,WB_2381_SOFTWARE_DEVELOPMENT,"
        "WB_2399_ICT_INNOVATION_AND_TRANSFORMATION,"
        "WB_376_INNOVATION_TECHNOLOGY_AND_ENTREPRENEURSHIP,"
        "CYBER_ATTACK"
    )

    # GitHub（Search API）
    github_from_date: str | None = None
    github_min_stars: int = 50
    github_max_repos: int = 200
    github_topics: str = "machine-learning,deep-learning,llm,artificial-intelligence"

    # RSSHub 中文新闻
    rsshub_base_url: str = "http://localhost:1200"
    rsshub_routes: str = "/36kr/newsflashes,/cnbeta"   # 36氪快讯 + cnBeta 中文业界资讯（jiqizhixin 路由已下线）
    rsshub_max_items: int = 200

    # LLM 抽取（P2 起用，默认切 DeepSeek）
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"
    llm_max_tokens: int = 2048
    llm_batch_size: int = 20
    llm_max_docs_per_run: int = 500
    llm_temperature: float = 0.0

    # 实体对齐（P2）
    align_name_threshold: float = 0.90   # string 相似度阈值
    align_enable_llm: bool = False       # LLM 消歧（成本高，默认关；先强 ID + string）

    # ---- 编排与自动化（P5）----
    # 双轨调度：hermes-agent cron（主）/ APScheduler（降级），入口统一 cron.py
    schedule_enable: bool = False            # 启用内置 APScheduler 调度（hermes-agent 接管时关）
    schedule_cron: str = "0 3 * * *"         # 每日 03:00 本地（避免整点；见 PROJECT_PLAN 调度避峰惯例）
    schedule_timezone: str = "Asia/Shanghai"

    # 每日运行（runbook）
    daily_mode: str = "incremental"          # incremental(增量,默认) | full(全量，不短路下游)
    daily_skip_if_no_new: bool = True        # 全源 0 新增 → 短路下游，写 no-op stamp
    run_manifest_file: str = "output/run_manifest.jsonl"   # 每次运行追加一条

    # 报告推送（notify，第 8 阶段）
    notify_enable: bool = False              # cron 无人值守开 true；手动 main.py 保持 false
    notify_channels: str = "file"            # 逗号分隔：file,telegram,discord
    notify_telegram_bot_token: str | None = None
    notify_telegram_chat_id: str | None = None
    notify_discord_webhook: str | None = None
    notify_report: str = "report.md"         # 推送哪个报告：report.md | eval_report.md

    # 人在环审校（HITL）
    review_enable_hitl: bool = False         # 报告前暂停人工确认（交互演示开）
    review_auto_approve: bool = True         # 无人值守自动通过；False = 等待 review_approve.json
    review_timeout_seconds: int = 0          # HITL 等待超时（秒）；0 = 不限

    # ---- 可视化 / 报告（P6）----
    viz_enable: bool = True                  # VisualizeStage 开关
    viz_dashboard_file: str = "output/dashboard.html"
    viz_charts_dir: str = "output/charts"
    viz_top_k: int = 20                      # 趋势图 / 榜单展示 top-N 概念/专利
    viz_theme: str = "auto"                  # auto(跟随系统) | light | dark

    # 生命周期（目标④）
    lifecycle_growth_window: int = 6         # 增速比较窗口（月）
    lifecycle_emerging_quantile: float = 0.2  # 累积量分位阈值（判 emerging）
    lifecycle_min_history: int = 12          # 曲线最少箱数，不足标 emerging

    # S 曲线选样（专利，承 P4_P3_RESULT §5 待办）
    patent_citation_sampling: str = "stratified"  # stratified(分层) | top_total(旧行为，保留对照)
    patent_citation_n_bins: int = 5              # 分层箱数（按 log10 总被引）
    patent_citation_per_bin: int = 2000          # 每箱采样上限

    # 周报
    weekly_enable: bool = True
    weekly_weekday: int = 0                  # 周一=0（周边界由 VisualizeStage 触发）
    weekly_window_days: int = 7              # 聚合最近 N 天 manifest
    weekly_report_file: str = "output/weekly_report.md"


@lru_cache
def get_settings() -> Settings:
    """返回缓存的 Settings 单例。"""
    return Settings()
