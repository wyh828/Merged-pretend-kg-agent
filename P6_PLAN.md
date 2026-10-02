> 本机适配说明：工程路径已改为 `F:/Predictive agents`；以下阶段设计与实验数字仍为上游历史记录。本机执行结果见 README 的「本机修订 00」。

# P6 可视化 / 报告 —— 完整构建计划

> 本文档承接 [PROJECT_PLAN.md](PROJECT_PLAN.md) §七「分阶段路线图」P6 行（趋势图 + S 曲线阶段 + 周报，交付前端/报告，验收「可演示」），
> 文末「后置优化/待决策登记」#10（目标④ S 曲线阶段 + 趋势图 + 周报）、#13（Kleinberg 泛化概念 / 排名 p@k=0 留待 P6），
> 以及 [P4_P3_METRIC_OPT_RESULT.md](P4_P3_METRIC_OPT_RESULT.md) §5「S 曲线选样修正」、[P5_PLAN.md](P5_PLAN.md) §11「目标④ S 曲线阶段 + 趋势图 + 周报 —— P6」。
> 现状代码见 [report.py](techtrend/stages/report.py)、[evaluate.py](techtrend/stages/evaluate.py)（已产 `citation_metrics.json` / `s_curve_stages.csv`）、
> [citations.py](techtrend/prediction/citations.py)（`s_curve_stage` 分类器，选样有偏）、[orchestration/notify.py](techtrend/orchestration/notify.py)（P5 推送，周报可复用）。

---

## 0. 一页速览

| 维度 | 内容 |
|---|---|
| 目标 | 把 P1–P5 已跑通的四目标预测结果变成「可演示」交付物：趋势图 + S 曲线阶段（目标④）+ 周报 |
| 载体 | **自包含单文件 `output/dashboard.html`**（内联 SVG，零新增依赖、离线可开）+ 文本/表格周报 `weekly_report.md` |
| 核心新增 | `prediction/lifecycle.py`（S 曲线分类泛化）+ `viz/` 包（svg/charts/dashboard/weekly）+ `VisualizeStage`（第 9 阶段）+ report 汇总四目标 |
| 关键修正 | S 曲线选样由「top-N 总被引」改为**分层抽样**，让 emerging/growth 也被覆盖（承 P4_P3_RESULT §5 待办） |
| 目标④ 单元 | **概念（技术实体）级为主**（活动量累积）+ **专利级为辅**（真引用累积） |
| 验收 | ① 离线开 dashboard 无外部网络请求 ② S 曲线阶段分布 ≥3 类 ③ 周报一键生成 ④ 四目标汇总 report ⑤ 可演示 |

---

## 1. Context（为什么做 / 承上启下）

**P0–P5 已把「采集 → 图谱 → 预测 → 验证 → 自动化」五层做齐**（见 PROJECT_PLAN §七「阶段成果记录」），四个预测目标里
①②③ 已出指标、④ 已有专利级 S 曲线雏形。但整条链路目前**没有任何一张图**，也没有汇总四目标的单一报告——成果散落在
`output/` 的 12 个 json/csv 里，无法「演示」。

> **定稿依据（P3/P4/P5 成果，见 PROJECT_PLAN §「P3 / P4 完整结果（定稿，cooccur 主边源）」）**：四目标最终数字 ——
> ① p@k=0.0（信号弱，留 P6 如实展示）；② TKG 共现图 CyGNet **0.9459** vs RotatE **0.4487**（`relates_to` 为无向共现代理，非真实定向关系）；
> ③ 活动量代理 MAE 0.5017 / 真引用口径 RMSE≈57；④ S 曲线仅 mature+declining（top-N 选样 + `total<0.2*max(x)` 判据在累积序列上恒假）。
> TKG 边源定稿 `cooccur`；专利引用图（P0-1，6,967,772 事实，2015-01→2024-12）仅服务目标③/④、经 P2-1 证伪不作 TKG 边源。

