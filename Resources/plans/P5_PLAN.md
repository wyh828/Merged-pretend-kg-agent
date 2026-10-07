> 本机适配说明：工程路径已改为 `F:/Predictive agents`；以下阶段设计与实验数字仍为上游历史记录。本机执行结果见 README 的「本机修订 00」。

> 本文保留上游设计和历史结果，未经本机复现；当前进展和本机验证见 [项目入口](../../README.md)。

# P5 hermes-agent 自动化 —— 完整构建计划

> 本文档承接 [PROJECT_PLAN.md](PROJECT_PLAN.md) §六「hermes-agent 编排层」、§七「分阶段路线图」P5 行，以及文末
> 「后置优化/待决策登记」#20（每日增量累积时序深度）、#19（重跑 extract 补近期定向对）。
> 也承接 [P4_P3_METRIC_OPT_PLAN.md](P4_P3_METRIC_OPT_PLAN.md) 的 **P0-3（启动每日增量，P5 cron）** —— 那是本阶段要落地的数据侧目标。
> 现状代码见 [cron.py](../../cron.py)（P0 空壳）、[main.py](../../main.py)（P4 七阶段 CLI）、[stages/__init__.py](../../techtrend/stages/__init__.py)。

---

## 0. 一页速览

| 维度 | 内容 |
|---|---|
| 目标 | 让「采集→抽取→对齐→建图→预测→报告」每日无人值守自动跑通，并**逐日累积时序深度**（CyGNet copy 的燃料） |
| 双轨调度 | **hermes-agent cron 主选** + **APScheduler 降级**；入口统一 `cron.py`，换调度器不动业务代码 |
| 多智能体 | 角色化 agent（采集/抽取/分析/预测集成/审校/报告）= 编排层叙事，**角色定义作数据**（单一事实来源），降级时同一 runbook 串行执行但保留角色标注 |
| 关键新增 | `orchestration/` 包（roles/runbook/notify/scheduler）+ `cron.py` daily 模式 + `NotifyStage`（第 8 阶段）+ HITL 审校开关 + `run_manifest.jsonl` |
| 验收 | ① 每日无人值守跑通（exit 0 + 日志 + manifest）② 连续 3 天增量不重复、时序深度递增 ③ 关掉 hermes-agent 用 `cron.py` 直接跑底层独立性 ④ 报告推送到至少一个渠道 |

---

## 1. Context（为什么做 / 承上启下）

**P0–P4 已把「采集 → 图谱 → 预测 → 验证」四层做齐**（见 PROJECT_PLAN §七「阶段成果记录」），但整条链路仍需人手动敲 `python main.py`。
P5 要把它变成**每日无人值守**的自动化系统，并顺带解决一个更根本的算法问题——**数据时序深度**。

**为什么 P5 同时是「编排」和「数据」两件事**：P3.5/P4 已把目标②（链接预测）的卡点锁定为「CyGNet 靠复制历史，但定向图 86.5% 的测试是新链接，copy 无史可复」（见 [P3_OPT_P4_RESULT.md](../reports/P3_OPT_P4_RESULT.md)）。
共现图上 copy 已占优——walk-forward 下 CyGNet **0.9459** vs RotatE **0.4487**（共现图高复现、copy 天然占优，非算法更强）；每日增量跑 collect→extract→align，让 `(s,r)` 跨时间重复，**巩固**这一优势并逐步拉长时序深度。
因此 P5 的每日 cron 不是「把现在的手动流程包一层定时器」那么简单，它本身就是 A2 达标的时间杠杆（PROJECT_PLAN #20）。

**编排层的硬约束（承 TECH_ROADMAP §6 / 审查要点 #3/#9）**：
1. **底层与 hermes-agent 解耦**：调度器只负责「定时触发 `cron.py`」，业务代码不知道是谁在调度它。hermes-agent 不稳定时可无损降级 APScheduler。
2. **多智能体发生在编排层，非底层 pipeline**：底层是 7 阶段串行（collect/extract/align/build_graph/predict/report/evaluate），多智能体协作是 hermes-agent 顶层的角色化委派（课题贡献点，需自行设计而非只用内置委派）。
3. **「每日无人值守」不等于「每天全量重跑」**：collect 已按 id 幂等 + cursor 增量（[collect.py](../../techtrend/stages/collect.py) `_append_dedup`），但 extract 是整表重算（幂等正确、成本随数据量线性增长）。P5 需一个「0 新增则短路」的守卫，避免空跑烧 LLM/CPU。

