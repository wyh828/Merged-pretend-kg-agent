"""GitHub REST collector for trending repository signals (public only).

Uses the ``search/repositories`` endpoint with two windows per topic:
1) ``{topic_query} created:>=D-7`` sorted by stars desc (new repos)
2) ``{topic_query} pushed:>=D-1`` sorted by stars desc (active repos)

Each topic uses its own ``github_query`` from ``topics.yaml`` so that repo
signals are topic-specific rather than shared across all topics.

Supports optional authentication via ``GITHUB_TOKEN``. Caches raw responses
through :class:`~http_client.PoliteApiClient` and writes minimal interim JSONL
snapshots (repos + derived signals). Returns one synthetic activity record per
topic with topic-specific signal counts.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import asyncio
from typing import Any, Iterable

from dotenv import load_dotenv

from techtrend.signal.config import PipelineConfig
from techtrend.signal.data_collectors.base import register
from techtrend.signal.http_client import PoliteApiClient, CachedResponse

GITHUB_API = "https://api.github.com"
SEARCH_REPOS = f"{GITHUB_API}/search/repositories"

# Default paging (overridable via source_cfg).
DEFAULT_PER_PAGE = 30  # GitHub max 100; smaller reduces rate pressure
DEFAULT_MAX_PAGES = 4  # safety cap per query kind


def _load_env(attempt_root: Path) -> None:
    env_path = attempt_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)


def _github_headers() -> dict[str, str]:
    """Build GitHub auth headers (separate from the session User-Agent)."""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        low = token.lower()
        use_bearer = low.startswith(("github_pat_", "ghu_", "ghs_", "gho_"))
        scheme = "Bearer" if use_bearer else "token"
        headers["Authorization"] = f"{scheme} {token}"
    return headers


def _day_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _iso_to_dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _extract_minimal_repo(item: dict[str, Any], topic_id: str = "", topic_label: str = "") -> dict[str, Any]:
    owner = item.get("owner") or {}
    license_info = item.get("license") or {}
    return {
        "repo_id": item.get("id"),
        "full_name": item.get("full_name"),
        "html_url": item.get("html_url"),
        "description": item.get("description"),
        "language": item.get("language"),
        "topics": item.get("topics", []),
        "stargazers_count": item.get("stargazers_count", 0),
        "forks_count": item.get("forks_count", 0),
        "open_issues_count": item.get("open_issues_count", 0),
        "watchers_count": item.get("watchers_count", 0),
        "license": license_info.get("key") if isinstance(license_info, dict) else None,
        "owner_login": owner.get("login"),
        "owner_type": owner.get("type"),
        "created_at": item.get("created_at"),
        "pushed_at": item.get("pushed_at"),
        "archived": item.get("archived", False),
        "disabled": item.get("disabled", False),
        "homepage": item.get("homepage"),
        "topic_id": topic_id,
        "topic_label": topic_label,
    }


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    n = 0
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    return n


@register("github")
class GithubCollector:
    """Daily trending-repo snapshot collector for GitHub search API."""

    async def collect(
        self,
        cfg: PipelineConfig,
        http_settings: dict[str, Any],
        source_cfg: dict[str, Any],
    ) -> list[dict[str, Any]]:
        # GitHub needs the attempt_root to locate .env for GITHUB_TOKEN.
        # We resolve it from the data_root (project root -> attempt root).
        attempt_root = cfg.data_root.parent / "Attempt"
        _load_env(attempt_root)

        raw_cache_dir = cfg.raw_api_path / "github"
        interim_dir = cfg.interim_path
        raw_cache_dir.mkdir(parents=True, exist_ok=True)
        interim_dir.mkdir(parents=True, exist_ok=True)

        # GitHub auth changes rate limits; reflect that in min_interval.
        gh_settings = dict(http_settings)
        if os.environ.get("GITHUB_TOKEN"):
            gh_settings["min_interval_seconds"] = min(
                float(gh_settings.get("min_interval_seconds", 3.0)), 0.5
            )
        else:
            gh_settings["min_interval_seconds"] = max(
                float(gh_settings.get("min_interval_seconds", 3.0)), 1.5
            )

        client = PoliteApiClient(raw_cache_dir, gh_settings)


        await client.__aenter__()
        headers = _github_headers()

        k_new = int(source_cfg.get("k_new", 100))
        k_active = int(source_cfg.get("k_active", 50))
        per_page = int(source_cfg.get("per_page", DEFAULT_PER_PAGE))
        max_pages = int(source_cfg.get("max_pages", DEFAULT_MAX_PAGES))
        lang_whitelist = source_cfg.get("language_whitelist") or None
        org_whitelist = source_cfg.get("org_whitelist") or None

        now = datetime.now(timezone.utc)
        day = _day_str(now)
        created_since = _day_str(now - timedelta(days=7))
        pushed_since = _day_str(now - timedelta(days=1))

        all_repos: list[dict[str, Any]] = []
        all_signals: list[dict[str, Any]] = []
        fetch_errors: list[str] = []
        records: list[dict[str, Any]] = []

        for topic in cfg.topics:
            topic_query = topic.github_query or topic.openalex_query
            if not topic_query:
                fetch_errors.append(f"topic {topic.topic_id}: no github_query configured")
                records.append({
                    "source": "github",
                    "topic_id": topic.topic_id,
                    "topic_label": topic.topic_label,
                    "window_start": day,
                    "window_end": day,
                    "activity_count": 0,
                    "collection_status": "failed",
                    "collected_at": now.isoformat(),
                    "cached": False,
                    "error": "no github_query configured",
                })
                continue

            topic_repos: list[dict[str, Any]] = []
            topic_fetch_errors: list[str] = []

            for q_suffix, topk, tag in [
                (f"created:>={created_since}", k_new, "new"),
                (f"pushed:>={pushed_since}", k_active, "active"),
            ]:
                full_query = f"{topic_query} {q_suffix}"
                page = 1
                kept = 0
                while kept < topk and page <= max_pages:
                    this_per = min(per_page, topk - kept)
                    params = {
                        "q": full_query,
                        "sort": "stars",
                        "order": "desc",
                        "per_page": this_per,
                        "page": page,
                    }
                    cache_key = f"github_{topic.topic_id}_{tag}_{day}_p{page}"
                    try:
                        response = await client.get_json(
                            SEARCH_REPOS, params, cache_key=cache_key, extra_headers=headers,
                        )
                    except Exception as exc:  # noqa: BLE001 - preserve partial progress
                        topic_fetch_errors.append(f"{topic.topic_id}/{tag} page {page}: {exc}")
                        break

                    if isinstance(response.payload, dict) and "_non_json_body" in response.payload:
                        topic_fetch_errors.append(
                            f"{topic.topic_id}/{tag} page {page}: non-JSON {response.payload['_non_json_body'][:80]}"
                        )
                        break

                    items = response.payload.get("items", []) if isinstance(response.payload, dict) else []
                    for item in items:
                        rec = _extract_minimal_repo(item, topic.topic_id, topic.topic_label)
                        if lang_whitelist and rec.get("language") not in lang_whitelist:
                            continue
                        if org_whitelist and rec.get("owner_login") not in org_whitelist:
                            continue
                        rec["_window"] = tag
                        topic_repos.append(rec)
                        kept += 1
                        if kept >= topk:
                            break
                    if not items:
                        break
                    page += 1

            # Deduplicate by repo_id within this topic, keeping max stargazers_count
            seen: dict[int, dict[str, Any]] = {}
            for r in topic_repos:
                rid = int(r.get("repo_id") or 0)
                if rid not in seen or (r.get("stargazers_count", 0) > seen[rid].get("stargazers_count", 0)):
                    seen[rid] = r
            deduped = list(seen.values())

            # Build topic-specific signals
            topic_signals: list[dict[str, Any]] = []
            for r in deduped:
                created_at = r.get("created_at")
                pushed_at = r.get("pushed_at")
                stars = int(r.get("stargazers_count", 0))
                days = max(1, int((now - _iso_to_dt(created_at)).days)) if created_at else 1
                recent = 1 if (pushed_at and (now - _iso_to_dt(pushed_at)).days <= 3) else 0
                topic_signals.append({
                    "repo_id": r.get("repo_id"),
                    "full_name": r.get("full_name"),
                    "stars_total": stars,
                    "stars_per_day_lifetime": round(stars / days, 3),
                    "forks_total": int(r.get("forks_count", 0)),
                    "activity_recent": recent,
                    "language": r.get("language"),
                    "created_at": created_at,
                    "topic_id": topic.topic_id,
                    "topic_label": topic.topic_label,
                    "_window": r.get("_window"),
                })

            all_repos.extend(deduped)
            all_signals.extend(topic_signals)
            fetch_errors.extend(topic_fetch_errors)

            n_topic_signals = len(topic_signals)
            status = "ok" if not topic_fetch_errors else "partial"
            records.append({
                "source": "github",
                "topic_id": topic.topic_id,
                "topic_label": topic.topic_label,
                "window_start": day,
                "window_end": day,
                "activity_count": n_topic_signals,
                "collection_status": status,
                "collected_at": now.isoformat(),
                "cached": False,
                "features": {
                    "repos_count": len(deduped),
                    "signals_count": n_topic_signals,
                    "stars_total": sum(s["stars_total"] for s in topic_signals),
                    "forks_total": sum(s["forks_total"] for s in topic_signals),
                    "activity_recent_count": sum(s["activity_recent"] for s in topic_signals),
                    "fetch_errors": topic_fetch_errors,
                },
            })

        # Persist all repos and signals (across all topics) to interim
        repos_path = interim_dir / f"github_repos_{day}.jsonl"
        n_repos = _write_jsonl(repos_path, all_repos)

        signals_path = interim_dir / f"github_signals_{day}.jsonl"
        n_signals = _write_jsonl(signals_path, all_signals)

        await client.__aexit__(None, None, None)
        return records