**P6 的定位是「渲染」而非「再建模」**：不新增预测算法、不修排名 p@k=0（那是数据信号弱的问题，见 #13，属于「补真引用/star 时序」
的数据路线，不在可视化阶段解决）、不调 TKG 参数。P6 只做一件事——**把已有四目标结果诚实地画出来、讲清楚**。

**现状盘点（决定 P6 从哪接手）**：

| 现状 | 对 P6 的含义 |
|---|---|
| `output/` 已有 12 个产物（`baseline/temporal/eval/citation_metrics.json`、`forecast.csv`、`fusion_ranking.csv`、`s_curve_stages.csv`…） | 可视化**零重算**：全部读这些产物渲染，不重跑预测 |
| [report.py](techtrend/stages/report.py) 只读 `baseline_metrics.json` + `temporal_metrics.json` | 遗漏 walk-forward（`eval_metrics.json`）与 S 曲线（`citation_metrics.json`）→ 需补成四目标汇总 |
| `requirements.txt` **无 matplotlib/plotly** | 走「零新增依赖」的**内联 SVG** 路线（契合 P3 用 sklearn 替代 XGBoost 的一贯取向） |
| [citations.py](techtrend/prediction/citations.py) `s_curve_stage` 已有，但 `build_patent_citation_monthly` 按**总被引 top-N** 选样；且 `s_curve_stage` 的 `total < 0.2*max(x)` 在累积序列上恒假 | 实测 `s_curve_dist={mature:4037, declining:963}` 只 2 类（PROJECT_PLAN 定稿：mature/declining 无 emerging/growth）→ P6 改分层抽样 + 修 emerging 判据 |
| 目标④ 只在**专利**上做了，**概念（技术实体）**上没有 | 目标④ 本义是「技术成熟度」，技术=Concept，P6 补概念级 S 曲线为主演示路径 |
| [notify.py](techtrend/orchestration/notify.py)（P5）已能推 file/telegram/discord | 周报可复用 `push_report`，不新造推送 |

---

## 2. 关键决策

| # | 决策 | 结论 | 依据 |
|---|---|---|---|
| 1 | 可视化载体 | **自包含 HTML + 内联 SVG（零新增依赖）**；交互需求升级时再换 Plotly（`include_plotlyjs='inline'`） | 离线可开、无 CDN、体积小、主题可调；契合项目「零新依赖」取向；本机 Clash 代理/无网演示也稳 |
| 2 | 目标④ 单元 | **概念级（技术实体）为主 + 专利级（引用累积）为辅** | 目标④ 本义「技术成熟度」；概念用活动量累积，专利用 P0-1 真引用累积 |
| 3 | S 曲线选样修正 | `build_patent_citation_monthly` 改**分层抽样**（按 log₁₀ 总被引分箱、每箱采样），保留全谱阶段 | 承 P4_P3_RESULT §5 待办；top-N 总被引只出成熟/衰退 |
| 4 | 阶段结构 | 新增 `VisualizeStage`（**第 9 阶段**，在 evaluate 之后、notify 之前），纯渲染、零重算 | 与 P4 的 `EvaluateStage`、P5 的 `NotifyStage` 同一「追加阶段」模式 |
| 5 | 周报触发 | 周边界（可配 weekday，默认周一）由 `VisualizeStage` 顺带产出 + 独立 `cron.py --mode weekly` 手动/演示 | 复用 P5 每日 cron，不新增调度器；手动可回填 |
| 6 | report 汇总 | [report.py](techtrend/stages/report.py) 从「baseline+temporal」扩到**四目标**（+eval+citation+S 曲线） | 现在 report 遗漏 walk-forward 与目标④，不是完整报告 |
| 7 | 排名 p@k=0 | **不修**，如实展示 fusion top-k 并标注「p@k=0 为信号本身弱」的诚实声明 | #13 属数据信号路线；P6 只渲染，红线「不调到赢」 |