---

## 2. 关键决策

| # | 决策 | 结论 | 依据 |
|---|---|---|---|
| 1 | 调度双轨 | **hermes-agent cron 主选 + APScheduler 降级**；两者都只调 `cron.py`，入口与参数完全一致 | PROJECT_PLAN §六 / 风险表「hermes-agent 迭代快不稳定」 |
| 2 | 角色层 = 数据 | 6 个角色定义放在 `orchestration/roles.py` 作**单一事实来源**，hermes-agent 的 agent/skill 与降级层的 runbook 都从它生成 | 避免「两套角色定义各写一遍」漂移 |
| 3 | 多智能体叙事 | 角色化 agent 是编排层概念；降级时同一 runbook 串行执行、但**每一步仍打角色标签 + 独立 summary**，保留「多智能体协同」的可交付证据 | TECH_ROADMAP 审查要点 #9 |
| 4 | 每日增量模式 | `cron.py --mode daily`（增量，默认）+ `--mode full`（手动全量）；daily 下 collect 全源 0 新增则**短路下游**并写 no-op stamp | #20；避免空跑 |
| 5 | notify 独立第 8 阶段 | `NotifyStage` 追加在 `evaluate` 之后，`notify_enable` 默认 **false**（手动 `main.py` 不推送，cron 才推） | 手动跑不打扰、无人值守才推送 |
| 6 | HITL 审校开关 | `review_enable_hitl` 默认 false、`review_auto_approve` 默认 true（保无人值守）；交互演示时关掉 auto | PROJECT_PLAN §6.2 审校 agent |
| 7 | 无人值守观测 | `output/run_manifest.jsonl` 每次运行追加一条（run_id/时间/各阶段状态/各源新增数），替代 git 记录 | 无人值守只能靠日志+manifest 确认 |
| 8 | 验收口径 | ①每日无人值守跑通 ②连续 3 天增量不重复、时序深度递增（#20）③底层独立性 ④推送至少一渠道 | PROJECT_PLAN P5 行 + P4_P3 P0-3 |

> **不做的**（诚实边界）：hermes-agent 是快速迭代的外部框架，其 cronjob/skill/agent 的**精确 YAML schema 以安装版本为准**，
> P5 交付「语义内容 + 接线点」，schema 细节在实现期对着本机安装的 hermes-agent 版本核对，不照抄本文示例字段名。

---

## 3. 目录结构（P5 新增/改动）

```
techtrend/
  orchestration/                # 新包：编排层（调度器无关）
    __init__.py
    roles.py                    # 新：6 角色定义（单一事实来源）
    runbook.py                  # 新：每日运行手册（角色→阶段→短路/依赖→manifest）
    notify.py                   # 新：报告推送（Telegram/Discord/file）
    scheduler.py                # 新：APScheduler 降级调度（python -m 入口）
  stages/
    notify_stage.py             # 新：NotifyStage（第 8 阶段）
    __init__.py                 # 改：注册 NotifyStage
  config.py                     # 改：+ P5 编排/推送/HITL 参数段
cron.py                         # 改：+ --mode daily|full / --notify / --dry-run / --auto-approve
.env.example                    # 改：+ P5 段
requirements.txt                # 改：apscheduler 解注释（降级依赖）

hermes/                         # 新：hermes-agent 侧（thin adapter，语义内容，schema 以安装版本为准）
  skills/
    techtrend-daily/SKILL.md    # 新：每日运行主技能（agentskills.io 标准）
    roles/SKILL.md              # 新：6 角色各自职责 + 委派说明（可一文件分节）
  config/
    cronjobs.example.yaml       # 新：cronjob 定时定义示例
    agents.example.yaml         # 新：角色 agent 定义示例
```

---

## 4. 数据流（每日运行）

