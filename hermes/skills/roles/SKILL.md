---
name: techtrend-roles
description: 6 角色多智能体委派图（采集/抽取/分析/预测集成/审校/报告）。与 techtrend/orchestration/roles.py 单一事实来源一致。
---

# 技术趋势 pipeline 6 角色委派图

> 单一事实来源：`techtrend/orchestration/roles.py`（本文件是其人类可读版，改动需两处同步）。

## 角色与职责

| 角色 | 底层阶段 | 依赖 | 说明 |
|---|---|---|---|
| collector | collect | — | 调度/监控各源每日增量 |
| extractor | extract, align, build_graph | collector | LLM 抽实体/关系 + 对齐 + 写 Neo4j（needs_llm） |
| analyst | predict | extractor | 突发/TKG 外推/回归 |
| integrator | predict, evaluate | analyst | 融合多路信号 + 回测校验 |
| reviewer | —（HITL 卡点） | integrator | 报告前暂停人工确认 |
| reporter | report, notify | reviewer | 生成日/周报告 + 推送 |

## 委派图（DAG 边 = roles.py 的 runs_after）

```
collector → extractor → analyst → integrator → reviewer → reporter
```

## 并行

- analyst 的 `burst` / `tkg` / `forecast` 三个子任务可 fan-out 并行
  （底层 predict 已按 `_run_burst/_run_tkg/_run_forecast/_run_fusion` 隔离，各自 try/except 不互阻，无共享状态冲突）。

## HITL 卡点

- reviewer：`review_enable_hitl=true` 且 `review_auto_approve=false` 时暂停，
  写 `output/review_request.json` 等待 `output/review_approve.json`。
