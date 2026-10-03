"""Pipeline 编排：按序执行各阶段，收集结果摘要。"""
import logging

from techtrend.config import Settings
from techtrend.stages import get_default_stages
from techtrend.storage import snapshot_outputs

log = logging.getLogger(__name__)


class Pipeline:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.stages = get_default_stages(settings)

    def run(self) -> list[dict]:
        snapshot_outputs(self.settings.output_dir, "full_pipeline")
        log.info("=== pipeline 启动（P4 验证体系：定向 TKG 外推 + walk-forward 回测）===")
        results: list[dict] = []
        for stage in self.stages:
            log.info("→ 进入阶段 [%s]", stage.name)
            result = stage.run()
            results.append(result)
            if result.get("status") == "error":
                log.error("阶段 [%s] 失败，停止下游；避免使用不完整或过期输入", stage.name)
                break
        log.info("=== pipeline 完成，共 %d 个阶段 ===", len(results))
        return results
