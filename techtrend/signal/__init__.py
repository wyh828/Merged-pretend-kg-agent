"""techtrend.signal —— 信号引擎子包（来自 Predictive Agents / pretend-agent）。

相对注意力份额 + EMA/MACD 动量 + 排序回测路线，作为命名空间隔离的子包并入
主干 tech-trend-kg-agents（`signal.config` vs `techtrend.config`，避免同名模块冲突）。

组成：
- :mod:`techtrend.signal.http_client`  —— PoliteApiClient：SQLite 缓存 + 限速 + 指数退避（async）
- :mod:`techtrend.signal.processors`     —— 清洗 / 异常检测 / 标准化（特征工程前置）
- :mod:`techtrend.signal.agents`         —— 采集 / 分析 / 研报（DeepSeek 直连）角色
- :mod:`techtrend.signal.configs`        —— topics.yaml / sources.yaml 话题与源配置层
"""

from techtrend.signal.config import (
    PipelineConfig,
    TopicConfig,
    ensure_dirs,
    generate_monthly_windows,
    load_pipeline_config,
    load_topics,
    load_yaml_config,
    month_range,
)
from techtrend.signal.http_client import (
    CachedResponse,
    DEFAULT_HTTP_SETTINGS,
    PoliteApiClient,
    RateLimitedError,
)

__all__ = [
    "PipelineConfig",
    "TopicConfig",
    "ensure_dirs",
    "generate_monthly_windows",
    "load_pipeline_config",
    "load_topics",
    "load_yaml_config",
    "month_range",
    "PoliteApiClient",
    "CachedResponse",
    "RateLimitedError",
    "DEFAULT_HTTP_SETTINGS",
]