```
[调度层]  hermes-agent cronjob  ──或──  APScheduler(scheduler.py)
                       │  都只触发 ↓（同一入口、同一参数）
              cron.py --mode daily
                       │
                       ▼
        runbook.run_daily(settings)                     ← 新：编排核心
        ├─ role: collector   → CollectStage.run()        # 增量，各源 cursor + id 去重
        │      └─ 记录 per-source new_records（0 新增判定）
        ├─ 守卫：若所有源 new==0 → 写 no-op stamp，短路下游，直接 report+notify
        ├─ role: extractor   → ExtractStage.run()        # 全量重算 triples/nodes（幂等正确）
        │        + AlignStage.run() + BuildGraphStage.run()
        ├─ role: analyst     → PredictStage.run()        # burst/tkg/forecast/fusion（可并行子任务）
        │        + EvaluateStage.run()
        ├─ role: reviewer    → HITL checkpoint           # 仅 review_enable_hitl 且非 auto 时暂停
        ├─ role: reporter    → ReportStage.run() + NotifyStage.run()
        └─ run_manifest.jsonl 追加一条（无论成败）
```

**关键点**：
- **collect 已是增量幂等**（[collect.py](../../techtrend/stages/collect.py) 各源 `_read_cursor` + `_append_dedup`），daily 模式每天跑 collect 只会**追加新数据**，`works.jsonl/arxiv.jsonl/...` 逐日增长 → 这就是 #20「时序深度累积」。
- **extract 是整表重算**（[extract.py](../../techtrend/stages/extract.py) `write_jsonl` 覆盖 triples.jsonl），每次从**已增长的** interim 重导出 → 时态跨度逐日拉长，无需新代码。
- **短路守卫**避免「0 新增却全量重算烧 LLM 预算」（`llm_max_docs_per_run` 每次都会重新花一遍）。

---

## 5. 配置扩展（config.py + .env.example）

```python
# ---- 编排与自动化（P5）----
# 双轨调度：hermes-agent cron（主）/ APScheduler（降级），入口统一 cron.py
schedule_enable: bool = False            # 启用内置 APScheduler 调度（hermes-agent 接管时关）
schedule_cron: str = "0 3 * * *"         # 每日 03:00 本地（避免整点；见 PROJECT_PLAN 调度避峰惯例）
schedule_timezone: str = "Asia/Shanghai"

# 每日运行（runbook）
daily_mode: str = "incremental"          # incremental(增量,默认) | full(全量)
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
review_auto_approve: bool = True         # 无人值守自动通过；False = 等待 review_approve.json / stdin
```

> `.env.example` 对应补 `SCHEDULE_ENABLE/SCHEDULE_CRON/NOTIFY_*`/`REVIEW_*` 段（全部默认关，无 key 也跑通）。

---

## 6. 各模块详细设计

### 6.1 orchestration/roles.py（新）—— 角色单一事实来源

```python
@dataclass(frozen=True)
class Role:
    name: str
    desc: str
    stages: tuple[str, ...]          # 负责的底层阶段名
    runs_after: tuple[str, ...] = () # 角色级依赖
    needs_llm: bool = False
    parallel_subtasks: tuple[str, ...] = ()  # 可并行的子任务（分析 agent 的 burst/tkg/forecast）
    human_checkpoint: bool = False

ROLES: tuple[Role, ...] = (
    Role("collector",  "采集 agent：调度/监控各源每日增量",
         stages=("collect",)),
    Role("extractor",  "抽取 agent：LLM 抽实体/关系并写入 Neo4j",
         stages=("extract", "align", "build_graph"), runs_after=("collector",), needs_llm=True),
    Role("analyst",    "分析 agent：突发/时序外推/回归（可并行）",
         stages=("predict",), runs_after=("extractor",),
         parallel_subtasks=("burst", "tkg", "forecast")),
    Role("integrator", "预测/集成 agent：融合多路信号 + 回测校验",
         stages=("predict", "evaluate"), runs_after=("analyst",)),
    Role("reviewer",   "审校 agent：报告前暂停人工确认（HITL）",
         stages=(), runs_after=("integrator",), human_checkpoint=True),
    Role("reporter",   "报告 agent：生成日/周报告 + 推送",
         stages=("report", "notify"), runs_after=("reviewer",)),
)
```

> 设计要点：`parallel_subtasks` 对应 [stages/predict.py](../../techtrend/stages/predict.py) 里 P3 已隔离的 `_run_burst/_run_tkg/_run_forecast/_run_fusion`
> 四个子任务（各自 try/except 不互阻）——这就是「分析 agent 可并行多个」在底层已存在的并行化接缝，hermes-agent 可沿它 fan-out。

### 6.2 orchestration/runbook.py（新）—— 每日运行手册

