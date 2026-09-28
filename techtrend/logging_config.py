"""统一日志：控制台 + 按天轮转的日志文件。"""
import logging
import logging.handlers
import sys
from pathlib import Path

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"


def _reconfigure_stdout_utf8() -> None:
    """Windows 下把控制台输出切到 UTF-8，避免中文乱码。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def setup_logging(level: str = "INFO", log_dir: Path = Path("logs")) -> logging.Logger:
    """配置并返回 root logger；可重复调用（幂等）。"""
    _reconfigure_stdout_utf8()
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    if root.handlers:  # 已配置过，直接返回
        return root

    root.setLevel(level.upper())
    # 抑制第三方库 INFO 日志：httpx 会打印完整请求 URL（含 query 里的 api_key 等敏感参数）；
    # neo4j 驱动每个 CREATE CONSTRAINT 都发一条 notification，也很吵。
    for noisy in ("httpx", "httpcore", "urllib3", "neo4j"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FMT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_dir / "pipeline.log", when="midnight", backupCount=7, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    return root
