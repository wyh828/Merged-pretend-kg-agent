"""角色定义（P5 单一事实来源）。

6 个角色化的 agent 职责定义。hermes-agent 的 agent/skill 与降级层的 runbook
都从这里派生，避免「两套角色定义各写一遍」漂移（PROJECT_PLAN §六 决策 #2）。

多智能体是编排层叙事，不是底层 pipeline 结构：底层是 8+1 阶段串行
（collect/extract/align/build_graph/predict/report/evaluate/notify/visualize）；
角色化 agent 是 hermes-agent 顶层的委派单位，降级时同一 runbook 串行执行、
但每一步仍打角色标签 + 独立 summary（审查要点 #9）。
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Role:
    name: str
    desc: str
    stages: tuple[str, ...] = ()              # 负责的底层阶段名
    runs_after: tuple[str, ...] = ()          # 角色级依赖（DAG 边，供 hermes-agent 委派）
    needs_llm: bool = False
    parallel_subtasks: tuple[str, ...] = ()   # 可并行的子任务（analyst 的 burst/tkg/forecast）
    human_checkpoint: bool = False


ROLES: tuple[Role, ...] = (
    Role("collector", "采集 agent：调度/监控各源每日增量",
         stages=("collect",)),
    Role("extractor", "抽取 agent：LLM 抽实体/关系并写入 Neo4j",
         stages=("extract", "align", "build_graph"), runs_after=("collector",), needs_llm=True),
    Role("analyst", "分析 agent：突发/时序外推/回归（可并行）",
         stages=("predict",), runs_after=("extractor",),
         parallel_subtasks=("burst", "tkg", "forecast")),
    Role("integrator", "预测/集成 agent：融合多路信号 + 回测校验",
         stages=("predict", "evaluate"), runs_after=("analyst",)),
    Role("reviewer", "审校 agent：报告前暂停人工确认（HITL）",
         stages=(), runs_after=("integrator",), human_checkpoint=True),
    Role("reporter", "报告 agent：生成日/周报告 + 仪表盘 + 推送",
         stages=("report", "notify", "visualize"), runs_after=("reviewer",)),
)


ROLE_BY_NAME: dict[str, Role] = {r.name: r for r in ROLES}

# 阶段名 → 首个负责该阶段的角色名（串行降级模式下的打标归属）。
# predict 在 analyst 与 integrator 都有声明（分析子任务 vs 融合），串行只跑一次，
# 归首个声明者 analyst；integrator 实际落到 evaluate（回测）。与 roles.py 无重复定义。
STAGE_ROLE: dict[str, str] = {}
for _role in ROLES:
    for _stage in _role.stages:
        STAGE_ROLE.setdefault(_stage, _role.name)


__all__ = ["Role", "ROLES", "ROLE_BY_NAME", "STAGE_ROLE"]
