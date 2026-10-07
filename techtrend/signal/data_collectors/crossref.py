"""CrossRef Works API collector.

Uses a single request per (topic, month) window with rows=1 to read
``message.total-results``, which gives the publication count without
pagination. This avoids the OpenAlex group_by emptiness and credits paywall.

The per-month loop, caching, retry, and failure handling are inherited from
:class:`~data_collectors.base.MonthCountCollector`. This file only defines the
4 CrossRef-specific hooks.
"""

from __future__ import annotations

import os
from typing import Any

from techtrend.signal.data_collectors.base import register, MonthCountCollector
from techtrend.signal.http_client import CachedResponse

CROSSREF_BASE_URL = "https://api.crossref.org/works"


@register("crossref")
class CrossrefCollector(MonthCountCollector):
    """Monthly publication-count collector for CrossRef Works API."""

    source_name = "crossref"
    base_url = CROSSREF_BASE_URL

    def build_params(self, query: str, date_start: str, date_end: str, contact: str) -> dict[str, Any]:
        params = {
            "query": query,
            "filter": f"from-pub-date:{date_start},until-pub-date:{date_end}",
            "rows": 1,
        }
        if contact:
            params["mailto"] = contact
        return params

    def parse_count(self, response: CachedResponse) -> int:
        message = response.payload.get("message", {}) if isinstance(response.payload, dict) else {}
        value = message.get("total-results")
        if type(value) is not int or value < 0:
            raise ValueError("Crossref response lacks a valid total-results")
        return value

    def resolve_contact(self, source_cfg: dict[str, Any]) -> str:
        env_name = source_cfg.get("mailto_env", "CROSSREF_MAILTO")
        return os.getenv(env_name, source_cfg.get("mailto", ""))

    def get_topic_query(self, topic: Any) -> str:
        return topic.crossref_query or topic.openalex_query
