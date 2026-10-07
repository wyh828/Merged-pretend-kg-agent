"""USPTO patent application collector.

USPTO provides patent data through two APIs:
1. Open Data Portal (ODP) API: official, requires USPTO.gov account + ID.me verification
2. PatentSearch API (ElasticSearch-based): newer, replaces legacy PatentsView API

Both require a free API key (passed via X-API-KEY header) and enforce a rate limit
of 45 requests per minute.

For a monthly count, we use the Patent Applications Search endpoint with a
date range filter and limit=0 to get only the total count without downloading
records.

ODP endpoint (GET):
  https://api.uspto.gov/api/v1/patent/applications/search
  Headers: X-API-KEY: {key}
  Query params: q (search), dateRangeData.startDate, dateRangeData.endDate

PatentSearch endpoint (POST):
  https://search.patentsview.org/api/v1/patent/search
  Headers: X-API-KEY: {key}
  Body: {"q": "...", "filters": {"app_date": ["2024-01-01", "2024-01-31"]}}

Due to ID.me verification requirement for ODP access (as of 2026-06-18),
the PatentSearch API is recommended for projects without USPTO.gov accounts.
"""

from __future__ import annotations

import os
import asyncio
from typing import Any

from techtrend.signal.config import PipelineConfig, generate_monthly_windows, month_range
from techtrend.signal.data_collectors.base import register
from techtrend.signal.http_client import PoliteApiClient, CachedResponse

ODP_BASE_URL = "https://api.uspto.gov/api/v1/patent/applications/search"
PATENTSEARCH_BASE_URL = "https://search.patentsview.org/api/v1/patent/search"


def _build_odp_params(query: str, date_start: str, date_end: str) -> dict[str, str]:
    """Build ODP API query parameters."""
    return {
        "q": query,
        "dateRangeData.startDate": date_start,
        "dateRangeData.endDate": date_end,
        "start": "0",
        "limit": "0",  # Count only, no records
    }


def _build_patentsearch_body(query: str, date_start: str, date_end: str) -> dict[str, Any]:
    """Build PatentSearch API request body."""
    return {
        "q": query,
        "filters": {
            "app_date": [date_start, date_end],
        },
        "page": 0,
        "per_page": 0,  # Count only
    }


def _parse_odp_count(response: CachedResponse) -> int:
    """Extract total count from ODP API response."""
    if not isinstance(response.payload, dict):
        return 0
    query_status = response.payload.get("queryStatus", {})
    return int(query_status.get("totalResults", 0))


def _parse_patentsearch_count(response: CachedResponse) -> int:
    """Extract total count from PatentSearch API response."""
    if not isinstance(response.payload, dict):
        return 0
    return int(response.payload.get("total_patent_count", 0))


@register("uspto")
class UsptoCollector:
    """Monthly patent-application-count collector for USPTO APIs."""

    source_name = "uspto"

    async def collect(
        self,
        cfg: PipelineConfig,
        http_settings: dict[str, Any],
        source_cfg: dict[str, Any],
    ) -> list[dict[str, Any]]:
        windows = generate_monthly_windows(cfg.start_date, cfg.end_date)
        if not windows:
            return []

        # Choose API endpoint: ODP or PatentSearch
        api_mode = source_cfg.get("api_mode", "patentsearch")  # "odp" or "patentsearch"
        if api_mode == "odp":
            base_url = ODP_BASE_URL
            parse_count = _parse_odp_count
        else:
            base_url = PATENTSEARCH_BASE_URL
            parse_count = _parse_patentsearch_count

        # Get API key from environment or config
        api_key = os.getenv("USPTO_API_KEY", source_cfg.get("api_key", ""))
        if not api_key:
            # Return failed records for all windows if no API key
            return self._all_failed_records(cfg, windows, "USPTO_API_KEY not set")

        cache_dir = cfg.raw_api_path / self.source_name
        # USPTO rate limit: 45 req/min ≈ 1.33 sec between requests
        uspto_settings = dict(http_settings)
        uspto_settings["min_interval_seconds"] = max(
            float(uspto_settings.get("min_interval_seconds", 1.5)), 1.5
        )
        client = PoliteApiClient(cache_dir, uspto_settings)

        await client.__aenter__()

        records: list[dict[str, Any]] = []

        for topic in cfg.topics:
            query = self._get_topic_query(topic)
            for w_start, w_end in windows:
                date_start, date_end = month_range(w_start)
                cache_key = f"uspto_{topic.topic_id}_{w_start}_{w_end}"

                try:
                    if api_mode == "odp":
                        params = _build_odp_params(query, date_start, date_end)
                        headers = {"X-API-KEY": api_key}
                        response = await client.get_json(
                            base_url,
                            params,
                            cache_key=cache_key,
                            extra_headers=headers,
                        )
                    else:
                        body = _build_patentsearch_body(query, date_start, date_end)
                        headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
                        response = await client.post_json(
                            base_url,
                            body,
                            cache_key=cache_key,
                            extra_headers=headers,
                        )
                except Exception as exc:  # noqa: BLE001 - preserve partial progress
                    records.append(self._failed_record(topic, w_start, w_end, exc))
                    continue

                if isinstance(response.payload, dict) and "_non_json_body" in response.payload:
                    records.append(self._failed_record(
                        topic, w_start, w_end,
                        RuntimeError(f"non-JSON response: {response.payload['_non_json_body'][:120]}"),
                    ))
                    continue

                count = parse_count(response)
                records.append({
                    "source": self.source_name,
                    "topic_id": topic.topic_id,
                    "topic_label": topic.topic_label,
                    "window_start": w_start,
                    "window_end": w_end,
                    "activity_count": count,
                    "collection_status": "ok",
                    "collected_at": response.fetched_at,
                    "cached": response.cache_hit,
                })

        await client.__aexit__(None, None, None)
        return records

    def _get_topic_query(self, topic: Any) -> str:
        """Pick the right query string from the topic config."""
        return getattr(topic, "uspto_query", "") or topic.openalex_query

    def _failed_record(self, topic: Any, w_start: str, w_end: str, exc: Exception) -> dict[str, Any]:
        from datetime import datetime
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

    def _all_failed_records(self, cfg: PipelineConfig, windows: list[tuple[str, str]], error_msg: str) -> list[dict[str, Any]]:
        """Generate failed records for all windows when API key is missing."""
        from datetime import datetime
        records: list[dict[str, Any]] = []
        for topic in cfg.topics:
            for w_start, w_end in windows:
                records.append({
                    "source": self.source_name,
                    "topic_id": topic.topic_id,
                    "topic_label": topic.topic_label,
                    "window_start": w_start,
                    "window_end": w_end,
                    "activity_count": None,
                    "collection_status": "failed",
                    "collected_at": datetime.utcnow().isoformat() + "Z",
                    "cached": False,
                    "error": error_msg,
                })
        return records
