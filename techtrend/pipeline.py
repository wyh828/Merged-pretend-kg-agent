"""Pipeline 编排：按序执行各阶段，收集结果摘要。"""
import logging

from techtrend.config import Settings
from techtrend.stages import get_default_stages

log = logging.getLogger(__name__)


class Pipeline:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.stages = get_default_stages(settings)

    def run(self) -> list[dict]:
        log.info("=== pipeline 启动（P4 验证体系：定向 TKG 外推 + walk-forward 回测）===")
        results: list[dict] = []
        for stage in self.stages:
            log.info("→ 进入阶段 [%s]", stage.name)
            results.append(stage.run())
        log.info("=== pipeline 完成，共 %d 个阶段 ===", len(results))
        return results
