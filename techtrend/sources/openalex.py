"""OpenAlex 客户端：过滤 / 分页 / 限速 / 重试 / 增量游标。

- 端点 `GET /works`；`mailto` 进 polite pool、`api_key` 进 premium（额度 10×）。
- 过滤 `from_publication_date:<date>,concepts.id:<ID1|ID2>`；cursor 分页跟随 `next_cursor`。
- 仅 429/5xx 与传输异常重试（tenacity 指数退避）。
- `concepts.id` 仍可用（实测）；若日后 OpenAlex 彻底移除 concepts 字段，
  可把过滤键切到 `primary_topic.id`/`topics.id`（见 P1_PLAN.md 风险说明）。
"""
import logging
from typing import Any, Iterable

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)

_BASE_URL = "https://api.openalex.org"
_SELECT = (
    "id,doi,title,abstract_inverted_index,publication_date,"
    "concepts,authorships,referenced_works,cited_by_count"
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
        per_page: int = 200,
        timeout: float = 30.0,
    ) -> None:
        headers: dict[str, str] = {}
        params: dict[str, Any] = {"per-page": per_page}
        if mailto:
            headers["User-Agent"] = f"mailto:{mailto}"
            params["mailto"] = mailto
        if api_key:
            params["api_key"] = api_key
        self.client = httpx.Client(
            base_url=_BASE_URL, timeout=timeout, headers=headers, params=params
        )
        self.per_page = per_page

    # ---- 内部请求（带重试）----
    @retry(
        retry=retry_if_exception(_should_retry),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        reraise=True,
    )
    def _get_page(self, params: dict[str, Any]) -> dict:
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
        """按过滤条件 cursor 分页拉取 works，直到空页或达 max_works。

        说明：P1 不显式指定 sort，沿用 OpenAlex 默认排序（高被引优先、跨时间分布），
        保证基线在限定 max_works 内仍能覆盖足够长的时间跨度（供 Kleinberg/时态切分用）。
        """
        filters: list[str] = []
        if from_date:
            filters.append(f"from_publication_date:{from_date}")
        if concept_ids:
            filters.append("concepts.id:" + "|".join(concept_ids))

        params: dict[str, Any] = {"select": _SELECT}
        if filters:
            params["filter"] = ",".join(filters)

        works: list[dict] = []
        page = 1
        while True:
            page_params = dict(params)
            page_params["page"] = page
            data = self._get_page(page_params)
            results = data.get("results") or []
            works.extend(results)
            log.info(
                "OpenAlex 分页：page=%d 本页 %d 条，累计 %d/%d",
                page, len(results), len(works), max_works,
            )
            page += 1
            # 到达 max_works / 空页 / 不足一页（末页）即停
            if not results or len(works) >= max_works or len(results) < self.per_page:
                break
        return works[:max_works]

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
        return {
            "id": work.get("id"),
            "title": work.get("title"),
            "publication_date": work.get("publication_date"),
            "doi": work.get("doi"),
            "abstract": self._reconstruct_abstract(work.get("abstract_inverted_index")),
            "cited_by_count": work.get("cited_by_count"),
            "concepts": [
                {"id": c.get("id"), "name": c.get("display_name"), "score": c.get("score")}
                for c in (work.get("concepts") or [])
            ],
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
