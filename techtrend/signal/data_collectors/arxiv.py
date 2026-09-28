"""arXiv API collector for preprint publication counts.

arXiv is completely free, no API key required. The API returns Atom 1.0 XML
(not JSON), so this collector cannot inherit from ``MonthCountCollector`` and
implements its own ``collect()`` with XML parsing.

Uses ``search_query`` with date range filtering and ``max_results=0`` to read
``<opensearch:totalResults>`` from the Atom feed, getting a count without
downloading any records.

Rate limiting: arXiv recommends a 3-second delay between consecutive calls.
The ``PoliteApiClient`` handles this via ``min_interval_seconds``.

Date format: arXiv uses ``YYYYMMDDHHMM`` (e.g., ``202501010000``).
"""

from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from typing import Any

from techtrend.signal.config import PipelineConfig, generate_monthly_windows, month_range
from techtrend.signal.data_collectors.base import register
from techtrend.signal.http_client import PoliteApiClient, CachedResponse

ARXIV_BASE_URL = "http://export.arxiv.org/api/query"

# XML namespace constants
NS_OPENSEARCH = "http://a9.com/-/spec/opensearch/1.1/"


def _date_to_arxiv_format(date_str: str) -> str:
    """Convert YYYY-MM-DD to arXiv datetime format YYYYMMDDHHMMSS.

    For start dates: 000000 (beginning of day)
    For end dates: 235959 (end of day)
    """
    clean = date_str.replace("-", "")
    if len(clean) == 8:
        return clean + "000000"
    return clean


def _build_search_query(topic_query: str, date_start: str, date_end: str) -> str:
    """Build arXiv search_query string with topic keywords and date range.

    arXiv query syntax:
    - ``all:keyword`` searches all fields
    - ``submittedDate:[YYYYMMDDHHMMSS TO YYYYMMDDHHMMSS]`` filters by date
    - Combined with ``AND``

    For multi-word queries like ``"large language model" OR LLM``, we wrap
    the whole expression in ``all:(...)``.
    """
    start_arxiv = _date_to_arxiv_format(date_start)
    end_arxiv = _date_to_arxiv_format(date_end)
    # Wrap topic query in all:() for field search, combined with date filter
    return f"all:({topic_query}) AND submittedDate:[{start_arxiv} TO {end_arxiv}]"


def _parse_total_results(xml_text: str) -> int:
    """Extract <opensearch:totalResults> from arXiv Atom XML response.

    Args:
        xml_text: Raw XML response body.

    Returns:
        Total result count as int, or 0 if parsing fails.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return 0

    # Try with namespace
    total_elem = root.find(f"{{{NS_OPENSEARCH}}}totalResults")
    if total_elem is not None and total_elem.text:
        return int(total_elem.text)

    # Fallback: search for any element named totalResults
    for elem in root.iter():
        if "totalResults" in elem.tag and elem.text:
            try:
                return int(elem.text)
            except ValueError:
                continue
    return 0


@register("arxiv")
class ArxivCollector:
    """Monthly preprint-count collector for arXiv API."""

    source_name = "arxiv"

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
        arxiv_settings = dict(http_settings)
        arxiv_settings["min_interval_seconds"] = max(
            float(arxiv_settings.get("min_interval_seconds", 3.0)), 3.0
        )
        
        records: list[dict[str, Any]] = []

        async with PoliteApiClient(cache_dir, arxiv_settings) as client:
            tasks = []
            for topic in cfg.topics:
                query = self._get_topic_query(topic)
                for w_start, w_end in windows:
                    date_start, date_end = month_range(w_start)
                    search_query = _build_search_query(query, date_start, date_end)
                    params = {
                        "search_query": search_query,
                        "start": 0,
                        "max_results": 0,
                    }
                    cache_key = f"arxiv_{topic.topic_id}_{w_start}_{w_end}"
                    tasks.append(self._fetch_single(client, topic, w_start, w_end, params, cache_key))
            
            results = await asyncio.gather(*tasks)
            records.extend(results)

        return records

    async def _fetch_single(self, client: PoliteApiClient, topic: Any, w_start: str, w_end: str, params: dict[str, Any], cache_key: str) -> dict[str, Any]:
        try:
            response = await client.get_json(ARXIV_BASE_URL, params, cache_key=cache_key)
        except Exception as exc:
            return self._failed_record(topic, w_start, w_end, exc)

        if isinstance(response.payload, dict) and "_non_json_body" in response.payload:
            xml_text = response.payload["_non_json_body"]
            count = _parse_total_results(xml_text)
            return {
                "source": self.source_name,
                "topic_id": topic.topic_id,
                "topic_label": topic.topic_label,
                "window_start": w_start,
                "window_end": w_end,
                "activity_count": count,
                "collection_status": "ok",
                "collected_at": response.fetched_at,
                "cached": response.cache_hit,
            }
        else:
            return self._failed_record(
                topic, w_start, w_end,
                RuntimeError("expected XML response from arXiv, got JSON"),
            )

    def _get_topic_query(self, topic: Any) -> str:
        """Pick the right query string from the topic config."""
        # arXiv query uses the same format as openalex_query
        return getattr(topic, "arxiv_query", "") or topic.openalex_query

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
