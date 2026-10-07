"""OpenAlex works: modern Topics, bounded cursor pages and free optional key.

Legacy concepts are accepted only when explicitly requested. Default paging
uses publication order, not present-day citation ranking.
"""
import logging
from typing import Any, Callable
import time

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)
from techtrend.sources.paging import WorksBatch

_BASE_URL = "https://api.openalex.org"
_SELECT = (
    "id,doi,title,abstract_inverted_index,publication_date,"
    "topics,primary_topic,authorships,referenced_works,cited_by_count"
)


def _should_retry(exc: BaseException) -> bool:
    """仅对限流/服务端错误/传输异常重试。"""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, (httpx.TransportError, httpx.TimeoutException))


class OpenAlexClient:
    def __init__(
        self,
        mailto: str | None = None,
        api_key: str | None = None,
        per_page: int = 100,
        timeout: float = 30.0,
        min_interval: float = 1.0,
        base_url: str = _BASE_URL,
    ) -> None:
        headers: dict[str, str] = {}
        params: dict[str, Any] = {}
        if mailto:
            headers["User-Agent"] = f"mailto:{mailto}"
            params["mailto"] = mailto
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self.client = httpx.Client(
            base_url=base_url, timeout=timeout, headers=headers, params=params
        )
        self.per_page = max(1, min(per_page, 100))
        self.min_interval = min_interval
        self._last_request = 0.0

    # ---- 内部请求（带重试）----
    @retry(
        retry=retry_if_exception(_should_retry),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        reraise=True,
    )
    def _get_page(self, params: dict[str, Any]) -> dict:
        time.sleep(max(0.0, self.min_interval - (time.monotonic() - self._last_request)))
        self._last_request = time.monotonic()
        resp = self.client.get("/works", params=params)
        resp.raise_for_status()
        return resp.json()

    # ---- 采集 ----
    def fetch_works(
        self,
        from_date: str | None,
        concept_ids: list[str] | None,
        max_works: int,
    ) -> list[dict]:
        """Compatibility wrapper; callers needing coverage use fetch_batch."""
        return self.fetch_batch(from_date, concept_ids, max_works).records

    def fetch_batch(self, from_date: str | None, concept_ids: list[str] | None,
                    max_works: int, *, until_date: str | None = None,
                    cursor: str = "*", field_ids: list[str] | None = None,
                    on_page: Callable | None = None) -> WorksBatch:
        """Consume bounded cursor pages in publication order, without lost rows.

        on_page(payload, query, next_cursor, complete) must persist the page
        before returning. Legacy concept filters remain opt-in for old configs.
        """
        if max_works <= 0:
            raise ValueError("max_works must be positive")
        filters: list[str] = []
        if from_date:
            filters.append(f"from_publication_date:{from_date}")
        if until_date:
            filters.append(f"to_publication_date:{until_date}")
        if concept_ids:
            filters.append("concepts.id:" + "|".join(concept_ids))
        if field_ids:
            filters.append("primary_topic.field.id:" + "|".join(field_ids))

        params: dict[str, Any] = {"select": _SELECT, "sort": "publication_date:asc"}
        if filters:
            params["filter"] = ",".join(filters)

        batch = WorksBatch(next_cursor=cursor)
        while len(batch.records) < max_works:
            page_params = dict(params)
            page_params["cursor"] = batch.next_cursor
            size = min(self.per_page, max_works - len(batch.records))
            page_params["per_page"] = size
            data = self._get_page(page_params)
            if not isinstance(data.get("results"), list) or not isinstance(data.get("meta"), dict):
                raise ValueError("OpenAlex response lacks results/meta")
            results = data["results"]
            if len(results) > size:
                raise ValueError("OpenAlex returned more rows than requested")
            batch.reported_total = data["meta"].get("count")
            next_cursor = data["meta"].get("next_cursor")
            complete = not results or len(results) < size or not next_cursor
            if on_page:
                on_page(data, page_params, next_cursor, complete)
            batch.records.extend(results)
            batch.next_cursor = next_cursor
            batch.complete = complete
            batch.pages += 1
            log.info("OpenAlex page %d: %d rows, complete=%s", batch.pages, len(results), complete)
            if complete:
                break
            if next_cursor == page_params["cursor"]:
                raise ValueError("OpenAlex cursor made no progress")
        return batch

    # ---- 归一化 ----
    @staticmethod
    def _reconstruct_abstract(inv: dict | None) -> str | None:
        """把 abstract_inverted_index 还原为纯文本（P2 LLM 用，P1 结构化抽取不依赖）。"""
        if not inv:
            return None
        pairs = [(pos, word) for word, positions in inv.items() for pos in positions]
        pairs.sort(key=lambda p: p[0])
        return " ".join(word for _, word in pairs)

    def normalize(self, work: dict) -> dict:
        """字段裁剪 + 归一化（display_name → name）。"""
        topics = work.get("topics") or []
        classifications = topics or work.get("concepts") or []
        return {
            "id": work.get("id"),
            "source": "openalex",
            "title": work.get("title"),
            "publication_date": work.get("publication_date"),
            "doi": work.get("doi"),
            "abstract": self._reconstruct_abstract(work.get("abstract_inverted_index")),
            "cited_by_count": work.get("cited_by_count"),
            "concepts": [
                {"id": c.get("id"), "name": c.get("display_name"), "score": c.get("score")}
                for c in classifications
            ],
            "classification_scheme": "openalex_topics" if topics else "legacy_concepts",
            "primary_topic": work.get("primary_topic"),
            "topics": topics,
            "historical_available_at": None,
            "authorships": [
                {
                    "author": {
                        "id": (a.get("author") or {}).get("id"),
                        "name": (a.get("author") or {}).get("display_name"),
                    },
                    "institutions": [
                        {"id": i.get("id"), "name": i.get("display_name")}
                        for i in (a.get("institutions") or [])
                    ],
                }
                for a in (work.get("authorships") or [])
            ],
            "referenced_works": work.get("referenced_works") or [],
        }

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "OpenAlexClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
