"""GitHub Search API 客户端：新晋热门仓库（created/star 过滤）。

- `GET /search/repositories?q=created:>DATE+stars:>=N+topic:AI`，token 进 `Authorization` 头。
- 未认证 60 req/h → 认证 5000 req/h；tenacity 处理 403/429。
- 归一化行含 `created_at`（仓库创建日，作三元组 time）；每日 star 快照由 CollectStage 另记。
"""
import logging
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

_BASE_URL = "https://api.github.com"


def _should_retry(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (403, 429) or exc.response.status_code >= 500
    return isinstance(exc, (httpx.TransportError, httpx.TimeoutException))


class GithubClient:
    def __init__(self, token: str | None = None, timeout: float = 30.0) -> None:
        headers: dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.client = httpx.Client(base_url=_BASE_URL, timeout=timeout, headers=headers)

    @retry(
        retry=retry_if_exception(_should_retry),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=60),
        reraise=True,
    )
    def _search(self, params: dict[str, Any]) -> dict:
        resp = self.client.get("/search/repositories", params=params)
        resp.raise_for_status()
        return resp.json()

    # ---- 采集 ----
    def fetch_repos(
        self,
        from_date: str | None,
        topics: list[str],
        min_stars: int,
        max_repos: int,
    ) -> list[dict]:
        """按 created/star/topic 过滤拉取仓库，分页至 max_repos。

        GitHub Search API 不支持对 topic: 限定符做 OR（无括号 422、加括号 total=0），
        故逐 topic 查询后按 full_name 去重合并。
        """
        repos: list[dict] = []
        seen: set[str] = set()
        for topic in topics:
            if len(repos) >= max_repos:
                break
            query = f"stars:>={min_stars} topic:{topic}"
            if from_date:
                query += f" created:>{from_date}"

            page = 1
            per_page = min(100, max_repos)
            while len(repos) < max_repos:
                data = self._search(
                    {"q": query, "sort": "stars", "order": "desc", "per_page": per_page, "page": page}
                )
                items = data.get("items") or []
                for r in items:
                    norm = self.normalize(r)
                    if norm["id"] not in seen:
                        seen.add(norm["id"])
                        repos.append(norm)
                log.info(
                    "GitHub topic=%s page=%d 本页 %d 条，累计 %d/%d",
                    topic, page, len(items), len(repos), max_repos,
                )
                page += 1
                if not items or len(items) < per_page or len(repos) >= max_repos:
                    break
        return repos[:max_repos]

    # ---- 归一化 ----
    @staticmethod
    def normalize(repo: dict) -> dict:
        full_name = repo.get("full_name") or ""
        return {
            "id": f"github:{full_name}",
            "source": "github",
            "name": full_name,
            "description": repo.get("description"),
            "url": repo.get("html_url"),
            "stars": repo.get("stargazers_count") or 0,
            "topics": repo.get("topics") or [],
            "created_at": (repo.get("created_at") or "")[:10],
        }

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "GithubClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