```python
def run_daily(settings) -> dict:
    """执行一次每日运行。返回 run manifest dict。
    1) collector：CollectStage.run() → per-source new_records
    2) 守卫：daily_skip_if_no_new 且全源 new==0 → 写 no-op stamp，跳下游，直接 report+notify
    3) extractor/analyst/integrator：按 roles.py 顺序跑对应 stage
    4) reviewer：review_enable_hitl 且非 auto → 等 review_approve.json 或 stdin
    5) reporter：ReportStage + NotifyStage
    6) manifest 追加 run_manifest.jsonl（含 run_id/起止时间/各阶段 status/各源新增数）"""
```

**manifest 结构**（无人值守观测，逐次追加一行）：

```json
{"run_id":"20260923T030001","started_at":"...","finished_at":"...","mode":"daily",
 "status":"ok","new_records":{"openalex":12,"arxiv":30,"uspto":0,"gdelt":18,"github":5,"rsshub":4},
 "stages":{"collect":"ok","extract":"ok","align":"ok","build_graph":"ok",
           "predict":"ok","evaluate":"ok","report":"ok","notify":"ok"},
 "noop":false}
```

### 6.3 orchestration/notify.py（新）+ stages/notify_stage.py（新）—— 报告推送

```python
# notify.py
def push_report(settings, report_text: str, channels: list[str]) -> dict:
    """按 notify_channels 推送到 file/telegram/discord；任一渠道失败仅记 warning 不阻断。
    - file：写 output/notify_latest.md（兜底，永远成功）
    - telegram：POST https://api.telegram.org/bot<token>/sendMessage（chat_id + text，httpx）
    - discord：POST <webhook>（{"content": ...}，httpx）
    注意本机 Clash 代理：外网推送需 trust_env=True（走代理），与 RSSHub 本地请求 trust_env=False 相反。"""

# notify_stage.py
class NotifyStage(Stage):
    name = "notify"
    def run(self) -> dict:
        if not self.settings.notify_enable:
            return {"stage": self.name, "status": "ok", "skipped": True}
        # 读 output/<notify_report> → push_report → 返回渠道级结果
```

### 6.4 orchestration/scheduler.py（新）—— APScheduler 降级调度

```python
"""降级调度入口（Plan B）：hermes-agent 不可用时 python -m techtrend.orchestration.scheduler"""
def build_scheduler(settings) -> BackgroundScheduler:
    # BlockingScheduler + CronTrigger.from_crontab(settings.schedule_cron, tz=timezone)
    # job = 调 subprocess 跑 [python, cron.py, --mode, daily, --notify]
def main() -> int:  # 阻塞运行；schedule_enable=false 时提示并退出
```

> 用 **subprocess 而非 import** 跑 `cron.py`：与 hermes-agent cron 触发方式完全同构（都是「外部进程触发同一入口」），
> 保证两条路径行为逐字节一致。

### 6.5 cron.py（改）—— 统一入口扩展

```python
"""定时调度入口（P5 落地）。hermes-agent cronjob 与 APScheduler 都触发此入口。"""
parser.add_argument("--mode", choices=["daily","full"], default="full")   # daily=runbook 增量；full=main.py 全量
parser.add_argument("--notify", action="store_true")                       # 临时开推送（覆盖 notify_enable）
parser.add_argument("--dry-run", action="store_true")                      # 只打印将执行的阶段顺序 + 角色标签，不实际跑
parser.add_argument("--auto-approve", action="store_true")                 # 覆盖 review_auto_approve=false
# daily → orchestration.runbook.run_daily；full → 原 main.run() 逻辑（保持 --stage/--list 兼容）
```

### 6.6 stages/__init__.py（改）

`get_default_stages` 末尾追加 `NotifyStage(settings)`（第 8 阶段）。`main.py --list` 输出 8 阶段；
`NotifyStage` 在 `notify_enable=false` 时返回 `skipped:true` 不阻断。

---

## 7. hermes-agent 侧设计（thin adapter）

> 语义内容确定；**YAML/JSON schema 以本机安装的 hermes-agent 版本为准**（实现期第一步先 `hermes-agent --version` 并查其
> cronjob/skill/agent 的配置样例）。以下给的是「每条要说什么」而非「最终字段拼写」。

### 7.1 技能沉淀（SKILL.md，agentskills.io 标准）

- `hermes/skills/techtrend-daily/SKILL.md`：主技能 —— 「每日技术趋势 pipeline 运行手册」。写明：
  触发命令 `python cron.py --mode daily --notify`、7+1 阶段顺序、各源 cursor/去重机制、失败降级（某源 error 不阻断）、
  产物清单（works/triples/report/run_manifest）。
