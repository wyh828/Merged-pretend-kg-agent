"""项目入口：`python main.py` 按配置顺序运行各阶段。

用法：
    python main.py                 # 跑全部阶段
    python main.py --stage <name>  # 只跑某个阶段
    python main.py --list          # 列出全部阶段名
"""
import argparse
import logging

from techtrend.config import get_settings
from techtrend.logging_config import setup_logging
from techtrend.pipeline import Pipeline
from techtrend.stages import get_default_stages
from techtrend.storage import snapshot_outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="技术趋势预测系统 pipeline（P4 验证体系：定向 TKG 外推 + walk-forward 回测）")
    parser.add_argument("--stage", metavar="NAME", help="只运行指定阶段（如 collect）")
    parser.add_argument("--list", action="store_true", help="列出全部阶段名后退出")
    return parser


def run() -> int:
    args = build_parser().parse_args()

    settings = get_settings()
    setup_logging(level=settings.log_level, log_dir=settings.log_dir)

    return run_full(args, settings)


def run_full(args, settings) -> int:
    """执行全量 pipeline（--list / --stage / 全跑）。供 main.py 与 cron.py --mode full 复用。"""
    log = logging.getLogger("main")
    stages = get_default_stages(settings)

    if args.list:
        for s in stages:
            print(s.name)
        return 0

    if args.stage:
        stage = next((s for s in stages if s.name == args.stage), None)
        if stage is None:
            log.error("未知阶段：%s（可用 --list 查看）", args.stage)
            return 1
        log.info("单阶段运行：%s", stage.name)
        snapshot_outputs(settings.output_dir, f"stage:{stage.name}")
        result = stage.run()
        return 1 if result.get("status") == "error" else 0

    pipeline = Pipeline(settings)
    results = pipeline.run()
    return 1 if any(r.get("status") == "error" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(run())