> **可视化载体对比**（决策 1 依据）：

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| 自包含 HTML + 内联 SVG | 离线可开、无 CDN、零依赖、主题可调（prefers-color-scheme）、体积 KB 级 | 交互弱（tooltip/缩放需手写）、图表类型手写 | ✅ **主选** |
| Plotly（`include_plotlyjs='inline'`） | 交互强、图表类型全 | 新增重依赖、单文件数 MB、中文字体需配 | 备选（需交互时后置） |
| matplotlib → PNG | 成熟、代码少 | 新增依赖、静态无交互、中文/负号坑 | 不选（除非周报要嵌 PNG） |

---

## 3. 目录结构（P6 新增/改动）

```
techtrend/
  prediction/
    lifecycle.py                # 新：S 曲线阶段分类（泛化，概念级 + 专利级共用）
    citations.py                # 改：build_patent_citation_monthly 分层抽样；s_curve_stage 迁移到 lifecycle 后 re-export
  viz/                          # 新包：纯渲染（零重算，只读 output/*）
    __init__.py
    svg.py                      # 新：SVG 原语（polyline/rect/axis/color tokens，theme-aware）
    charts.py                   # 新：各图 SVG（趋势折线 / S 曲线叠加 / 阶段分布柱状 / walk-forward 折线 / 融合榜单）
    dashboard.py                # 新：拼装自包含 dashboard.html
    weekly.py                   # 新：周报聚合（run_manifest.jsonl + 最新指标 + 图）
  stages/
    visualize.py                # 新：VisualizeStage（第 9 阶段）
    report.py                   # 改：汇总四目标（baseline+temporal+eval+citation+S 曲线）
    __init__.py                 # 改：注册 VisualizeStage（evaluate 之后、notify 之前）
  config.py                     # 改：+ P6 viz/lifecycle/weekly/选样参数段
cron.py                         # 改：+ --mode weekly（手动/演示周报）
.env.example                    # 改：+ P6 段
requirements.txt                # 不改（零新增依赖；可选升级路径见 §10）
```

---

## 4. 数据流（渲染输入 → dashboard）

```
output/（P1–P5 已落盘，P6 只读）
  baseline_metrics.json   ──┐
  temporal_metrics.json   ──┤
  eval_metrics.json       ──┤  report.py（改）──► report.md（四目标汇总）
  eval_folds.csv          ──┤
  citation_metrics.json   ──┤
  s_curve_stages.csv      ──┤
  forecast.csv            ──┼──► visualize.py ──► dashboard.html（内联 SVG，自包含）
  fusion_ranking.csv      ──┤        ├─ charts/trend_top.svg
  burst_concepts.csv      ──┤        ├─ charts/s_curve_overlay.svg
  run_manifest.jsonl      ──┘        ├─ charts/stage_dist.svg
  (P5 每日追加)                       ├─ charts/walkforward_folds.svg
                                      └─ weekly_report.md（周边界时）
```

**关键点**：
- **零重算**：`VisualizeStage` 只 `json.loads` / `pd.read_csv` 读 `output/`，不 import torch/pykeen、不碰 Neo4j、不发网络请求。
- **时序曲线数据来源**：概念趋势用 `build_concept_monthly_counts`（[kleinberg.py](techtrend/prediction/kleinberg.py)）对 `works.jsonl` 现场算（这是唯一一处「重算」，仅读 interim 聚合，无模型/LLM）；专利累积引用用 `patent_citations.jsonl`。二者都进 dashboard 趋势图。
- **周报**：读 `run_manifest.jsonl` 尾部 7 条（P5 每日追加）+ 最新四指标 + fusion top-k + S 曲线分布，产出文本周报并复用 [notify.py](techtrend/orchestration/notify.py) 推送。

---

## 5. 配置扩展（config.py + .env.example）