- `hermes/skills/roles/SKILL.md`：6 角色的职责与委派图（= roles.py 的人类可读版），标注哪些可并行（analyst 的 burst/tkg/forecast）、
  哪个是 HITL 卡点（reviewer）。

### 7.2 cronjob 定时（主选调度）

`hermes/config/cronjobs.example.yaml`：一条 cronjob，cron 表达式 `0 3 * * *`（本地时区），动作 = 执行
`F:\Predictive agents\.venv\Scripts\python.exe cron.py --mode daily --notify`（hermes-agent 侧填底层 python 解释器绝对路径，见记忆：不用坏掉的 `python` 桩）。

### 7.3 角色 agent 委派（多智能体贡献点）

`hermes/config/agents.example.yaml`：定义 6 个子 agent（名字 = roles.py 的 name），各自 `SKILL.md` 引用 + 允许的底层工具
（collector→collect、analyst→predict 子任务…）；委派链 = `delegate_task` + kanban 队列，DAG 边 = roles.py 的 `runs_after`。
**并行**：analyst 的 `burst/tkg/forecast` 三个子任务 fan-out 并行（底层 predict 已隔离，无共享状态冲突）。

### 7.4 降级对照（验收④的关键）

| 能力 | hermes-agent 模式 | 降级模式（APScheduler/直接 cron.py） |
|---|---|---|
| 定时 | 内置 cronjob | scheduler.py（APScheduler） |
| 多智能体委派 | delegate_task + kanban | 单进程 runbook 串行（仍按角色打标 + 分 summary） |
| 技能沉淀 | SKILL.md 自动生成 | 手动维护同一批 SKILL.md |
| 报告推送 | 内置 Telegram/Discord 工具 或 notify.py | notify.py（httpx） |
| HITL | 交互式审校 | review_approve.json / stdin |

---

## 8. 实施顺序（任务分解，含依赖）

1. **config.py + .env.example + requirements.txt**：补 P5 参数段；解注释 `apscheduler`。单测：`get_settings()` 无 .env 默认值干净跑通。
2. **roles.py + runbook.py**：角色定义 + `run_daily`（先不含 notify/HITL，串 collector→extractor→analyst→integrator→reporter）。
   单测：manifest 逐条追加；全源 0 新增时短路（`noop=true` 且不触发 extract）。
3. **notify.py + notify_stage.py + stages/__init__ 注册**：`file` 渠道先通（`output/notify_latest.md`）；telegram/discord 用
   `--dry-run` 校验 URL 拼接不发真实请求。单测：渠道级失败不阻断、`notify_enable=false` 返回 skipped。
4. **cron.py 扩展**：`--mode/--notify/--dry-run/--auto-approve`。单测：`--dry-run` 打印角色标签顺序、不落库；`--mode full` 与 main.py 行为一致。
5. **scheduler.py（APScheduler 降级）**：subprocess 触发 `cron.py --mode daily --notify`。单测：cron 表达式解析正确、job 可手动 fire。
6. **HITL 审校开关**：`review_enable_hitl=true` + `review_auto_approve=false` 时，report 前写 `review_request.json` 并等待
   `review_approve.json`（超时可配，默认不限）。单测：auto=true 直接放行。
7. **hermes-agent adapter**：对着安装版本核对 schema，落 `hermes/` 三文件（SKILL + cronjob + agents）。验收④的降级对照跑一遍。
8. **端到端 + 连续 3 天**：`cron.py --mode daily --notify` 连续跑（可手动触发模拟 3 天），验证增量不重复 + 时序深度递增 + manifest 3 条。

---

## 9. 验证方式 + 验收标准

```bash
# 底层独立性（验收③）：不依赖 hermes-agent
& 'F:\Predictive agents\.venv\Scripts\python.exe' cron.py --mode daily --notify
& 'F:\Predictive agents\.venv\Scripts\python.exe' cron.py --dry-run          # 只看角色顺序不落库
type output\run_manifest.jsonl
type output\notify_latest.md

# 连续 3 天增量不重复（验收②）：同一天触发 2 次，第 2 次应 0 新增短路
& 'F:\Predictive agents\.venv\Scripts\python.exe' cron.py --mode daily        # 第 1 次：各源有新增
& 'F:\Predictive agents\.venv\Scripts\python.exe' cron.py --mode daily        # 第 2 次：noop=true（除 github star 快照外无重复数据）

# 降级调度（验收③ Plan B）
& 'F:\Predictive agents\.venv\Scripts\python.exe' -m techtrend.orchestration.scheduler   # 需先 SCHEDULE_ENABLE=true（或 --once 参数）
```

