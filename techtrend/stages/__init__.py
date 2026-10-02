"""阶段注册：按 pipeline 执行顺序返回默认阶段列表（P6 九阶段）。"""
from techtrend.config import Settings
from techtrend.stages.align import AlignStage
from techtrend.stages.base import Stage
from techtrend.stages.build_graph import BuildGraphStage
from techtrend.stages.collaborate import CollaborateStage
from techtrend.stages.collect import CollectStage
from techtrend.stages.evaluate import EvaluateStage
from techtrend.stages.extract import ExtractStage
from techtrend.stages.notify_stage import NotifyStage
from techtrend.stages.predict import PredictStage
from techtrend.stages.report import ReportStage
from techtrend.stages.visualize import VisualizeStage


def get_default_stages(settings: Settings) -> list[Stage]:
    """返回按执行顺序排列的阶段实例（第 9 阶段 visualize 在末尾，含四目标仪表盘 + 周报）。"""
    return [
        CollectStage(settings),
        ExtractStage(settings),
        AlignStage(settings),
        BuildGraphStage(settings),
        PredictStage(settings),
        EvaluateStage(settings),
        CollaborateStage(settings),
        ReportStage(settings),
        NotifyStage(settings),
        VisualizeStage(settings),
    ]


__all__ = ["get_default_stages", "Stage"]
