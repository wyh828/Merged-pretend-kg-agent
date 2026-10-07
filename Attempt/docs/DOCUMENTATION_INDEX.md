# 简明操作指南

适用项目：`F:\Predictive agents`。更新日期：2026-10-07。
目前可以准备数据、检查数据、写入图谱和查看看板；正式全量预测还需要扩大样本、补齐专利时序引用并验证历史信息可得性。

## 1. 打开项目

打开 PowerShell，先执行这两行。后续命令在同一个窗口运行；`$py` 代表本项目已配置的 Python。

```powershell
Set-Location 'F:\Predictive agents'
$py = '.\.venv\Scripts\python.exe'
```

环境已配置好，日常使用从这里开始。

## 2. 查看或更新看板

查看已有结果：

```powershell
Invoke-Item '.\output\runs\research_01\dashboard.html'
```

数据整理后，更新看板：

```powershell
& $py main.py --stage visualize
```

看板展示学科统计、数据覆盖和分析文档；只有查看看板时，无需启动数据库。

## 3. 继续准备数据

按顺序逐条运行，上一条成功后再运行下一条。可执行 `$LASTEXITCODE` 查看退出码：`0` 表示成功，非 `0` 时先处理报错。

| 顺序 | 操作 | 命令 | 成功后得到什么 |
|---|---|---|---|
| 1 | 准备数据 | `& $py Attempt/scripts/prepare_data_02.py` | 原始响应、文献记录、月度覆盖统计；成功响应可复用 |
| 2 | 检查数据 | `& $py Attempt/scripts/verify_data_02.py` | 输出 `status: passed`，保存检查记录 |
| 3 | 抽取、对齐并入库 | `& $py Attempt/scripts/prepare_graph_02.py --load-database` | 各阶段输出 `status: ok`，保存过程和图谱 |
| 4 | 更新看板 | `& $py main.py --stage visualize` | 更新 `dashboard.html` |

第 3 步需要 Neo4j；电脑重启后先执行下面的数据库启动步骤。当前历史窗口是 **2016–2025 年、26 学科**，每学科每年 20 条随机文献种子；固定样本数不能代表真实热度，看板使用独立 API 汇总量。

## 4. 重启电脑后启动数据库

```powershell
docker desktop start
docker compose --env-file .env -f Attempt/env/compose_01.yaml up -d neo4j
& $py Attempt/scripts/verify_database_01.py
```

等 Docker Desktop 启动完成再执行下一行。数据库检查中的 `connectivity`、`event_history` 和 `idempotence` 应为 `passed`。需要查看图谱时，用浏览器打开 `http://127.0.0.1:7474`，连接地址为 `bolt://127.0.0.1:7687`；用户名和密码使用项目根目录 `.env` 中的配置。

## 5. 文件在哪里、遇到问题怎么办

| 内容 | 本机位置 |
|---|---|
| 看板 | `F:\Predictive agents\output\runs\research_01\dashboard.html` |
| 新数据和检查记录 | `F:\Predictive agents\Data\Datasets\technology_trends_01` 下的 `raw`、`interim`、`processed`、`metadata` |
| 运行日志 | `F:\Predictive agents\logs` |
| 路径、日期、密码与 API Key | `F:\Predictive agents\.env`；格式参考根目录 `.env.example` |
| 采样数量、请求上限 | `F:\Predictive agents\Attempt\configs\data_preparation_02.yaml` |

遇到缺少 Python 包的报错，先确认使用第 1 步的 `$py`；数据库连接失败，先完成第 4 步；API 限流或访问失败，按日志处理后重跑第 3 节的数据准备命令，已有成功响应会保留。

代码修改后的检查命令：

```powershell
& $py -m pytest tests -q --basetemp=output/test_tmp_03 -p no:cacheprovider
```

查看容易识别的版本说明：

```powershell
git log -5 --format='%s'
```

数据准备版本的中文说明为“完成十年跨学科数据准备与图谱入库”。Git 的字母数字编号是自动生成的版本标识。

详细记录：[项目进展](../../README.md) · [数据准备与限制](data_preparation_02.md) · [研究方向](research_direction_01.md)。

## 共享数据

想给别人看成果，先发 C 看板；想继续实验，再发 A 数据和 B 图谱。具体操作见 [共享指南](sharing_00.md)。目前附件还在准备，发布状态见 [共享安排](sharing_plan_00.md)。
