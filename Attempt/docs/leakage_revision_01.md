# Leakage Revision 01

## 目标、授权与范围

基于本地 `codex/merged-local-00`；本轮前的检查点为 `codex/checkpoint-before-leak-fix-01`，对应上一修订提交 `c229928`。用户明确优先修复时间泄漏，并要求先整理代码、算法、环境和数据库，之后重新采集。没有迁入旧研究数据，没有调用研究数据 API、付费 LLM、通知或定时任务。

代码仍保留采集、存储、抽取、对齐、建图、预测、验证、协同、报告、看板的十阶段结构。新增工具只处理日历、快照与溯源，不引入新 Python 依赖。Neo4j 为独立 Docker 实例；旧容器不作迁移。

## 逐项检查闸门

| 函数/模块 | 修订的问题与行为 | 专项检查 |
|---|---|---|
| regression.run_regression / evaluation._regression_fold | 全史 Top-N 和跨留出边界标签泄漏；选样仅训练前缀，标签完整结束后才能使用；近期均值只取预测前 | test_regression_causality.py |
| temporal.fit_graph_scope / apply_graph_scope + EvaluateStage | 支持度/度数筛选曾先看全图；每折仅训练事实拟合，测试保留已知实体的新关系对，不按训练旧关系对剔除 | test_graph_causality.py |
| PredictStage / collab.link_agent_scores | 融合和协同链接分读取了更晚事实/旧缓存；统一历史预测起点，缓存绑定事实与模型参数摘要；无新分也更新为空缓存 | test_predict_causality.py |
| signal.concept_share_momentum / Kleinberg | 未来才出现的零历史实体改变分母/排名候选；历史前缀活跃对象才参与拟合 | test_ranking_causality.py |
| metrics + fusion + cross_examine | Spearman 并列秩、常量相关、Top-1 Lift 总池均值、并列名次和缺路权重口径不一致 | test_metric_protocol_01.py，Spearman 与 scipy 对照 |
| calendar_bins + 两类月度矩阵 | 六个事件月被误当六个日历月；连续日历补齐，覆盖缺失单列说明 | test_calendar_citation_causality.py |
| 引用转换、采集和 EvaluateStage | 缺引用日曾回填被引专利发表日；采集/回测按未来总量选样；改为准确事件日期、保留窗口事实、逐折选择；全史分层仅用于描述性 S 曲线 | test_calendar_citation_causality.py / test_citation_collection_01.py |
| Neo4jClient / ExtractStage / temporal.project_t2t | 同关系不同日期事件被覆盖/去重；增加事件 ID 和证据来源，保留不同时间/来源/版本；后来文档修订不能挂到更早事件 | test_graph_event_storage.py / test_event_provenance_01.py + 实际数据库检查 |
| EvaluateStage / leak_check | 空折、无真值或零成功折不能报告验证成功；缺专利文件覆盖旧成功 JSON，边界检查空集返回 None | test_evaluation_availability_01.py |
| Pipeline / run_daily | 前置阶段失败后仍运行下游并可能发布旧结果；失败后停止下游，记录状态 | test_evaluation_availability_01.py / test_stage_order.py |
| _write_raw / storage | 新快照编号、来源查询/观测时间/校验值 sidecar；CLI/全量/每日运行前保留报告副本 | test_raw_snapshots.py / test_storage_provenance_01.py |
| tlogic.score_candidates | 挖掘标签与查询标签不匹配导致零分、对称性方向错误、两跳第一条边可来自未来；匹配实际规则、按入边预测反向、两条边均早于查询 | test_tlogic_causality_01.py |

修复一个接口后运行该项测试，测试通过才进入下一项；最后跑全套。反例会改变未来量/追加未来独有对象，并验证过去训练样本、候选范围、图筛选或规则分数保持不变。测试没有宣称覆盖所有函数的真实行为。

## 新存储位置

所有地址以 `F:/Predictive agents` 为根；本机 `.env` 已切换：

```
Data/Datasets/technology_trends_01/
  raw/                 分源/采集日/编号的归一化快照与 metadata sidecar
  interim/             当前结构化记录、抽取图、对齐审计和引用事实
  processed/           后续分版本的派生特征（尚无研究数据）
  metadata/            覆盖/清单/来源记录（尚无研究数据）
  cache/               PyKEEN / PyStow / Torch / Hugging Face 缓存
Data/Database/neo4j_01/ 专用图数据库持久卷
output/runs/research_01/ 本轮当前报告和看板；重跑前复制到 history/artifacts_00、_01…
output/validation_01/   独立合成验证，不能当研究数据
logs/neo4j_01/          数据库日志
```

快照 metadata 记录 source_url、query、collected_at、dataset_version、rows、sha256、schema_version；historical_available_at/license/coverage 未知时保持未知。现有普通 API raw 快照实为归一化记录，original_payload_preserved=false。后续补原文存储后才能改为 true。collected_at/recorded_at 不等于历史公开可得时间。

