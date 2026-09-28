# P0 脚手架 —— 实施计划

## Context（为什么做这件事）

仓库当前是全新空目录（仅一份 PROJECT_PLAN.md，无代码、无 git）。整个项目按分层架构推进（数据层 → 图谱层 → 预测层 → 编排层），P0 是第一阶段"脚手架"：

- **目标**：搭出目录结构、依赖、配置与统一日志，交付一个可运行的"空 pipeline"（各层只留接口桩）。
- **验收标准**（计划书原文）：`python main.py` 跑通。

P0 本身不写业务逻辑，但它决定了 P1–P6 的骨架：目录怎么分层、配置怎么读、日志怎么打、阶段怎么串起来。

### 已确认的三个决策

| 项 | 结论 |
|---|---|
| 依赖/工具链 | conda 环境建到 E 盘 + pip + requirements.txt（贴合已验证的完整路径工作流，不用 uv/poetry） |
| 配置管理 | pydantic-settings（类型安全、.env 自动加载、字段校验） |
| P0 范围 | 纯脚手架：目录 + 依赖 + 配置 + 日志 + 各层空桩 |

### 工具链决策依据

用户 conda,python环境.docx 已沉淀稳定工作流：conda 环境建在 `E:\conda_envs\<name>`、用完整路径 `E:\conda_envs\<name>\python.exe xxx.py` 运行、装包用 `...\python.exe -m pip install`。因此：

- 用 `conda create -p E:\conda_envs\techtrend python=3.12` 建环境；
- 全程完整路径运行，不依赖 `conda activate`；
- 依赖写在 requirements.txt（pip 原生）。

git…docx 的两条经验落实：① .env 等敏感文件进 .gitignore；② 建议 git init 起步。

---

## 目录结构

```
tech-trend-kg-agents/
├── main.py / cron.py          入口（CLI / 定时壳）
├── requirements.txt / .env.example / .gitignore / README.md
├── techtrend/
│   ├── __init__.py / config.py / logging_config.py / pipeline.py
│   └── stages/  base.py + collect/extract/build_graph/predict/report.py
├── data/ output/ logs/        运行时目录（gitignore 忽略）
```

## 阶段归属

| 阶段 | P0 | 实现阶段 |
|---|---|---|
| collect | 桩 | P1 数据层 |
| extract | 桩 | P1 LLM 抽取 |
| build_graph | 桩 | P1 Neo4j 写入 |
| predict | 桩 | P1 基线 / P3 TKG |
| report | 桩 | P6 报告 |

## 验证方式

```bash
conda create -p E:\conda_envs\techtrend python=3.12 -y
E:\conda_envs\techtrend\python.exe -m pip install -r requirements.txt
E:\conda_envs\techtrend\python.exe main.py   # 预期：打印 5 阶段桩日志，exit 0
E:\conda_envs\techtrend\python.exe cron.py   # 与 main.py 等价
```