```python
# ---- 可视化 / 报告（P6）----
viz_enable: bool = True                  # VisualizeStage 开关
viz_dashboard_file: str = "output/dashboard.html"
viz_charts_dir: str = "output/charts"
viz_top_k: int = 20                      # 趋势图 / 榜单展示 top-N 概念/专利
viz_theme: str = "auto"                  # auto(跟随系统) | light | dark

# 生命周期（目标④）
lifecycle_growth_window: int = 6         # 增速比较窗口（月）
lifecycle_emerging_quantile: float = 0.2 # 累积量分位阈值（判 emerging）
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
```

> `.env.example` 对应补 `VIZ_ENABLE/VIZ_THEME/LIFECYCLE_*/PATENT_CITATION_SAMPLING/WEEKLY_*` 段（全默认，无 key 也跑通）。

---

## 6. 各模块详细设计

### 6.1 prediction/lifecycle.py（新）—— S 曲线阶段分类（泛化）

把 [citations.py](techtrend/prediction/citations.py) 里专利专用的 `s_curve_stage` 抽出来泛化，**概念级与专利级共用**：

```python
def s_curve_stage(cumulative: Iterable[float], growth_window: int = 6,
                  emerging_quantile: float = 0.2, min_history: int = 12) -> str:
    """对『累积』序列判 S 曲线阶段（目标④）。
    - 输入须为单调不减的累积序列（专利累积被引 / 概念累积活动量）。
    - emerging  序列箱数 < min_history，或累积终点 < 全样本 emerging_quantile 分位
    - growth    近期增速 > 历史增速（二阶导 > 0，加速上升）
    - mature    近期增速 > 0 但 ≤ 历史增速（减速仍增长，饱和）
    - declining 近 growth_window 月增量为 0（停止增长）
    """
```

**关键修正点**（对现 `citations.py` 版本）：现版 `if total < 0.2 * max(x): return "emerging"` 在累积序列上**恒为假**
（`total == x[-1] == max(x)`），导致 emerging 分支永远走不到——这是 P4_P3_RESULT 里「S 曲线仅 mature+declining」的
**算法侧**原因之一（另一原因是选样偏，见 6.2）。新版 emerging 改用**分位阈值**（对全样本终点分布取分位）判定，并加 `min_history` 兜底。

```python
def concept_lifecycle_stages(monthly: pd.DataFrame, ...) -> pd.Series:
    """概念级 S 曲线（P6 主演示路径）：概念月度活动量 → 累积 → 逐概念阶段标签。"""

def s_curve_stages(monthly: pd.DataFrame, ...) -> pd.Series:
    """保持原签名（专利级入口，从 citations.py 迁移而来，供 evaluate.py 与 viz 复用）。"""
```

**向后兼容**：[citations.py](techtrend/prediction/citations.py) 里 `s_curve_stage`/`s_curve_stages` 改为
`from techtrend.prediction.lifecycle import s_curve_stage, s_curve_stages` 再 re-export，[evaluate.py](techtrend/stages/evaluate.py)
的 `from ...citations import ... s_curve_stages` 无需改动（或一并切到 lifecycle，二选一，实现期定）。

### 6.2 prediction/citations.py（改）—— S 曲线选样修正

`build_patent_citation_monthly` 的 `max_patents` 目前按**总被引次数降序取 top-N**，系统性排除 emerging（低被引但近期活跃）。
改为**分层抽样**：

```python
def build_patent_citation_monthly(facts, mode="month", min_citations=2,
                                  max_patents=5000, sampling="stratified",
                                  n_bins=5, per_bin=2000) -> pd.DataFrame:
    # sampling == "stratified"：
    #   1. 先按 min_citations 过滤噪声（保留）
    #   2. 对每个专利算 log10(总被引+1)，等宽分 n_bins 箱
    #   3. 每箱内按总被引降序取 per_bin 个（不足全取）→ 低被引箱也保底覆盖
    # sampling == "top_total"：旧行为（总被引 top-N），保留作对照
```