新数据目录最初因沙箱继承权限缺失无法写入，已仅为新版本目录补充工程内写权限，旧数据不改权限。正常沙箱对新目录实际写入/删除自建探针已通过。

## Neo4j 管理

查过本机程序、注册表、进程与服务，没有查到现有 Neo4j 或 Java 图库；Docker Desktop 已安装但未运行。启动 Docker 后，两个既有容器 opengauss、og_manager 保持原状态。新增 predictive-agents-neo4j-01，Neo4j 5.26.31：

- 浏览器：`http://127.0.0.1:7474`；Bolt：`bolt://127.0.0.1:7687`；只映射本机回环端口。
- 镜像摘要：`neo4j@sha256:d9cfe82983d27f5a75b3aaae8f316d04f9a698a3b7f6103a508f7caf8362f255`，已写入本地 `.env`。
- 新生成的密码仅在忽略的 `.env` / `Attempt/env/neo4j_auth.local`，未写进 Git 或聊天。
- compose 文件 `Attempt/env/compose_01.yaml`；堆/页缓存各 512 MB，总上限 2 GB、2 CPU，重启策略 no；匿名 usage report 已关闭。
- 数据卷和日志位于工程目录；启动不删除旧约束，旧库迁移不自动执行。

实际验证成功：连通、建约束、同一对节点两日期事件均保留、重复写入仍为两事件、未提供 available_at 时不伪造、清理本次唯一测试 ID。当前研究节点数为 0。结果见 output/validation_01/database_check_01.json / database_check_02.json。

参考：[Neo4j Docker 官方说明](https://neo4j.com/docs/operations-manual/current/docker/introduction/)、[Docker Desktop start](https://docs.docker.com/reference/cli/docker/desktop/start/)。

## 可复查命令与结果

```powershell
Set-Location 'F:\Predictive agents'
& '.\.venv\Scripts\python.exe' -m pytest tests -q --basetemp=output/test_tmp_01 -p no:cacheprovider
& '.\.venv\Scripts\python.exe' -m pip check
& '.\.venv\Scripts\python.exe' -m compileall -q techtrend main.py cron.py Attempt/scripts
& '.\.venv\Scripts\python.exe' Attempt/scripts/verify_database_01.py
& '.\.venv\Scripts\python.exe' Attempt/scripts/verify_causality_01.py
# Docker 在电脑重启后需要手动启动；保留现有数据卷：
docker desktop start
docker compose --env-file .env -f Attempt/env/compose_01.yaml up -d neo4j
```

合成流程：2020-01 到 2024-12，60 个日历月、240 条人为生成记录，固定模型 seed、CPU；抽取→对齐→回测→协同→报告→看板均成功。TKG 一折实际训练 CyGNet 和 RotatE；活动量和排名各一折。没有专利真数据，该目标显示缺失；不使用合成指标支持算法优越性或实际预测质量。

结果摘要 output/validation_01/causal_workflow_00/verification_summary_01.json；报告和看板在该目录 reports。验证脚本重复运行自动创建下一个目录，旧结果不覆盖。依赖版本沿用 local_environment_00.txt，无新增 pip 依赖。

执行提示：CPU 无 CUDA、PyKEEN 保守 batch size、Windows 缺 wmic 时 joblib 回退到逻辑核心数；均未造成本次合成流程失败。首次完整检查在本地显式 CACHE_DIR 下有一个路径测试失败，确认是环境覆盖影响测试假设；删除冗余 CACHE_DIR，让缓存随 DATA_DIR 默认规则解析后通过。

最终全套测试、静态导入、看板及 Git 结果在根 README 本轮记录。AST 函数清单 function_inventory_01.json 为本轮全量接口快照，清单不等于 460 个接口均完成业务验证。

## 不能宣称已解决的边界

1. 今天下载的历史记录可能包含后来的引用数、概念分类/别名，以及 LLM 的后见知识。没有历史版本和 available_at，event_time 回测不是严格历史信息可得性验证。leak_ok 仅代表有非空折的事实时间边界。
2. 实体对齐尚未逐折拟合/保存历史映射；需先补可追溯原始字段与版本，再验证真实历史回测。静态随机 RotatE 指标仅作结构基线，不当未来预测成绩。
3. 跨领域统一注册与采集覆盖尚未完成；部分增量游标、默认高被引/高 star 截断、真实服务接口仍需下一闸门。无法把 88 个单元测试当作全源联网联调成功。
4. 全量引用矩阵仍在内存构建，免费全领域多年数据要按年月分批/派生聚合；禁止靠未来总被引 Top-N 控内存而产生新的选样泄漏。
5. 多年阶段权重、递归类比与迁移尚处设计阶段；详见 research_direction_01.md。

本机修订与合成验证成立；真实新数据全量预测尚未完成。下一步按方向说明逐项推进，不把旧实验数字与新协议混合。
