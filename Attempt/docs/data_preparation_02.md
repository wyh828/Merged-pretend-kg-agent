# Data Preparation 02

## 目标与已确认范围

用户要求继续上一轮未完成的数据准备：先修复代码、环境和存储，再重新获取数据；领域不限；保留热度增长、新技术关联、专利引用增长三个目标。沿用 `codex/merged-local-00`、十阶段流水线和现有 Python 依赖。修改前检查点 `codex/checkpoint-before-data-prep-02` 对应 `88881d6`。本轮只使用 OpenAlex/Crossref 公开免费额度和本机 Neo4j，没有调用 LLM、付费服务、定时任务或通知。

## 当前数据流与接口

```text
Settings / .env: collection dates + DATA_DIR
Attempt/configs/data_preparation_02.yaml: source parameters + budgets + quality rules
  -> API original responses: raw/<source>/<collection-date>/*_NN.jsonl
  -> response metadata + SHA-256 sidecars
  -> per-query append-only ledger: metadata/preparation_queries_02.jsonl
  -> normalized snapshots: interim/snapshots/*_NN.jsonl
  -> imprecise-date quarantine: interim/quarantine/*_NN.jsonl
  -> deduplicated working index: interim/works.jsonl
  -> versioned corpus monthly counts + sample coverage: processed/*_NN.jsonl/.csv
  -> ExtractStage -> AlignStage -> Neo4j (bounded idempotent batches)
  -> existing dashboard reads coverage, independent corpus counts and audit documents
```

主采集与信号侧默认入口现在共用本工程的存储根和历史窗口；信号侧 `end_date` 是排他月，因此统一窗口为 `2016-01` 到 `2026-01`，对应 2016–2025 的 120 个完整月。显式旧实验配置仍保留自身参数。六主题 YAML 保留为历史关键词对照，不能代表全部学科；本轮宽领域数据由 API 返回的主学科注册表驱动，主采集默认不再限定 AI/CS。arXiv/GitHub/USPTO 的旧专项过滤未被宣称为全领域覆盖，尚需来源适配和覆盖验证。

## 逐项问题、修订与检查

| 函数/阶段 | 复现的问题 | 修订与验收 |
|---|---|---|
| OpenAlex/Crossref fetch_batch | 条数上限截断已下载页面；无法可靠续页；OpenAlex 旧页码/200 条参数 | 请求仅剩余条数，返回明确 `complete` 与 `next_cursor`，使用 cursor；OpenAlex 每页至多 100；按出版时间顺序 |
| CollectStage academic progress | 达上限仍把日期进度写为今天，后续漏采历史 | 先保存原响应与标准化记录，再写页断点；完整窗口结束才推进日期；上限停止保留剩余 cursor |
| Crossref normalize | DOI 登记日期被当作论文出版日期 | 只使用 published/issued；记录日期精度，缺日或无出版日期保留到 quarantine |
| OpenAlex normalize | 新版 Topics 不符合旧 concepts 下游接口 | 保留 topics/primary_topic，并将 Topics 映射到现有 concepts 合同；标注 classification_scheme，补 source |
| CrossrefCollector / MonthCountCollector | 无统计字段响应被记成成功且为零；使用虚构联系邮箱 | 校验统计字段；错误记 `activity_count=null` 和 failed；联系邮箱可空 |
| DataPreparation | 需要跨年跨学科覆盖、原文、重跑和来源审计 | 逐月主学科分组含 unknown，并与 meta.count 相等；分学科年份按固定 seed 抽样；每个原响应独立 SHA-256；成功任务离线复用 |
| 实测主学科注册表 | 未分类组使用 `https://openalex.org/fields/unknown`，初次适配误算为一个学科 | 增加实测反例；只有数字 field ID 算正式学科，unknown 单列。保留初次结果，当前有效摘要为 preparation_summary_01.json、field_registry_03.json |
| 原始/派生版本管理 | 更换摘要文件扩展名可能复用旧编号并覆盖派生表 | 编号考虑同族全部扩展名；保留旧 `monthly_activity_00`，新结果使用 `_01` |
| 大量样本追加 | 每次都重读整个 works 索引，成本随总量增长 | 一个运行内复用 ID 集合，成功追加后才更新；重启仍从磁盘恢复 |
| Neo4jClient upsert | “批量”写入实际逐条发查询，整个图使用一个事务 | 每类型分组，UNWIND；默认每批 500，可配置；失败传播，已完成批次可幂等重放。双日期、可得性未知、测试数据清理实测通过 |
| 看板 | 固定每层抽取量容易被误解为真实热度 | 展示独立 API 月度汇总、覆盖卡片、全部学科明细、审计文档；种子记录不生成概念生命周期趋势 |

## 来源、日期与许可

历史窗口为 **2016-01-01 至 2025-12-31**，收集时间见每份响应及元数据。2026 是未结束年份，本轮排除，不能把未取得月份记零。使用 Python 3.13.9，现有 .venv、httpx、PyYAML、Neo4j 等依赖；环境基础快照在 local_environment_00.txt。没有新增依赖。