> 说明：分层抽样**保留成熟/衰退样本**（高被引箱仍满额），同时**保底纳入低被引箱**（emerging/growth 候选），
> 使 S 曲线分布覆盖 ≥3 个阶段。这是「修正数据忠实于问题」（承 §2 决策 3），不是「调到赢」。

### 6.3 viz/svg.py（新）—— SVG 原语 + 色板（theme-aware）

纯函数，无状态、零依赖，输入 numpy/list 数据、输出 SVG 字符串：

```python
def color_tokens(theme: str) -> dict          # 明/暗两套 CSS 变量（palette 由 dataviz skill 定）
def svg_line(points, stroke, ...) -> str      # <polyline>
def svg_bars(rects, fill, ...) -> str         # 柱状
def svg_axis(xs, ys, labels, ...) -> str      # 坐标轴 + 刻度
def svg_fig(inner: str, w, h, title) -> str   # 图框 + 标题 + 图例
```

> **实现期第一步先读 `dataviz` skill**：按「可读性优先、light/dark 双主题、品牌中性可替换色板、不硬编码颜色、对比度达标」
> 设计 SVG 色板与标注规范。dashboard 用 `prefers-color-scheme` + `data-theme` 切换明暗（与系统提示的 theme-aware 规则一致）。

### 6.4 viz/charts.py（新）—— 各图 SVG

| 函数 | 输入 | 图 | 对应目标 |
|---|---|---|---|
| `trend_top_svg(monthly, top_k)` | 概念/专利累积或活动量矩阵 | top-k 趋势折线 | ③（+④ 曲线叠加） |
| `s_curve_overlay_svg(stages, curves)` | 各阶段典型曲线 | 每阶段一条归一化累积曲线叠加 | ④ |
| `stage_dist_svg(dist)` | `s_curve_dist` dict | 阶段分布柱状 | ④ |
| `walkforward_folds_svg(folds)` | `eval_folds.csv` | 每折 tkg_mrr/copyonly/rotate 三线 | ② |
| `fusion_rank_svg(ranking)` | `fusion_ranking.csv` | top-k 融合得分横向条形 | ① |
| `forecast_svg(forecasts)` | `forecast.csv` | actual vs forecast 散点/线 | ③ |

### 6.5 viz/dashboard.py（新）—— 拼装自包含 dashboard.html

读 `output/*.json/csv`，调 charts 出各图，拼成**单文件** HTML（CSS 内联 + SVG 内联 + 零外部 `<script>`/`<link>`）：

```
dashboard.html 分区：
  header        标题 + 生成时间 + TKG 边源(含回退说明)
  指标卡片      四目标：② MRR/Hits、③ MAE/RMSE、① p@k、④ S 曲线分布
  目标②        walk-forward 每折折线（CyGNet vs copy-only vs RotatE）
  目标③        概念趋势折线 + 预测值标注
  目标④        S 曲线叠加图 + 阶段分布柱状（概念级 + 专利级）
  目标①        融合 top-k 榜单（附诚实声明：p@k=0 为信号本身弱，见 #13）
  脚注         口径：filtered / walk-forward+purge+embargo / 转导协议 / 边源回退
```

**硬要求**：`dashboard.html` 双击离线可开、**无任何外部网络请求**（不引 CDN、不内联巨型 JS）、图片以数据而非外部链接承载；
顶部/底部安全区适配移动端宽度；`max-width:100%` 与图内 `overflow-x:auto`。

### 6.6 viz/weekly.py（新）—— 周报聚合

```python
def build_weekly_report(settings) -> str:
    # 读 run_manifest.jsonl 尾部 weekly_window_days 条
    # 汇总：各源累计新增数、成功/失败天数、阶段状态
    # 最新四指标（eval_metrics.json）+ S 曲线分布（citation_metrics.json）
    # 本周 fusion top-k + 突发热点（burst_concepts.csv）
    # 文本/表格周报 + 末尾链接 dashboard.html
```

