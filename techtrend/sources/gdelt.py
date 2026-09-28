"""GDELT GKG 客户端：日文件下载 / unzip / CSV 流式解析。

- 端点 `http://data.gdeltproject.org/gdeltv2/<YYYYMMDDHHMMSS>.gkg.csv.zip`（默认日 0 点文件）。
- GKG 为制表符分隔（v2 首行有表头）；按 `theme_filter` 过滤 + `max_records` 截断（体量巨大）。
- 无 key、匿名；仅 429/5xx 与传输异常重试。增量游标 `data/.gdelt_cursor` 由 CollectStage 管理。
"""
import csv
import io
import logging
import zipfile
from datetime import datetime, timedelta
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

# GKG 某些字段（V2Extras/URL 等）极长，超出 csv 默认 131072 上限，须放宽。
csv.field_size_limit(10**8)

_BASE_URL = "http://data.gdeltproject.org/gdeltv2"

# GKG v2 关键列下标（0-based，按官方 Codebook）
_COL_ID = 0
_COL_DATE = 1
_COL_THEMES = 8
_COL_PERSONS = 12
_COL_ORGS = 14
_COL_TONE = 15


def _split_v2_field(value: str) -> list[str]:
    """解析 GKG V2 字段 `name,count;name,count;...` → 去重后的名字列表（保序）。"""
    out: list[str] = []
    seen: set[str] = set()
    for entry in value.split(";"):
        name = entry.split(",", 1)[0].strip()
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _should_retry(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, (httpx.TransportError, httpx.TimeoutException))


def _day_files(from_date: str | None, days_back: int = 1) -> list[str]:
    """返回需下载的日文件时间戳（YYYYMMDDHHMMSS），默认最近 days_back 天。"""
    end = datetime.now().date()
    start = (
        datetime.strptime(from_date, "%Y-%m-%d").date()
        if from_date
        else end - timedelta(days=days_back)
    )
    stamps: list[str] = []
    d = start
    while d <= end:
        stamps.append(d.strftime("%Y%m%d") + "000000")
        d += timedelta(days=1)
    return stamps


class GdeltClient:
    def __init__(self, timeout: float = 60.0) -> None:
        self.client = httpx.Client(timeout=timeout, follow_redirects=True)

    @retry(
        retry=retry_if_exception(_should_retry),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        reraise=True,
    )
    def _download(self, stamp: str) -> bytes:
        url = f"{_BASE_URL}/{stamp}.gkg.csv.zip"
        resp = self.client.get(url)
        resp.raise_for_status()
        return resp.content

    # ---- 采集 ----
    def fetch_news(
        self,
        from_date: str | None,
        theme_filter: list[str],
        max_records: int,
    ) -> list[dict]:
        """按日下载 GKG，主题过滤 + max_records 截断。"""
        themes = {t.strip() for t in theme_filter if t.strip()}
        records: list[dict] = []
        for stamp in _day_files(from_date):
            if len(records) >= max_records:
                break
            try:
                content = self._download(stamp)
            except Exception as exc:  # noqa: BLE001 —— 单日下载失败不阻断他日
                log.warning("GDELT 日文件 %s 下载失败：%s", stamp, exc)
                continue
            got = self._parse_zip(content, themes, max_records - len(records))
            records.extend(got)
            log.info("GDELT %s：命中 %d 条，累计 %d/%d", stamp, len(got), len(records), max_records)
        return records

    def _parse_zip(self, content: bytes, themes: set[str], limit: int) -> list[dict]:
        """解压 zip，流式读 CSV，按主题过滤后截断。"""
        out: list[dict] = []
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            name = zf.namelist()[0]  # 每个 zip 只有一个 csv
            with zf.open(name) as f:
                reader = csv.reader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"), delimiter="\t")
                for row in reader:
                    if len(row) <= _COL_TONE:
                        continue
                    if row[_COL_ID] == "GKGRECORDID":  # 跳过表头
                        continue
                    rec = self.normalize(row)
                    if themes and not (set(rec["themes"]) & themes):
                        continue
                    out.append(rec)
                    if len(out) >= limit:
                        break
        return out

    # ---- 归一化 ----
    @staticmethod
    def normalize(row: list[str]) -> dict:
        date_raw = row[_COL_DATE] if len(row) > _COL_DATE else ""
        date = (
            f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}"
            if len(date_raw) >= 8
            else date_raw
        )
        tone: float | None = None
        try:
            tone = float(row[_COL_TONE].split(",")[0])
        except (ValueError, IndexError):
            tone = None
        themes = _split_v2_field(row[_COL_THEMES]) if len(row) > _COL_THEMES else []
        persons = _split_v2_field(row[_COL_PERSONS]) if len(row) > _COL_PERSONS else []
        organizations = _split_v2_field(row[_COL_ORGS]) if len(row) > _COL_ORGS else []
        return {
            "id": f"gdelt:{row[_COL_ID]}",
            "source": "gdelt",
            "title": None,
            "text": " ".join(
                f"{label}:{', '.join(vals)}"
                for label, vals in (("themes", themes), ("persons", persons), ("orgs", organizations))
                if vals
            ),
            "themes": themes,
            "persons": persons,
            "organizations": organizations,
            "tone": tone,
            "publication_date": date,
        }

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "GdeltClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
