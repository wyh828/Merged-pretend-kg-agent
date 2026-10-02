"""Source collector interface and registry.

Every data source implements :class:`SourceCollector` so that
``DataCollectionAgent`` can iterate sources purely from ``sources.yaml``
configuration instead of hardcoding per-source branches.

A collector receives:
- ``cfg``: the validated :class:`~config.PipelineConfig`
- ``http_settings``: the ``http`` section of ``sources.yaml`` (or defaults)
- ``source_cfg``: the per-source section of ``sources.yaml`` (e.g. mailto,
  k_new, language_whitelist)

and returns a list of activity records. Each record MUST carry:

- ``source``: short source name (``"crossref"`` etc.)
- ``topic_id`` / ``topic_label``
- ``window_start`` / ``window_end`` (YYYY-MM for academic/news, YYYY-MM-DD for
  daily snapshots)
- ``activity_count``: int or ``None`` when the request failed
- ``collection_status``: ``"ok"`` or ``"failed"``
- ``collected_at``: ISO timestamp
- ``error``: present only when ``collection_status == "failed"``
- ``cached``: bool, whether the value came from cache
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from techtrend.signal.config import PipelineConfig, generate_monthly_windows, month_range
from techtrend.signal.http_client import PoliteApiClient, CachedResponse


@runtime_checkable
class SourceCollector(Protocol):
    """Unified interface for every data source collector."""

    source_name: str

    async def collect(
        self,
        cfg: PipelineConfig,
        http_settings: dict[str, Any],
        source_cfg: dict[str, Any],
    ) -> list[dict[str, Any]]:
        ...

_COLLECTORS: dict[str, type[SourceCollector]] = {}

def register(name: str):
    def decorator(cls: type[SourceCollector]) -> type[SourceCollector]:
        _COLLECTORS[name] = cls
        return cls
    return decorator

def get_collector_class(name: str) -> type[SourceCollector]:
    if name not in _COLLECTORS:
        raise ValueError(f"Unknown collector: {name}")
    return _COLLECTORS[name]

class MonthCountCollector:
    """Base class for sources that query API for count per month window."""

    source_name: str
    base_url: str

    async def collect(
        self,
        cfg: PipelineConfig,
        http_settings: dict[str, Any],
        source_cfg: dict[str, Any],
    ) -> list[dict[str, Any]]:
        windows = generate_monthly_windows(cfg.start_date, cfg.end_date)
        if not windows:
            return []

        cache_dir = cfg.raw_api_path / self.source_name
        contact = self.resolve_contact(source_cfg)
        records: list[dict[str, Any]] = []

        async with PoliteApiClient(cache_dir, http_settings) as client:
            tasks = []
            for topic in cfg.topics:
                query = self.get_topic_query(topic)
                for w_start, w_end in windows:
                    date_start, date_end = month_range(w_start)
                    params = self.build_params(query, date_start, date_end, contact)
                    cache_key = f"{self.source_name}_{topic.topic_id}_{w_start}_{w_end}"
                    tasks.append(self._fetch_single(client, topic, w_start, w_end, params, cache_key))
            
            results = await asyncio.gather(*tasks)
            records.extend(results)

        return records

    async def _fetch_single(self, client: PoliteApiClient, topic: Any, w_start: str, w_end: str, params: dict[str, Any], cache_key: str) -> dict[str, Any]:
        try:
            response = await client.get_json(self.base_url, params, cache_key=cache_key)
        except Exception as exc:
            return self._failed_record(topic, w_start, w_end, exc)

        if isinstance(response.payload, dict) and "_non_json_body" in response.payload:
            return self._failed_record(
                topic, w_start, w_end,
                RuntimeError(f"non-JSON response: {response.payload['_non_json_body'][:120]}"),
            )

        return {
            "source": self.source_name,
            "topic_id": topic.topic_id,
            "topic_label": topic.topic_label,
            "window_start": w_start,
            "window_end": w_end,
            "activity_count": self.parse_count(response),
            "collection_status": "ok",
            "collected_at": response.fetched_at,
            "cached": response.cache_hit,
        }

    # --- Hooks: subclasses override these 4 ---

    def build_params(self, query: str, date_start: str, date_end: str, contact: str) -> dict[str, Any]:
        """Assemble the API query parameters for one (topic, month) request."""
        raise NotImplementedError

    def parse_count(self, response: CachedResponse) -> int:
        """Extract the activity count from a successful API response."""
        raise NotImplementedError

    def resolve_contact(self, source_cfg: dict[str, Any]) -> str:
        """Return the polite-pool contact email (or empty string if N/A)."""
        return ""

    def get_topic_query(self, topic: Any) -> str:
        """Pick the right query string from the topic config. Default: openalex_query."""
        return topic.openalex_query

    # --- Shared helper ---

    def _failed_record(self, topic: Any, w_start: str, w_end: str, exc: Exception) -> dict[str, Any]:
        return {
            "source": self.source_name,
            "topic_id": topic.topic_id,
            "topic_label": topic.topic_label,
            "window_start": w_start,
            "window_end": w_end,
            "activity_count": None,
            "collection_status": "failed",
            "collected_at": datetime.utcnow().isoformat() + "Z",
            "cached": False,
            "error": str(exc),
        }
