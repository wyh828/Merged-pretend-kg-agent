"""CrossRef 客户端（阶段 3 合并，第 7 源）：DOI 锚点 + `mailto` polite pool + 增量游标。

与 OpenAlex 客户端同构（filter / 分页 / 限速 / 重试 / 归一化到 works 行），
差异仅在 CrossRef 的协议细节：

- 端点 `GET /works`；`mailto` 进 polite pool（CrossRef 无 premium key，全靠 mailto）。
- 过滤 `filter=from-pub-date:<date>`（按出版日期增量，与 OpenAlex `from_publication_date` 同语义）。
- 游标分页：首请求 `cursor=*`，之后跟随 `message.next-cursor`（CrossRef 深分页规范）。
- CrossRef **无受控 concept 词表**，`subject` 为自由文本标签 → 归一化为
  `crossref:<subject>` 作 concept 短 ID（name=subject, score=1.0），供概念频次/信号使用。
- 与 OpenAlex 的 DOI 去重不在此处：两者都以 DOI 锚定，交给 align 阶段的 DOI 强锚点合并。
"""
import html
import logging
import re
from typing import Any, Iterable

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)

_BASE_URL = "https://api.crossref.org"
_SELECT = "DOI,title,abstract,subject,published,issued,created,author,reference,container-title"
_TAG_RE = re.compile(r"<[^>]+>")


def _should_retry(exc: BaseException) -> bool:
    """仅对限流/服务端错误/传输异常重试。"""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, (httpx.TransportError, httpx.TimeoutException))


def _strip_tags(text: str | None) -> str | None:
    """JATS/HTML 摘要还原为纯文本（CrossRef abstract 常为 JATS 片段）。"""
    if not text:
        return None
    plain = _TAG_RE.sub(" ", html.unescape(text))
    return re.sub(r"\s+", " ", plain).strip() or None


def _date_from_parts(obj: dict | None) -> str | None:
    """CrossRef 日期（date-parts [[Y,M,D]]）→ 'YYYY-MM-DD'（缺位则截短）。"""
    if not obj:
        return None
    parts = (obj.get("date-parts") or [])[:1]
    if not parts or not parts[0]:
        return None
    ymd = parts[0]
    y = ymd[0] if len(ymd) > 0 else None
    if y is None:
        return None
    m = ymd[1] if len(ymd) > 1 else None
    d = ymd[2] if len(ymd) > 2 else None
    if m is None:
        return f"{y:04d}"
    if d is None:
        return f"{y:04d}-{m:02d}"
    return f"{y:04d}-{m:02d}-{d:02d}"


class CrossrefClient:
    def __init__(
        self,
        mailto: str | None = None,
        per_page: int = 100,
        timeout: float = 30.0,
    ) -> None:
        self.client = httpx.Client(base_url=_BASE_URL, timeout=timeout)
        self.mailto = mailto
        self.per_page = min(per_page, 1000)  # CrossRef rows 上限 1000

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
        """按 `from-pub-date` 游标分页拉取 works，直到末页或达 max_works。

        `concept_ids` 在 CrossRef 无对应过滤能力（无受控词表），忽略；保留形参以与
        OpenAlex 接口对齐。默认排序为 CrossRef 相关性（同 OpenAlex 默认排序的
        跨时间分布覆盖，保证时间跨度足够供时态切分）。
        """
        params: dict[str, Any] = {
            "rows": self.per_page,
            "select": _SELECT,
            "cursor": "*",
        }
        if from_date:
            params["filter"] = f"from-pub-date:{from_date}"
        if self.mailto:
            params["mailto"] = self.mailto

        works: list[dict] = []
        while True:
            data = self._get_page(params)
            message = data.get("message") or {}
            results = message.get("items") or []
            works.extend(results)
            log.info(
                "CrossRef 分页：cursor=%s 本页 %d 条，累计 %d/%d",
                params.get("cursor"), len(results), len(works), max_works,
            )
            next_cursor = message.get("next-cursor")
            if not results or len(works) >= max_works or not next_cursor:
                break
            params["cursor"] = next_cursor
        return works[:max_works]

    # ---- 归一化 ----
    @staticmethod
    def normalize(work: dict) -> dict:
        """CrossRef item → 归一化 work 行（与 OpenAlex `normalize` 同 schema）。"""
        doi = (work.get("DOI") or "").strip()
        title_list = work.get("title") or []
        title = title_list[0] if title_list else (work.get("container-title") or [""])[0]
        pub_date = (
            _date_from_parts(work.get("published"))
            or _date_from_parts(work.get("issued"))
            or _date_from_parts(work.get("created"))
        )
        return {
            "id": f"doi:{doi.lower()}" if doi else None,
            "source": "crossref",
            "title": title or None,
            "doi": doi or None,
            "publication_date": pub_date,
            "abstract": _strip_tags(work.get("abstract")),
            "concepts": [
                {"id": f"crossref:{s}", "name": s, "score": 1.0}
                for s in (work.get("subject") or []) if s
            ],
            "authorships": [
                {
                    "author": {
                        "id": None,
                        "name": " ".join(
                            p for p in (a.get("given"), a.get("family")) if p
                        ).strip() or None,
                    },
                    "institutions": [],
                }
                for a in (work.get("author") or [])
            ],
            "referenced_works": [
                r.get("DOI") for r in (work.get("reference") or []) if r.get("DOI")
            ],
        }

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "CrossrefClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