**验收标准**（对应 PROJECT_PLAN P5 行「每日无人值守跑通」）：

| # | 标准 | 通过标志 |
|---|---|---|
| 1 | 每日无人值守跑通 | `cron.py --mode daily --notify` exit 0；manifest 各阶段 status=ok |
| 2 | 增量不重复 + 时序深度递增（#20） | 同日二次触发 `noop=true`；`works.jsonl`/`arxiv.jsonl` 行数逐日单调不降、`triples.jsonl` 时态跨度拉长 |
| 3 | 底层独立性 | 关掉 hermes-agent，`cron.py` 直接跑仍 exit 0、产物齐全 |
| 4 | 报告推送 | `notify_latest.md` 生成 + 至少一个渠道（file 兜底）收到报告 |
| 5 | 多智能体叙事可交付 | `--dry-run` 打印角色→阶段映射；`hermes/skills/roles/SKILL.md` 描述 6 角色委派图 |

---

## 10. 风险与注意

- **hermes-agent 版本快、不稳定**：cronjob/skill/agent 的 schema 随时变 → 以安装版本为准（§7 已标注）；编排能力由
  APScheduler 兜底，**hermes-agent 只是「主选叙事 + 课题要求」的一层**，崩了不影响每日跑通。
- **extract 全量重算成本**：每日从增长的 interim 全量重导出 + 全量 LLM 重抽（`llm_max_docs_per_run` 每次都花一遍）→
  数据量涨后每日成本上升。P5 先靠「0 新增短路」缓解；真正的「增量抽取」（只对新 doc 抽 + 增量合并 triples）登记为后置优化，
  不在本阶段强做（正确性优先于效率）。
- **github star 快照「不算重复」**：[collect.py](../../techtrend/stages/collect.py) `_collect_github` 每次都 `append_jsonl` 一条
  star 快照（这是刻意设计，star 时间序列需要每日新点），因此「0 新增短路」的判定**只看 id 去重后的 new_records，不看 star 快照**，
  否则永远短路不了。
- **本机 Clash 代理方向相反**（见记忆 [[windows-clash-proxy-localhost]]）：本地 RSSHub 请求要 `trust_env=False`；
  外网 Telegram/Discord 推送要 `trust_env=True` 走代理。notify.py 内必须按目标 host 区分，不能一刀切。
- **python 解释器**：scheduler/cronjob 一律写 `F:\Predictive agents\.venv\Scripts\python.exe`（见记忆 [[python-interpreter-path]]），
  不依赖 PATH 里坏掉的 `python` 桩。
- **HITL 卡死风险**：`review_enable_hitl=true` + `auto=false` 时若无人应答，runbook 会一直等 → 加超时（默认不限但可配），
  且无人值守验收必须用 auto=true。
- **「调到赢」红线**（承 PROJECT_PLAN #18）：每日增量只**补数据/补历史**，不因时序变深就去调 `tkg_min_cooccur`/`tkg_alpha`
  凑 A2 反超；若 P5 累积后仍不达标，回兜底 ② 如实收尾。

---

## 11. 待办登记（跨 P6）

- **增量抽取**（extract 只抽新 doc + 增量合并 triples，替代每日全量重算）—— 数据量增长后的成本优化，非正确性问题。
- **目标③真引用/star 时序**（`cited_by_count` 1 行修复 + 多日 star 快照入回归）—— P4_P3 的 P1-1，可借 P5 每日跑自然累积，但回归目标切换仍属算法侧，留后置。
- **目标④ S 曲线阶段 + 趋势图 + 周报** —— P6 可视化/报告（notify 的周报渠道可复用 notify.py）。
- **定向抽取全源近期覆盖**（#21）—— 定向 pass 从 OpenAlex 扩到 arXiv/USPTO/GitHub/RSSHub，P5 每日增量使各源数据变厚后更有意义。
- 根目录残留调试脚本 `alpha_sweep_tmp.py / dim_sweep_tmp.py / debug_fusion_tmp.py` 可删（承 P3_OPT_P4_RESULT 尾注）。
