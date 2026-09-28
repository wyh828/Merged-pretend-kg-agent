"""Unified polite HTTP client for all data collectors (async version).

Provides a single cache-first HTTP layer with:
- Deterministic cache keys (full 64-char SHA256)
- Bounded retries with exponential backoff + jitter
- Respect for Retry-After headers
- Non-JSON response wrapping (e.g. GDELT plain-text errors)
- Per-cache request logging
- URL redaction for api_key/token query params
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import time
from dataclasses import dataclass, asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiohttp
import aiosqlite


class RateLimitedError(Exception):
    """Raised when a provider asks for a wait longer than this run permits."""

    def __init__(self, message: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class CachedResponse:
    """Minimal response representation persisted in the raw API cache."""

    status_code: int
    headers: dict[str, str]
    payload: Any
    fetched_at: str
    url: str
    cache_hit: bool = False


# Default HTTP settings. Per-source overrides come from sources.yaml["http"].
DEFAULT_HTTP_SETTINGS: dict[str, Any] = {
    "user_agent": "PredictiveAgents/0.1 (research project)",
    "contact_email_env": "PROJECT_CONTACT_EMAIL",
    "timeout_seconds": 30,
    "max_retries": 3,
    "min_interval_seconds": 3.0,
    "backoff_factor_seconds": 15.0,
    "max_backoff_seconds": 90.0,
    "max_retry_after_seconds": 120.0,
    "jitter_seconds": 1.5,
    "respect_retry_after": True,
}


class PoliteApiClient:
    """Cache-first async client with spacing, Retry-After, and bounded backoff."""

    def __init__(self, cache_dir: str | Path, settings: dict[str, Any] | None = None) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        merged = dict(DEFAULT_HTTP_SETTINGS)
        if settings:
            merged.update(settings)
        self.settings = merged
        
        user_agent = merged["user_agent"]
        email_env = merged.get("contact_email_env")
        if email_env and os.getenv(email_env):
            user_agent = f"{user_agent} (mailto:{os.environ[email_env]})"
            
        self.headers = {"User-Agent": user_agent, "Accept": "application/json"}
        self._last_request_at = 0.0
        self.request_log_path = self.cache_dir / "request_log_00.jsonl"
        self.db_path = self.cache_dir / "cache.sqlite"
        self._spacing_lock = asyncio.Lock()
        
        self.session: aiohttp.ClientSession | None = None
        self.db: aiosqlite.Connection | None = None

    async def __aenter__(self) -> PoliteApiClient:
        self.session = aiohttp.ClientSession(headers=self.headers)
        self.db = await aiosqlite.connect(self.db_path)
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS api_cache_v2 (cache_key TEXT, retrieved_at TIMESTAMP, data TEXT, PRIMARY KEY (cache_key, retrieved_at))"
        )
        try:
            await self.db.execute(
                "INSERT OR IGNORE INTO api_cache_v2 (cache_key, retrieved_at, data) "
                "SELECT cache_key, '2024-01-01T00:00:00+00:00', data FROM api_cache"
            )
        except aiosqlite.OperationalError:
            pass
        await self.db.commit()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.session:
            await self.session.close()
        if self.db:
            await self.db.close()

    async def _get_from_cache(self, cache_key: str, as_of: str | None = None) -> CachedResponse | None:
        if not self.db:
            return None
        
        query = "SELECT data FROM api_cache_v2 WHERE cache_key = ?"
        params = [cache_key]
        
        if as_of:
            query += " AND retrieved_at <= ?"
            params.append(as_of)
            
        query += " ORDER BY retrieved_at DESC LIMIT 1"
        
        async with self.db.execute(query, tuple(params)) as cursor:
            row = await cursor.fetchone()
            if row:
                data = json.loads(row[0])
                data.setdefault("cache_hit", True)
                return CachedResponse(**data)

        # Fallback to file-based JSON cache if present
        json_path = self.cache_dir / f"{cache_key}.json"
        if json_path.exists():
            try:
                with json_path.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
                data.setdefault("cache_hit", True)
                cached_resp = CachedResponse(**data)
                await self._save_to_cache(cache_key, cached_resp)
                return cached_resp
            except Exception:
                pass

        return None

    async def _save_to_cache(self, cache_key: str, response: CachedResponse) -> None:
        if not self.db:
            return
        persist = {k: v for k, v in asdict(response).items() if k != "cache_hit"}
        now_iso = datetime.now(UTC).isoformat()
        await self.db.execute(
            "INSERT INTO api_cache_v2 (cache_key, retrieved_at, data) VALUES (?, ?, ?)",
            (cache_key, now_iso, json.dumps(persist, ensure_ascii=False))
        )
        await self.db.commit()

    async def get_json(
        self,
        url: str,
        params: dict[str, Any],
        *,
        cache_key: str,
        as_of: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> CachedResponse:
        full_cache_key = self._cache_name(url, params, cache_key)
        cached = await self._get_from_cache(full_cache_key, as_of)
        if cached:
            return cached

        max_retries = int(self.settings["max_retries"])
        for attempt in range(max_retries + 1):
            await self._wait_for_spacing()
            try:
                headers = {**self.headers}
                if extra_headers:
                    headers.update(extra_headers)
                timeout = aiohttp.ClientTimeout(total=float(self.settings["timeout_seconds"]))
                async with self.session.get(url, params=params, headers=headers, timeout=timeout) as response:
                    await self._log_attempt(str(response.url), response.status, attempt, "response")
                    if response.status == 429:
                        retry_after = self._retry_after_seconds(response.headers.get("Retry-After"))
                        maximum = float(self.settings.get("max_retry_after_seconds", 60.0))
                        if retry_after is not None and retry_after > maximum:
                            raise RateLimitedError(
                                f"Provider requested waiting {retry_after:.1f}s; stopping instead of retrying early",
                                retry_after_seconds=retry_after,
                            )
                        if attempt >= max_retries:
                            response.raise_for_status()
                        await self._backoff(attempt, retry_after=response.headers.get("Retry-After"))
                        continue

                    if response.status >= 500:
                        if attempt >= max_retries:
                            response.raise_for_status()
                        await self._backoff(attempt, retry_after=response.headers.get("Retry-After"))
                        continue

                    response.raise_for_status()
                    try:
                        payload = await response.json()
                    except (ValueError, aiohttp.ContentTypeError, json.JSONDecodeError):
                        text = await response.text()
                        # Wrap non-JSON body (e.g. GDELT plain text)
                        payload = {"_non_json_body": text[:500]}
                    
                    result = CachedResponse(
                        status_code=response.status,
                        headers={k: v for k, v in response.headers.items()
                                 if k.lower() in {"date", "etag", "retry-after"}},
                        payload=payload,
                        fetched_at=datetime.now(UTC).isoformat(),
                        url=self._redact_url(str(response.url)),
                        cache_hit=False,
                    )
                    await self._save_to_cache(full_cache_key, result)
                    return result
            except aiohttp.ClientError as exc:
                await self._log_attempt(url, None, attempt, "request_exception")
                if attempt >= max_retries:
                    raise
                await self._backoff(attempt, retry_after=None)
                continue

        raise RuntimeError("API request exhausted retries without a response")

    async def post_json(
        self,
        url: str,
        body: dict[str, Any],
        *,
        cache_key: str,
        as_of: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> CachedResponse:
        full_cache_key = self._cache_name(url, body, cache_key)
        cached = await self._get_from_cache(full_cache_key, as_of)
        if cached:
            return cached

        max_retries = int(self.settings["max_retries"])
        for attempt in range(max_retries + 1):
            await self._wait_for_spacing()
            try:
                headers = {"Content-Type": "application/json", **self.headers}
                if extra_headers:
                    headers.update(extra_headers)
                timeout = aiohttp.ClientTimeout(total=float(self.settings["timeout_seconds"]))
                async with self.session.post(url, json=body, headers=headers, timeout=timeout) as response:
                    await self._log_attempt(str(response.url), response.status, attempt, "response")
                    if response.status == 429:
                        retry_after = self._retry_after_seconds(response.headers.get("Retry-After"))
                        maximum = float(self.settings.get("max_retry_after_seconds", 60.0))
                        if retry_after is not None and retry_after > maximum:
                            raise RateLimitedError(
                                f"Provider requested waiting {retry_after:.1f}s; stopping instead of retrying early",
                                retry_after_seconds=retry_after,
                            )
                        if attempt >= max_retries:
                            response.raise_for_status()
                        await self._backoff(attempt, retry_after=response.headers.get("Retry-After"))
                        continue

                    if response.status >= 500:
                        if attempt >= max_retries:
                            response.raise_for_status()
                        await self._backoff(attempt, retry_after=response.headers.get("Retry-After"))
                        continue

                    response.raise_for_status()
                    try:
                        payload = await response.json()
                    except (ValueError, aiohttp.ContentTypeError, json.JSONDecodeError):
                        text = await response.text()
                        payload = {"_non_json_body": text[:500]}
                    
                    result = CachedResponse(
                        status_code=response.status,
                        headers={k: v for k, v in response.headers.items()
                                 if k.lower() in {"date", "etag", "retry-after"}},
                        payload=payload,
                        fetched_at=datetime.now(UTC).isoformat(),
                        url=self._redact_url(str(response.url)),
                        cache_hit=False,
                    )
                    await self._save_to_cache(full_cache_key, result)
                    return result
            except aiohttp.ClientError as exc:
                await self._log_attempt(url, None, attempt, "request_exception")
                if attempt >= max_retries:
                    raise
                await self._backoff(attempt, retry_after=None)
                continue

        raise RuntimeError("API request exhausted retries without a response")

    async def _wait_for_spacing(self) -> None:
        async with self._spacing_lock:
            minimum = float(self.settings["min_interval_seconds"])
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < minimum:
                await asyncio.sleep(minimum - elapsed)
            self._last_request_at = time.monotonic()

    async def _backoff(self, attempt: int, retry_after: str | None) -> None:
        if self.settings.get("respect_retry_after", True) and retry_after:
            try:
                delay = float(retry_after)
            except ValueError:
                delay = 0.0
        else:
            delay = float(self.settings["backoff_factor_seconds"]) * (2 ** attempt)
        delay = min(delay, float(self.settings["max_backoff_seconds"]))
        delay += random.uniform(0, float(self.settings["jitter_seconds"]))
        await asyncio.sleep(delay)

    @staticmethod
    def _retry_after_seconds(value: str | None) -> float | None:
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            return None

    async def _log_attempt(self, url: str, status_code: int | None, attempt: int, event: str) -> None:
        entry = {
            "event": event,
            "attempt": attempt,
            "status_code": status_code,
            "url": self._redact_url(url),
            "logged_at": datetime.now(UTC).isoformat(),
        }
        with self.request_log_path.open("a", encoding="utf-8") as handle:
            json.dump(entry, handle, ensure_ascii=False)
            handle.write("\n")

    @staticmethod
    def _redact_url(url: str) -> str:
        if not url:
            return url
        parts = urlsplit(url)
        safe_query = []
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            safe_query.append(
                (key, "[REDACTED]" if key.lower() in {"api_key", "apikey", "key", "token"} else value)
            )
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(safe_query), parts.fragment))

    @staticmethod
    def _cache_name(url: str, params: dict[str, Any], cache_key: str) -> str:
        if isinstance(params, dict):
            # For GET requests where params is dict
            query = json.dumps({"url": url, "params": params, "cache_key": cache_key}, sort_keys=True)
        else:
            # For POST requests where params is body
            query = json.dumps({"url": url, "body": params, "cache_key": cache_key}, sort_keys=True)
        return hashlib.sha256(query.encode("utf-8")).hexdigest()
