"""可视化包（P6）：纯渲染，零重算。

只读 output/*.json/csv + interim 聚合，不 import torch/pykeen、不碰 Neo4j、不发网络请求。
"""
from techtrend.viz.svg import col_chart, hbar_chart, line_chart

__all__ = ["line_chart", "hbar_chart", "col_chart"]
