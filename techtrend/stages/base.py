"""阶段抽象基类：P1–P6 各阶段实现统一入口。"""
from abc import ABC, abstractmethod

from techtrend.config import Settings


class Stage(ABC):
    """pipeline 中的一个阶段。子类需设 `name` 并实现 `run()`。"""

    name: str = "base"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @abstractmethod
    def run(self) -> dict:
        """执行本阶段，返回结果摘要 dict。"""
