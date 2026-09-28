"""arXiv 客户端：Atom 查询 / 分页 / 限速 / 重试 / 增量游标。

- 端点 `https://export.arxiv.org/api/query`（Atom XML，feedparser 解析）。
- 查询 `search_query=cat:cs.AI+OR+cat:cs.LG+...`，按 submittedDate 降序分页。
- 日期增量在客户端过滤：结果已降序，遇到早于 from_date 的条目即停止。
  arXiv 的 submittedDate 过滤器实测返回 406，故不用。
- 传输用 stdlib urllib 而非 httpx：arXiv 的 Varnish CDN 对 httpx 的请求
  （尤其 start>0 分页）返回 406，urllib 正常返回 200。
- 遵守 3s/请求限速；仅 429/5xx 与传输异常重试。
- 增量游标由 CollectStage 管理（`data/.arxiv_cursor`），此处只负责拉取 + 归一化。
"""
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import feedparser
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

_BASE_URL = "https://export.arxiv.org/api/query"
_USER_AGENT = "techtrend-kg/0.1 (research pipeline; contact: local)"


def _should_retry(exc: BaseException) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code == 429 or exc.code >= 500
    return isinstance(exc, urllib.error.URLError)


class ArxivClient:
    def __init__(self, per_page: int = 100, timeout: float = 30.0) -> None:
        self.per_page = per_page
        self.timeout = timeout

    @retry(
        retry=retry_if_exception(_should_retry),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        reraise=True,
    )
    def _get(self, params: dict[str, Any]) -> bytes:
        qs = urllib.parse.urlencode(params)
        req = urllib.request.Request(
            f"{_BASE_URL}?{qs}", headers={"User-Agent": _USER_AGENT}
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read()

    # ---- 采集 ----
    def fetch_works(
        self,
        from_date: str | None,
        categories: list[str],
        max_records: int,
    ) -> list[dict]:
        """按分类拉取 Atom（submittedDate 降序），start/max_results 分页。

        日期增量在客户端过滤：结果已按 submittedDate 降序，一旦遇到早于 from_date
        的条目即停止（后续更早）。
        """
        search_query = " OR ".join(f"cat:{c}" for c in categories)

        records: list[dict] = []
        start = 0
        while len(records) < max_records:
            params = {
                "search_query": search_query,
                "start": start,
                "max_results": min(self.per_page, max_records - len(records)),
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            }
            content = self._get(params)
            feed = feedparser.parse(content)
            entries = feed.entries or []
            for e in entries:
                rec = self.normalize(e)
                if from_date and rec.get("publication_date") and rec["publication_date"] < from_date:
                    return records[:max_records]  # 降序，已越过窗口
                records.append(rec)
            log.info(
                "arXiv 分页：start=%d 本页 %d 条，累计 %d/%d",
                start, len(entries), len(records), max_records,
            )
            start += len(entries)
            if not entries or len(entries) < self.per_page:
                break
            time.sleep(3)  # arXiv 3s/请求限速
        return records[:max_records]

    # ---- 归一化 ----
    @staticmethod
    def normalize(entry: Any) -> dict:
        """Atom entry → 归一化行。abstract 为纯文本，可直接喂 LLM。"""
        arxiv_id = ""
        id_url = entry.get("id") or ""
        # id 形如 http://arxiv.org/abs/2301.00001v1 → arxiv:2301.00001
        if "/abs/" in id_url:
            arxiv_id = "arxiv:" + id_url.split("/abs/")[-1].split("v")[0]
        elif "/abs/" not in id_url and id_url:
            arxiv_id = "arxiv:" + id_url.rsplit("/", 1)[-1]
        return {
            "id": arxiv_id,
            "source": "arxiv",
            "title": entry.get("title", "").strip(),
            "doi": entry.get("arxiv_doi"),
            "abstract": entry.get("summary", "").strip(),
            "categories": [
                t.get("term") for t in entry.get("tags", []) if t.get("term")
            ],
            "authors": [
                {"name": a.get("name")} for a in entry.get("authors", []) if a.get("name")
            ],
            "publication_date": (entry.get("published") or "")[:10],
        }

    def close(self) -> None:
        # urllib 无持久连接，保留 close() 以与其他源接口一致。
        return None

    def __enter__(self) -> "ArxivClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
