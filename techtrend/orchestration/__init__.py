"""编排层（P5）：调度器无关的每日运行手册、角色定义、报告推送、降级调度。

与底层 pipeline 解耦：本包只依赖底层 Stage 与 config，不 import 任何调度器；
hermes-agent cron 与 APScheduler 都只负责「定时触发 cron.py」，业务代码不感知调度来源。
"""
from techtrend.orchestration.roles import ROLE_BY_NAME, ROLES, Role

__all__ = ["Role", "ROLES", "ROLE_BY_NAME"]