周报为**纯文本/表格**（markdown 里嵌 SVG 兼容性差），图一律「指向 `dashboard.html`」，不嵌图片 → 维持零新增依赖。

### 6.7 stages/visualize.py（新）+ stages/__init__.py（改）—— 第 9 阶段

```python
class VisualizeStage(Stage):
    name = "visualize"
    def run(self) -> dict:
        if not self.settings.viz_enable:
            return {"stage": self.name, "status": "skipped"}
        # 读 output/* → dashboard.html + charts/*.svg
        # weekly_enable 且今天是 weekly_weekday → 写 weekly_report.md（可再 notify）
```

[stages/__init__.py](techtrend/stages/__init__.py) `get_default_stages` 在 `EvaluateStage` 之后、`NotifyStage` 之前插入
`VisualizeStage(settings)`。`main.py --list` 输出 **9 阶段**。

### 6.8 stages/report.py（改）—— 汇总四目标

`_render` 从「baseline+temporal」扩到读 `eval_metrics.json` + `citation_metrics.json` + `s_curve_stages.csv`，产出四目标汇总表：
① 排名（precision@k + fusion top-k）、② 链接预测（walk-forward MRR/Hits + 边源回退说明）、③ 回归（MAE/RMSE/MAPE，
标注活动量代理 vs 真引用口径）、④ S 曲线（阶段分布 + 覆盖阶段数）。保持向后兼容：旧字段仍在。

---

## 7. 实施顺序（任务分解，含依赖）

1. **prediction/lifecycle.py**：S 曲线分类泛化 + 概念级 + 专利级入口；`citations.py` re-export 保持兼容。
   单测：对构造的累积序列（加速/减速/停止）判出 growth/mature/declining/emerging 各阶段。
2. **citations.py 选样修正**：`stratified` 分层抽样，`top_total` 保留对照。单测：分层后阶段分布覆盖 ≥3 类。
3. **viz/svg.py + charts.py**：先读 `dataviz` skill 定色板，再落 SVG 原语与六图。单测：每图输出合法 SVG 字符串、无外链。
4. **viz/dashboard.py**：拼装自包含 dashboard.html。单测：文件无 `<script src>`/`<link href>`/`http` 外链，浏览器离线可开。
5. **viz/weekly.py**：周报聚合。单测：给定 7 条 manifest 输出含各源新增数 + 四指标 + 周环比。
6. **stages/visualize.py + stages/__init__.py 注册**：`--list` 含 visualize、exit 0。单测：`viz_enable=false` 返回 skipped。
7. **stages/report.py 汇总四目标**：读 eval + citation。单测：report.md 含四目标小节与 S 曲线分布。
8. **config.py + .env.example**：补 P6 段。单测：`get_settings()` 无 .env 默认值干净。
9. **端到端验收**：`main.py --stage visualize` 产 dashboard + charts + （周边界）weekly_report；浏览器离线打开核对四图齐全、S 曲线 ≥3 阶段。

---

## 8. 验证方式 + 验收标准

```bash
& 'F:\Predictive agents\.venv\Scripts\python.exe' main.py --list            # 输出 9 阶段（含 visualize）
& 'F:\Predictive agents\.venv\Scripts\python.exe' main.py --stage visualize # 渲染 dashboard + charts（零重算）
& 'F:\Predictive agents\.venv\Scripts\python.exe' cron.py --mode weekly     # 手动/演示周报
# 浏览器双击 output/dashboard.html：无网络请求、四目标图齐全、明暗主题可切
```

**验收标准**（对应 PROJECT_PLAN P6 行「趋势图 + S 曲线阶段 + 周报，可演示」）：

