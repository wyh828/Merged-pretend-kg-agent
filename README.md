# Predictive Agents：技术趋势预测研究

项目根目录：`F:\Predictive agents`。使用论文等多源数据构建时序知识图谱，研究热度增长、新技术关联、专利引用增长；长期记忆与阶段权重迁移仍处于设计阶段。

## 从哪里开始

| 目的 | 入口 |
|---|---|
| 日常运行、启动数据库、查看看板 | [简明操作指南](Attempt/docs/DOCUMENTATION_INDEX.md) |
| 了解当前数据、来源与限制 | [数据准备记录](Attempt/docs/data_preparation_02.md) |
| 查看共享包准备与发布状态 | [共享方案与进度](Attempt/docs/sharing_plan_00.md) |
| 理解研究方向 | [研究方向](Attempt/docs/research_direction_01.md) |
| 查看完整设计 | [项目计划](Resources/plans/PROJECT_PLAN.md) · [技术路线](Resources/plans/TECH_ROADMAP.md) |
| 查看两项目合并与汇报材料 | [合并计划](Resources/plans/MERGE_PLAN.md) · [对比分析](Resources/reports/COMPARISON_REPORT.md) · [汇报大纲](Resources/reports/REPORT_OUTLINE.md) |
| 查阅早期阶段与旧结果 | [阶段计划目录](Resources/plans/) · [历史报告目录](Resources/reports/) · [整理前进展记录](Resources/reports/project_history_00.md) |

## 当前已验证到哪一步

2016–2025 年、26 学科，OpenAlex/Crossref 各覆盖 120 个月；保留 511 份原始响应，5,375 条去重文献，425 条粗日期隔离记录。此前真实入库检查为 **53,687 个实体、62,093 条事件关系**，实体数包含参考文献占位、作者、机构和主题。

这些是数据准备与图谱种子结果。**正式全量预测尚未完成**：当前每学科每年仅 20 条随机种子，专利时序引用缺失，历史分类与引用当时可得性尚未验证。两个来源有重叠，统计量不能相加；固定样本数量不能代表真实热度。上游文档数字作为历史记录保留。

本机已有 Python 3.13.9 的 `.venv`；密码和 API Key 放在忽略的本地 `.env`。看板位于 `output/runs/research_01/dashboard.html`，可离线打开。

```powershell
Set-Location 'F:\Predictive agents'
Invoke-Item '.\output\runs\research_01\dashboard.html'
```

完整流程：`collect → extract → align → build_graph → predict → evaluate → collaborate → report → notify → visualize`。按操作指南逐步检查，前一步失败先修复。

## 文件在哪里

| 目录 | 内容 |
|---|---|
| `Resources/plans/` | 总计划、技术路线、合并方案、P0–P6 阶段计划 |
| `Resources/reports/` | 对比分析、汇报大纲、历史结果 |
| `Attempt/` | 配置、环境、脚本、函数清单、操作和修订记录 |
| `techtrend/`、`tests/` | 现有源代码与检查用例 |
| `Data/Datasets/technology_trends_01/` | 原始响应、整理数据、统计和来源审计 |
| `Data/Database/neo4j_01/` | Docker Neo4j 挂载的持久数据库文件 |
| `Data/Exports/` | 版本化共享包，本地生成后作为 Release 附件发布 |
| `output/runs/research_01/` | 当前看板和生成报告 |

## 上传和共享

本项目使用本机 **LisaZhao0709** 账号，更新目标为 [项目仓库](https://github.com/wyh828/Merged-pretend-kg-agent)。原有 fork 保留，本次使用原仓库远端上传独立审核分支。

A 数据文件、B 图谱备份、C 看板与统计结果计划作为同一版本的三个下载附件。**当前附件尚未生成或发布**；完成验证后，此处补充各自的准确下载链接。

## 最新阶段记录（2026-10-07）

| 阶段 | 阻塞/问题 | 成果与检查 | 后续优化/下一步 |
|---|---|---|---|
| 上传账号 | 原仓库权限已开放 | 本机 LisaZhao0709 身份和原仓库写权限核对通过；整理前检查点 `codex/checkpoint-before-sharing-00` | 代码版本与共享附件绑定到同一提交 |
| 文档组织 | 根目录 19 个 MD 混合设计、历史和操作；看板读取旧路径 | 17 个文档分类迁移，原 README 完整内容单独归档；111 个文档链接有效，看板专项检查通过 | 检查通过后再进行数据导出 |
| 数据包 A | 原路径绑定本机，需保留来源与许可 | 待生成；原始数据保留 | 相对路径、逐文件校验、解压后检查 |
| 图谱包 B | 需要匹配 Neo4j 版本与离线导出 | 待导出；Docker Desktop 的通信 socket 报错，备份重建后仍复现 | 在独立空目录恢复，比较实体和事件数 |
| 看板包 C | 必须继续区分观察统计和未验证预测 | 待生成 | 离线看板与统计表核对 |

此前修订 02 检查为 106 项测试通过、85 模块导入通过；详见 [数据准备记录](Attempt/docs/data_preparation_02.md)。本轮最终全套 116 项测试通过，最终修改专项 15 项通过；86 个模块导入通过，484 个函数记录于新清单，111 个本地文档链接有效。详见 [本次提交说明](Attempt/docs/submission_review_00.md)。共享附件还未完成真实导出与恢复验证。

本轮代码已上传 [审核 PR #1](https://github.com/wyh828/Merged-pretend-kg-agent/pull/1)，本地分支为 `codex/local-sharing-00`。Docker 故障记录见 [启动问题记录](Attempt/docs/docker_recovery_00.md)，A/B/C 附件暂未发布。
