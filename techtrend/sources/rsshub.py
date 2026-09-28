"""RSSHub RSS 客户端：httpx 拉 RSS/Atom → feedparser 解析。

- 前置：Docker 起 RSSHub（`docker run -d -p 1200:1200 diygod/rsshub`），选中文科技媒体路由。
- 每 item 取 title / link / summary（去 HTML）/ published；中文 `text` 供 LLM 抽实体/tone。
- 无 key；仅 429/5xx 与传输异常重试。
"""
import html
import logging
import re
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)


def _should_retry(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, (httpx.TransportError, httpx.TimeoutException))


def _strip_html(text: str) -> str:
    """去 HTML 标签 + 反转义，得到纯文本（喂 LLM）。"""
    text = re.sub(r"<[^>]+>", " ", text or "")
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


class RssHubClient:
    def __init__(self, base_url: str = "http://localhost:1200", timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        # trust_env=False：本机 RSSHub 走 localhost，须绕过系统代理（否则被 127.0.0.1:7897 代理拦成 502）
        self.client = httpx.Client(timeout=timeout, trust_env=False)

    @retry(
        retry=retry_if_exception(_should_retry),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        reraise=True,
    )
    def _get(self, route: str) -> bytes:
        resp = self.client.get(f"{self.base_url}{route}")
        resp.raise_for_status()
        return resp.content

    # ---- 采集 ----
    def fetch_items(self, routes: list[str], max_items: int) -> list[dict]:
        """逐路由拉取 RSS，合并并截断到 max_items。"""
        items: list[dict] = []
        for route in routes:
            if len(items) >= max_items:
                break
            try:
                content = self._get(route)
            except Exception as exc:  # noqa: BLE001 —— 单路由失败不阻断他路由
                log.warning("RSSHub 路由 %s 拉取失败：%s", route, exc)
                continue
            feed = feedparser.parse(content)
            for entry in feed.entries or []:
                items.append(self.normalize(entry, route))
                if len(items) >= max_items:
                    break
        return items

    # ---- 归一化 ----
    @staticmethod
    def normalize(item: Any, route: str) -> dict:
        link = item.get("link") or ""
        summary = item.get("summary") or ""
        published = item.get("published") or item.get("updated") or ""
        date = ""
        try:
            date = parsedate_to_datetime(published).strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            date = (published or "")[:10]
        return {
            "id": f"rsshub:{link}",
            "source": "rsshub",
            "title": (item.get("title") or "").strip(),
            "text": _strip_html(summary),
            "url": link,
            "publication_date": date,
        }

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "RssHubClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
