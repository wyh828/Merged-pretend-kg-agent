"""降级调度入口（Plan B）：hermes-agent 不可用时的 APScheduler 常驻调度。

用法：
    F:\\Predictive agents\\.venv\\Scripts\\python.exe -m techtrend.orchestration.scheduler --once   # 单次触发测试
    F:\\Predictive agents\\.venv\\Scripts\\python.exe -m techtrend.orchestration.scheduler          # 常驻（需 SCHEDULE_ENABLE=true）

用 subprocess 而非 import 跑 cron.py：与 hermes-agent cron 触发方式完全同构
（都是「外部进程触发同一入口」），保证两条路径行为逐字节一致。

python 解释器：默认 sys.executable（= 用正确解释器启动本模块时即为 conda python）；
也可 --python 显式指定。见 memory [[python-interpreter-path]]，不要用坏掉的 `python` 桩。
"""
import argparse
import logging
import subprocess
import sys

from techtrend.config import PROJECT_ROOT, get_settings
from techtrend.logging_config import setup_logging

log = logging.getLogger(__name__)


def build_scheduler(settings):
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "缺少 apscheduler（pip install apscheduler），或改用 hermes-agent cron 作主调度"
        ) from exc

    scheduler = BlockingScheduler(timezone=settings.schedule_timezone)
    trigger = CronTrigger.from_crontab(settings.schedule_cron, timezone=settings.schedule_timezone)

    def _job() -> None:
        cmd = [sys.executable, str(PROJECT_ROOT / "cron.py"), "--mode", "daily", "--notify"]
        log.info("APScheduler 触发：%s", " ".join(cmd))
        proc = subprocess.run(cmd, cwd=PROJECT_ROOT)
        log.info("cron.py 退出码 %d", proc.returncode)

    scheduler.add_job(_job, trigger, id="techtrend_daily", replace_existing=True)
    return scheduler


def _fire_once(python: str | None) -> int:
    exe = python or sys.executable
    cmd = [exe, str(PROJECT_ROOT / "cron.py"), "--mode", "daily", "--notify"]
    log.info("单次触发：%s", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT)
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="APScheduler 降级调度（Plan B）")
    parser.add_argument("--once", action="store_true", help="立即触发一次 job 后退出（测试用）")
    parser.add_argument("--python", default=None, help="底层 python 解释器路径（默认 sys.executable）")
    args = parser.parse_args()

    settings = get_settings()
    setup_logging(level=settings.log_level, log_dir=settings.log_dir)

    if args.once:
        return _fire_once(args.python)

    if not settings.schedule_enable:
        log.error(
            "SCHEDULE_ENABLE=false：内置 APScheduler 未启用（hermes-agent 接管时关）。"
            "用 --once 单次触发，或设 SCHEDULE_ENABLE=true 起常驻调度。"
        )
        return 1

    scheduler = build_scheduler(settings)
    log.info(
        "APScheduler 启动：cron=%s tz=%s（Ctrl-C 停止）",
        settings.schedule_cron, settings.schedule_timezone,
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("调度停止")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
