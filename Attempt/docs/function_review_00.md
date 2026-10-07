# Function Review 00

## Review scope

阅读项目源代码、入口/阶段调用关系、配置、上下游数据文件，以及 PROJECT_PLAN、COMPARISON_REPORT、MERGE_PLAN、REPORT_OUTLINE。逐模块接口记录见 `function_inventory_00.json`：包含文件、行号、函数/方法名、参数、返回注解、职责摘要和静态调用。

静态清单包含 448 项声明；81 个模块通过导入。AST 与导入检查不能替代业务行为检查；未在专项测试覆盖的函数仍需真实或合成数据验证。每一项下表修复均运行专项检查，通过后推进下一项。

## Completed gates

| Function / contract | Reproduced problem | Focused validation |
|---|---|---|
| Settings.resolve_local_paths / signal.load_pipeline_config | 相对路径随启动目录变化 | test_local_paths.py |
| main.run_full | evaluate 返回 error 但进程退出 0 | test_cli_status.py |
| get_default_stages / run_daily | 全量 report 在 evaluate 前，每日漏掉 collaborate | test_stage_order.py |
| run_daily review gate | 人工拒绝后仍报告/推送 | test_stage_order.py |
| SourceCollector protocol | collect 定义错误缩进到 registry 函数内 | test_collector_contract.py |
| UsptoCollector.collect | headers 与 PoliteApiClient.extra_headers 参数不一致 | test_uspto_interface.py，两种模式，无网络 |
| CollectStage.run | 部分源失败/未知源却总返回 ok | test_collect_status.py |
| _parse_json / LLMExtractor validation | 非对象 JSON、异常元素/字段类型导致崩溃 | test_llm_validation.py，无模型调用 |
| line_chart | 最后折缺失导致 Y(None) 崩溃；缺失点被直接连线 | test_svg_missing_data.py，SVG XML 解析 |
| VisualizeStage / dashboard.render | 缺指标仍判断模型优劣，文档与看板分离 | test_dashboard_integration.py，转义与空状态 |
| build_patent_citation_monthly | 空分层样本 min() 崩溃，排序前 ffill 导致累积曲线错误 | test_citation_matrix.py |
| configure_model_storage / run_rotate | 依赖缓存写入用户目录而报权限错误 | test_model_storage.py；小样本 CPU 实际训练 |
| ndcg_at_k | 原指数增益在活动量 2000 时 OverflowError | test_ndcg_numeric.py，同尺度消除，保持原公式 |
| ReportStage.run / _render_four_goals | 有评估但无旧 baseline 时不生成报告；缺对照仍判断输赢 | test_report_availability.py |
| _write_raw | 同源同日同 tag 会覆盖原始快照 | test_raw_snapshots.py，独立编号、排他创建 |
| short_id / extract_triples / build_nodes / align_entities | Crossref DOI 后缀碰撞、错误来源标记、DOI URL 与文本不能匹配 | test_crossref_identity.py |

USPTO 测试首次使用 start=end，按项目「end 月排除」定义产生 0 个窗口；修正测试区间为 2024-01 到 2024-02 后两种模式通过，并非更改采集窗口语义。模型缓存检查第二次在项目 Data 目录遇到沙箱 ACL 阻塞，获批在工程内建缓存后真实训练成功。

## Pending research-method review

以下问题先记录，不修改历史实验口径，也不宣称已解决：

1. metrics.spearman_rho 未按并列值赋平均秩，常量输入可能得到虚假的完全相关。
2. metrics.top1_lift 文档写全池均值，代码取 ranked 列表均值；若只传 Top-K，口径不同。
3. regression.run_regression / evaluation：全时段 Top-N 选实体、训练标签跨测试边界、基线近期均值可能包含测试信息；需按折单独复核。
4. temporal 图投影：全时段实体度数/支持度筛选可能把未来信息带入训练选择。leak_check 只验证事实时间边界，不能证明前处理无泄漏。
5. citation 时序仅包含出现事件的时间箱；是否补齐完整日历会改变回归/生命周期口径。

拟修改范围：prediction/metrics.py、regression.py、evaluation.py、temporal.py、stages/evaluate.py，以及对应反例测试和新版本实验说明。修订结果应输出独立 `_01` 版本，原结果不覆盖。需要用户复核后执行。

## Remaining engineering audit

Crossref 作者字段没有强 ID，仍需补全作者实体；TLogic 候选评分规则键与挖掘标签可能不一致；link_agent_scores 的边源/已有产物需检查；重复预测实验输出仍可能覆盖，需要保存独立实验版本后再运行。采集器部分业务缺少数据/API 时返回 0（而非明确不可用），需在外部服务联调阶段验证。

外部集成尚未验证：Neo4j 写入、各真实 API、LLM 抽取与研报、通知/定时、云备份。默认关闭调度和通知。完整运行尚未完成，任何上游历史数字都不算本机复现结果。
