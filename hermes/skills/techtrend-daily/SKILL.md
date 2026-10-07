---
name: techtrend-daily
description: 每日技术趋势 pipeline 运行手册（采集→抽取→对齐→建图→预测→报告→推送）。无人值守每日触发，逐日累积时序深度。
---

# 每日技术趋势 pipeline 运行手册

触发命令（底层 python 解释器用绝对路径，不用坏掉的 `python` 桩）：

```bash
& 'F:\Predictive agents\.venv\Scripts\python.exe' cron.py --mode daily --notify
```

## 阶段顺序（7+1，共 8 阶段）

| 角色 | 阶段 | 说明 |
|---|---|---|
| collector | collect | 多源增量采集（各源 cursor + id 去重） |
| extractor | extract → align → build_graph | LLM 抽实体/关系 + 跨源对齐 + 写 Neo4j |
| analyst | predict | 突发/TKG 外推/回归（burst/tkg/forecast 可并行子任务） |
| integrator | evaluate | 融合多路信号 + walk-forward 回测校验 |
| reviewer | HITL | 报告前暂停人工确认（默认 auto 放行） |
| reporter | report → notify | 生成日报告 + 推送渠道 |

## 短路守卫

全源 0 新增（`daily_skip_if_no_new=true`）时跳过 extract/align/build_graph/predict/evaluate，
直接 report+notify，manifest 记 `noop=true`，避免空跑烧 LLM 预算。

## 失败降级

- 某源采集失败（`error`）不阻断他源；但有源 error 时不触发短路（无法确定是否真无新增）。
- 单阶段异常记 `error` 继续后续阶段，manifest 记录各阶段 status。

## 产物清单

- `data/interim/works.jsonl`、`arxiv.jsonl`、`patents.jsonl`、`news.jsonl`、`github.jsonl`（逐日增长）
- `data/interim/triples.jsonl`、`nodes.jsonl`（整表重算，时态跨度逐日拉长）
- `output/report.md`、`eval_report.md`
- `output/notify_latest.md`（file 渠道兜底）
- `output/run_manifest.jsonl`（每次运行追加一条，无人值守观测）