| # | 标准 | 通过标志 |
|---|---|---|
| 1 | 趋势图 | `dashboard.html` 自包含、离线可开，含 top 概念/专利趋势折线 + 预测标注 |
| 2 | S 曲线阶段（目标④） | 概念级 + 专利级阶段标签；分布覆盖 **≥3 个阶段**（emerging/growth/mature/declining 至少 3 类）；选样分层后不再只有 mature+declining |
| 3 | 周报 | `weekly_report.md` 聚合当周 manifest + 四指标 + 图链接，`--mode weekly` 一键生成 |
| 4 | 四目标汇总 | `report.md` 统一汇总四目标（补 eval + citation + S 曲线），不再只 baseline+temporal |
| 5 | 可演示 | 浏览器打开 `dashboard.html` 无外部网络请求、无 JS 报错、四目标分区齐全、明暗主题可切 |
| 6 | 诚实口径 | dashboard/report 显式标注「p@k=0 为信号弱」「活动量代理 vs 真引用」「TKG 边源回退」三条诚实声明 |

---

## 9. 风险与注意

- **零依赖路线的交互弱**：SVG 无原生 hover/缩放。演示够用；若后续要交互，升级 Plotly（`include_plotlyjs='inline'`），
  `viz/charts.py` 的「数据 → 图」接口不变，只换后端（见 §10 待办）。
- **S 曲线选样是「修正数据忠实于问题」，不是「调到赢」**（承 PROJECT_PLAN #18）：分层抽样目的是让**全谱阶段**都能被
  观测与演示，不改 `lifecycle_*` 阈值去凑分布；若分层后某阶段仍缺样本，如实报告「样本不足」而非调阈值凑齐。
- **emerging 判据分位阈值依赖样本**：`lifecycle_emerging_quantile` 对全样本终点分布取分位，样本量小（专利 top-N 已截断）
  时分位不稳 → 报告里注明「阶段标签是启发式，非监督真值」，不把 S 曲线当成「训练出来的成熟度模型」宣传。
- **专利引用止于 2024**（P0-1 终版）：专利级 S 曲线时态到 2024-12；概念级用活动量可到 2026-09，二者时间跨度不同，
  报告须分开标注，不混比。
- **周报与日报的关系**：周报只聚合**已有** manifest 与指标，不触发新采集/预测；`--mode weekly` 是纯渲染，误触发不会烧 LLM/CPU。
- **明暗主题**：SVG 颜色走 CSS 变量 + `prefers-color-scheme`，不硬编码 hex；实现前先读 `dataviz` skill 定色板。
- **python 解释器**（承记忆 [[python-interpreter-path]]）：所有命令写 `F:\Predictive agents\.venv\Scripts\python.exe`，不依赖坏掉的 `python` 桩。
- **不新增依赖**：`requirements.txt` 不改；若验收时发现 matplotlib/plotly 确实必要（如周报要嵌 PNG），再单列讨论，不默认引入。

---

## 10. 待办登记（跨 P6 之后 / 收尾）

- **交互升级**：SVG → Plotly（`include_plotlyjs='inline'`）当需要 hover/缩放时；`viz/charts.py` 接口不变。
- **排名 p@k=0 根治**（#13）：补真引用/star 时序（P1-2 已回填 `cited_by_count`，多日 star 快照待 P5 累积）→ 属数据路线，非可视化。
- **目标④ 监督化**：S 曲线阶段当前是启发式；若要「训练」成熟度模型，需人工标注阶段真值，留作选题延伸，不在 P6 做。
- **周报推送渠道**：当前周报可复用 [notify.py](techtrend/orchestration/notify.py) 的 file/telegram/discord；是否把周报纳入
  每日 `notify_channels` 之外的「周推送」单列，实现期按需定。
- **根目录残留调试脚本** `alpha_sweep_tmp.py / dim_sweep_tmp.py / debug_fusion_tmp.py` 可删（承 P3_OPT_P4_RESULT 尾注）。
