"""定时调度入口（P5 落地）。hermes-agent cronjob 与 APScheduler 都触发此入口。

用法：
    python cron.py                        # daily 增量（默认），走 runbook
    python cron.py --mode daily --notify  # 每日无人值守：增量 + 推送报告
    python cron.py --mode full            # 手动全量，等价 main.py（--stage/--list 兼容）
    python cron.py --mode weekly          # 生成周报（聚合最近 N 天 manifest + 四目标指标）
    python cron.py --dry-run              # 只打印角色→阶段顺序 + 角色标签，不落库
    python cron.py --auto-approve         # 覆盖 review_auto_approve=false（无人值守保险）

与 main.py 分工：main.py = 手动全量 8 阶段 CLI；cron.py = 无人值守统一入口，
daily 走 orchestration.runbook（角色化 + 短路守卫 + HITL + manifest），full 复用 main.run_full。
"""
import argparse
import logging

from techtrend.config import get_settings
from techtrend.logging_config import setup_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="每日无人值守调度入口（P5/P6：runbook 增量 / main.py 全量 / 周报）")
    parser.add_argument("--mode", choices=["daily", "full", "weekly"], default="daily",
                        help="daily=runbook 增量（默认）；full=main.py 全量 pipeline；weekly=生成周报")
    parser.add_argument("--notify", action="store_true", help="临时开推送（覆盖 notify_enable=false）")
    parser.add_argument("--dry-run", action="store_true", help="只打印角色→阶段顺序，不实际跑、不落库")
    parser.add_argument("--auto-approve", action="store_true", help="覆盖 review_auto_approve=false")
    parser.add_argument("--stage", metavar="NAME", help="仅 full 模式：只运行指定阶段（如 collect）")
    parser.add_argument("--list", action="store_true", help="列出全部阶段名后退出")
    return parser


def _print_dry_run(settings, mode: str) -> None:
    if mode == "daily":
        from techtrend.orchestration.roles import ROLES

        print("[dry-run] daily 模式：角色 → 阶段（不落库）")
        for role in ROLES:
            stages = list(role.stages)
            if not stages and role.human_checkpoint:
                stages = ["(HITL checkpoint)"]
            extra = []
            if role.needs_llm:
                extra.append("needs_llm")
            if role.parallel_subtasks:
                extra.append(f"parallel={','.join(role.parallel_subtasks)}")
            note = f"  [{', '.join(extra)}]" if extra else ""
            print(f"  {role.name:<10} {role.desc}")
            print(f"           stages={stages}  runs_after={list(role.runs_after)}{note}")
    else:
        from techtrend.stages import get_default_stages

        print("[dry-run] full 模式：阶段顺序（不落库）")
        for s in get_default_stages(settings):
            print(f"  {s.name}")


def run() -> int:
    args = build_parser().parse_args()

    settings = get_settings()
    setup_logging(level=settings.log_level, log_dir=settings.log_dir)
    log = logging.getLogger("cron")

    # 临时覆盖（无人值守 / 交互演示用）
    if args.notify:
        settings.notify_enable = True
    if args.auto_approve:
        settings.review_auto_approve = True

    if args.dry_run:
        _print_dry_run(settings, args.mode)
        return 0

    if args.list:
        from techtrend.stages import get_default_stages

        for s in get_default_stages(settings):
            print(s.name)
        return 0

    if args.stage and args.mode != "full":
        log.error("--stage 仅 full 模式可用（当前 --mode %s）", args.mode)
        return 2

    if args.mode == "weekly":
        from techtrend.viz.weekly import build_weekly_report

        report = build_weekly_report(settings)
        log.info("周报完成：%s（%d 次运行）", report.get("report_file"), report.get("n_runs", 0))
        return 0 if report.get("status") == "ok" else 1

    if args.mode == "full":
        from main import run_full

        return run_full(args, settings)

    from techtrend.orchestration.runbook import run_daily

    manifest = run_daily(settings)
    log.info(
        "run_daily 完成：run_id=%s status=%s noop=%s",
        manifest.get("run_id"), manifest.get("status"), manifest.get("noop"),
    )
    return 0 if manifest.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(run())
