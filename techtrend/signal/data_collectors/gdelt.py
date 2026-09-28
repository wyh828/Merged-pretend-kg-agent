"""GDELT DOC 2.0 API collector.

Uses a single ``timelinevolraw`` request per topic to cover the entire date
range, then aggregates the daily timeline into monthly windows locally. This
minimises API calls and avoids rate-limiting.

Key robustness fixes vs. the old client:
- OR queries are auto-wrapped in parentheses (GDELT rejects
  ``a OR b`` at top level; it requires ``(a OR b)``).
- Non-JSON responses (GDELT plain-text errors) are detected via the
  ``_non_json_body`` wrapper from :class:`~http_client.PoliteApiClient` and
  recorded as ``collection_status == "failed"`` instead of being silently
  swallowed as empty data.
- Per-topic failures do not abort the whole run.
"""

from __future__ import annotations

from datetime import datetime
import asyncio
from typing import Any

from techtrend.signal.config import PipelineConfig, generate_monthly_windows
from techtrend.signal.data_collectors.base import register
from techtrend.signal.http_client import PoliteApiClient, CachedResponse

GDELT_BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


def normalize_gdelt_query(query: str) -> str:
    """Wrap top-level OR queries in parentheses.

    GDELT rejects queries like ``"AI agent" OR "AI agents"`` with
    ``"Queries containing OR'd terms must be surrounded by ()."``. If the
    query contains a top-level `` OR `` (i.e. not already enclosed in
    parentheses), wrap the whole thing in ``(...)``.

    Already-parenthesised queries are returned unchanged. Queries without
    `` OR `` are returned unchanged.
    """
    stripped = query.strip()
    if " OR " not in stripped:
        return stripped
    # Already fully wrapped in parentheses -> leave alone.
    if stripped.startswith("(") and stripped.endswith(")"):
        # Naive balance check on the outer wrap only.
        depth = 0
        for i, ch in enumerate(stripped):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and i != len(stripped) - 1:
                    # Closed before end -> outer parens are not the wrap.
                    break
        else:
            return stripped
    return f"({stripped})"


def _parse_gdelt_datetime(ym: str) -> str:
    """Convert YYYY-MM to GDELT datetime format YYYYMMDDHHMMSS."""
    return f"{ym.replace('-', '')}01000000"


def _extract_timeline(payload: Any) -> list[dict[str, Any]]:
    """Extract the data series from a GDELT timeline payload."""
    if not isinstance(payload, dict):
        return []
    timeline = payload.get("timeline", [])
    if not isinstance(timeline, list):
        return []
    for series in timeline:
        if isinstance(series, dict) and "data" in series:
            inner = series["data"]
            if isinstance(inner, list):
                return inner
    return []


def _parse_timeline_entry(entry: Any) -> tuple[str | None, int]:
    """Parse a timeline entry into (date_str, count)."""
    if not isinstance(entry, dict):
        return None, 0
    if "date" in entry and "value" in entry:
        return entry["date"], int(entry["value"])
    for key, val in entry.items():
        if isinstance(val, (int, float)):
            return key, int(val)
    return None, 0


def _gdelt_date_to_ym(date_str: str) -> str | None:
    """Convert GDELT datetime string to YYYY-MM."""
    if not date_str or len(date_str) < 6:
        return None
    clean = date_str.split("T")[0] if "T" in date_str else date_str
    if len(clean) < 6:
        return None
    try:
        year = clean[:4]
        month = clean[4:6]
        int(year)
        int(month)
        return f"{year}-{month}"
    except (ValueError, IndexError):
        return None


def _build_params(query: str, date_start: str, date_end: str) -> dict[str, Any]:
    return {
        "query": query,
        "mode": "timelinevolraw",
        "startdatetime": _parse_gdelt_datetime(date_start),
        "enddatetime": _parse_gdelt_datetime(date_end),
        "format": "json",
    }


@register("gdelt")
class GdeltCollector:
    """Monthly news-activity collector for GDELT DOC 2.0 timeline API."""

    async def collect(
        self,
        cfg: PipelineConfig,
        http_settings: dict[str, Any],
        source_cfg: dict[str, Any],
    ) -> list[dict[str, Any]]:
        windows = generate_monthly_windows(cfg.start_date, cfg.end_date)
        if not windows:
            return []

        cache_dir = cfg.raw_api_path / "gdelt"
        client = PoliteApiClient(cache_dir, http_settings)

        await client.__aenter__()
        overall_start = windows[0][0]
        overall_end = windows[-1][1]
        records: list[dict[str, Any]] = []

        for topic in cfg.topics:
            query = normalize_gdelt_query(topic.gdelt_query)
            params = _build_params(query, overall_start, overall_end)
            cache_key = f"gdelt_{topic.topic_id}_{overall_start}_{overall_end}"
            try:
                response = await client.get_json(GDELT_BASE_URL, params, cache_key=cache_key)
            except Exception as exc:  # noqa: BLE001 - preserve partial progress
                records.extend(self._failed_records(topic, windows, exc))
                continue

            if isinstance(response.payload, dict) and "_non_json_body" in response.payload:
                err = f"non-JSON response: {response.payload['_non_json_body'][:120]}"
                records.extend(self._failed_records(topic, windows, RuntimeError(err)))
                continue

            timeline = _extract_timeline(response.payload)
            monthly_counts = self._aggregate_monthly(timeline)
            for w_start, w_end in windows:
                records.append({
                    "source": "gdelt",
                    "topic_id": topic.topic_id,
                    "topic_label": topic.topic_label,
                    "window_start": w_start,
                    "window_end": w_end,
                    "activity_count": monthly_counts.get(w_start, 0),
                    "collection_status": "ok",
                    "collected_at": response.fetched_at,
                    "cached": response.cache_hit,
                })

        await client.__aexit__(None, None, None)
        return records

    @staticmethod
    def _aggregate_monthly(timeline: list[dict[str, Any]]) -> dict[str, int]:
        monthly: dict[str, int] = {}
        for entry in timeline:
            date_str, count = _parse_timeline_entry(entry)
            if date_str:
                ym = _gdelt_date_to_ym(date_str)
                if ym:
                    monthly[ym] = monthly.get(ym, 0) + count
        return monthly

    @staticmethod
    def _failed_records(topic: Any, windows: list[tuple[str, str]], exc: Exception) -> list[dict[str, Any]]:
        """One failed record per window so downstream coverage stats stay honest."""
        fetched_at = datetime.utcnow().isoformat() + "Z"
        return [
            {
                "source": "gdelt",
                "topic_id": topic.topic_id,
                "topic_label": topic.topic_label,
                "window_start": w_start,
                "window_end": w_end,
                "activity_count": None,
                "collection_status": "failed",
                "collected_at": fetched_at,
                "cached": False,
                "error": str(exc),
            }
            for w_start, w_end in windows
        ]