- [OpenAlex API 认证与免费额度](https://help.openalex.org/api/authentication/)；[主学科分组](https://help.openalex.org/api/grouping/)；[Topics](https://help.openalex.org/data/topics/)。元数据 CC0，许可说明见 [OpenAlex Pricing](https://help.openalex.org/access/pricing/)。响应原文与完整非敏感查询均保存。
- [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) 的大部分事实元数据公开可用；部分摘要版权归出版社或作者。只取得元数据，没有下载全文；不假定全文许可。使用按月出版过滤，取首 5 条作元数据接口种子，不能称为代表性样本。
- OpenAlex 每个“学科 × 年份”随机抽 20 条，seed=42，corpus=core；固定 seed 对当前索引可重复，未来索引修订仍可能改变结果，因此真正可复核依据为已保存的原响应。
- API 返回的被引总数、参考文献和分类是当前回溯版本。`historical_available_at=null`；被引总数额外记 `cited_by_count_as_of`。不将今天的收集时间冒充当年公开时间。
- Crossref cursor 可能在闲置后失效；主采集不会因此推进日期。遇到失效需重放该窗口并去重，不能声称任意跨日深游标都永久有效。

## 本轮实际结果

| 项目 | 结果 |
|---|---:|
| 正式主学科 | 26；另有未分类组 |
| OpenAlex / Crossref 成功月份 | 各 120 / 120 |
| OpenAlex 学科年份层 | 260 / 260，每层 20 条种子 |
| 首次请求 / 原始响应 | 511，均成功；OpenAlex 391、Crossref 120 |
| 离线重跑新增网络请求 | 0 |
| 原响应文件总大小 | 约 80.93 MiB |
| 标准化去重文献 | 5,375：OpenAlex 5,200 + Crossref 175 |
| 日期精度不足的隔离记录 | 425，均为 Crossref；原记录完整保留 |
| 有分类 / 有参考文献的记录 | 5,200 / 2,674 |
| 月度覆盖表行数 | 3,360：27 组 × 120 月 + Crossref 120 月 |
| OpenAlex 期间文献汇总 | 111,242,266；其中未分类 9,339,909 |
| Crossref 期间 DOI 记录汇总 | 76,002,104，与 OpenAlex 有重叠，不可相加 |
| 抽取 / 对齐保留事件 | 62,093 / 62,093 |
| Neo4j 实体 / 事件关系 | 53,687 / 62,093；第二次导入数量相同 |

图实体包含参考文献占位、作者、机构和主题，**53,687 不是已下载全文或完整元数据的文献数量**。结构化抽取产生 cites 24,040、belongs_to 13,545、authored_by 17,285、affiliated_with 7,223。未调用 LLM；未生成未经回测验证的预测结论。

当前有效文件在 `Data/Datasets/technology_trends_01`：metadata/preparation_summary_01.json、metadata/data_validation_00.json、metadata/field_registry_03.json、processed/monthly_activity_01.jsonl/.csv、processed/sample_coverage_01.jsonl。图谱过程保留于 processed/graph_preparation_00 和 _01。第一次摘要误将 unknown 计入 27 学科的历史文件保留作审计，不用作当前覆盖结论。

## 运行与验证命令

```powershell
Set-Location 'F:\Predictive agents'
& '.\.venv\Scripts\python.exe' Attempt/scripts/prepare_data_02.py
& '.\.venv\Scripts\python.exe' Attempt/scripts/verify_data_02.py
& '.\.venv\Scripts\python.exe' Attempt/scripts/verify_database_01.py
& '.\.venv\Scripts\python.exe' Attempt/scripts/prepare_graph_02.py --load-database
& '.\.venv\Scripts\python.exe' main.py --stage visualize
& '.\.venv\Scripts\python.exe' -m pytest tests -q --basetemp=output/test_tmp_02 -p no:cacheprovider
& '.\.venv\Scripts\python.exe' -m pip check
& '.\.venv\Scripts\python.exe' -m compileall -q techtrend main.py cron.py Attempt/scripts
git diff --check
```

prepare_data 重跑使用有校验和的成功响应，保留新编号派生结果；失败任务才重请求。prepare_graph 为每次执行保存 previous/extract/align 状态和 manifest，失败不进入下一阶段；数据库按事件 ID 幂等导入。重新采样需新配置/版本，不能覆盖 raw；代码单元测试与真实来源/数据库验证是不同层次，函数清单不等于全部行为都通过验证。

最终检查为 106 项测试通过、85 模块导入通过、475 项函数声明登记（function_inventory_02.json），pip check/compileall/Git 空白检查通过。两次真实图谱导入数量相同；metadata/graph_validation_00.json 记录事件时间范围 2016-01-01 至 2025-12-31，填入历史可得性日期的事件数为 0。Neo4j 对不存在的 available_at 属性提示警告，符合未知值不写入的策略；未把该警告当作已验证可得性。

## 阻塞、限制与后续优化

1. 本轮完成的是十年文献统计层和图谱种子。每层 20 条低于配置中研究扩展阶段的 100 条参考门槛；该门槛是可调整的数据准备参数，没有被声称为统计充分性结论。下一步按任务需要扩大采样或选取可管理的完整子集，并记录抽样概率和选择偏差。
2. Crossref 的年/月精度记录不丢弃：后续可用于相应粗粒度统计；不能自动补成 1 月 1 日或每月 1 日作为精确关系时间。
3. 专利时序引用原始文件尚缺；本机没有发现已配置的 USPTO API key，旧 PatentsView bulk 地址存在迁移问题。尚不能训练/评估专利引用增长目标。取得可访问 bulk 文件或本地配置免费来源凭证后，再验证 citing_date、CPC 映射、年份覆盖和解析器。
4. 需要处理历史当时可得性、后续参考文献/分类修订与实体对齐的历史前缀。现有数据是回溯快照，摘要明确 `historical_as_of_evaluation_ready=false` 和 `full_scale_forecasting_ready=false`；不把时间切分测试通过宣传为已消除全部泄漏。
5. 当前看板显示观察量与覆盖；三个正式预测目标、多年阶段权重和跨事件迁移仍需独立研究版本及真实回测，不使用 seed 的月度频次代替全量热度。
