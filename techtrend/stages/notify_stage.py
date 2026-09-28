"""通知阶段（P5，第 8 阶段）：把产出报告推到配置的渠道。

notify_enable=false（默认，手动 main.py）时返回 skipped:true 不阻断；
cron 无人值守开 true 才推。读 output/<notify_report> → push_report。
"""
import logging

from techtrend.orchestration.notify import push_report
from techtrend.stages.base import Stage

log = logging.getLogger(__name__)


class NotifyStage(Stage):
    name = "notify"

    def run(self) -> dict:
        s = self.settings
        if not s.notify_enable:
            return {"stage": self.name, "status": "ok", "skipped": True, "reason": "notify_enable=false"}

        report_path = s.output_dir / s.notify_report
        if not report_path.exists():
            log.warning("%s 不存在，notify 跳过（先跑 report）", report_path)
            return {"stage": self.name, "status": "error", "error": f"{report_path} 不存在"}

        text = report_path.read_text(encoding="utf-8")
        channels = [c.strip() for c in s.notify_channels.split(",") if c.strip()]
        results = push_report(s, text, channels)
        log.info("notify 完成：%s", results)
        return {"stage": self.name, "status": "ok", "channels": results}
