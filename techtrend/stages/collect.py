"""采集阶段（P2 多源）：按 collect_sources 逐源采集到 data/interim。

- interim 文件：works.jsonl（OpenAlex）/ arxiv.jsonl / patents.jsonl / news.jsonl（GDELT+RSSHub）/ github.jsonl。
- 每源独立 try/except（单源失败记 "error" 不影响他源）；增量游标每源一个 `data/.<source>_cursor`。
- 按 id 去重保证幂等（续跑不重复）；raw 快照写 `data/raw/<source>/<date>/`。
"""
import logging
import re
import shutil
from datetime import datetime
from datetime import timezone
from pathlib import Path

from techtrend.config import Settings
from techtrend.io import append_jsonl, read_jsonl, write_jsonl
from techtrend.sources.arxiv import ArxivClient
from techtrend.sources.crossref import CrossrefClient
from techtrend.sources.gdelt import GdeltClient
from techtrend.sources.github import GithubClient
from techtrend.sources.openalex import OpenAlexClient
from techtrend.sources.rsshub import RssHubClient
from techtrend.sources.uspto import UsptoClient, file_date
from techtrend.stages.base import Stage
from techtrend.storage import write_snapshot_metadata, reserve_snapshot_path

log = logging.getLogger(__name__)


def _dedupe_by_id(records: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for r in records:
        rid = r.get("id")
        if rid and rid not in seen:
            seen.add(rid)
            out.append(r)
    return out


def _append_dedup(interim_path: Path, records: list[dict]) -> int:
    """与存量 interim 按 id 去重后追加，返回新增条数。"""
    existing = {r.get("id") for r in read_jsonl(interim_path) if r.get("id")}
    observed = datetime.now(timezone.utc).isoformat()
    new = [{**r, "collected_at": observed, "dataset_version": interim_path.parent.parent.name}
           for r in records if r.get("id") and r.get("id") not in existing]
    append_jsonl(interim_path, new)
    return len(new)


def _write_raw(raw_dir: Path, source: str, run_date: str, tag: str, records: list[dict],
               *, source_url: str | None = None, query: dict | None = None) -> Path:
    directory = raw_dir / source / run_date
    directory.mkdir(parents=True, exist_ok=True)
    version = 0
    while True:
        path = directory / f"{source}_{tag}_{version:02d}.jsonl"
        try:
            # Exclusive creation preserves prior snapshots even on concurrent runs.
            import json
            with path.open("x", encoding="utf-8") as file:
                for record in records:
                    file.write(json.dumps(record, ensure_ascii=False) + "\n")
            write_snapshot_metadata(path, source=source, row_count=len(records),
                                    dataset_version=raw_dir.parent.name,
                                    source_url=source_url, query=query)
            return path
        except FileExistsError:
            version += 1


def _read_cursor(s: Settings, name: str) -> str | None:
    f = s.data_dir / f".{name}_cursor"
    if f.exists():
        return f.read_text(encoding="utf-8").strip() or None
    return None


def _write_cursor(s: Settings, name: str, value: str) -> None:
    (s.data_dir / f".{name}_cursor").write_text(value, encoding="utf-8")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _cleanup_old_weeks(raw_dir: Path, keep_weeks: int) -> int:
    """归档超过 keep_weeks 周的 ipgb/ipab 周目录（移到 _archive，非删除）。"""
    if keep_weeks <= 0:
        return 0
    dirs = [
        d for d in raw_dir.iterdir()
        if d.is_dir() and re.match(r"^(ipgb|ipab)\d{8}_wk\d+$", d.name)
    ]
    dates = sorted({_dir_date(d) for d in dirs}, reverse=True)
    keep = set(dates[:keep_weeks])
    archived = 0
    for d in dirs:
        if _dir_date(d) and _dir_date(d) not in keep:
            target = raw_dir / "_archive" / d.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(d), str(target))
            archived += 1
    if archived:
        log.info("USPTO 归档旧周文件 %d 个目录到 _archive", archived)
    return archived


def _dir_date(d: Path) -> str:
    m = re.search(r"(\d{8})", d.name)
    return m.group(1) if m else ""


class CollectStage(Stage):
    name = "collect"

    def run(self) -> dict:
        s = self.settings
        interim_dir = s.data_dir / "interim"
        raw_dir = s.data_dir / "raw"
        interim_dir.mkdir(parents=True, exist_ok=True)
        raw_dir.mkdir(parents=True, exist_ok=True)

        sources = [x.strip() for x in s.collect_sources.split(",") if x.strip()]
        summary: dict[str, object] = {}
        for src in sources:
            handler = _HANDLERS.get(src)
            if handler is None:
                log.warning("未知数据源 %s，跳过", src)
                summary[src] = "unknown"
                continue
            try:
                summary[src] = handler(s, interim_dir, raw_dir)
            except Exception as exc:  # noqa: BLE001 —— 单源失败不影响他源
                log.exception("collect[%s] 失败", src)
                summary[src] = "error"

        log.info("collect 完成：%s", summary)
        status = "error" if any(v in ("error", "unknown") for v in summary.values()) else "ok"
        return {"stage": self.name, "status": status, "sources": summary}


# ---------------------------------------------------------------------------
# 各源处理器（返回新增条数）
# ---------------------------------------------------------------------------
def _collect_openalex(s: Settings, interim_dir: Path, raw_dir: Path) -> int:
    from_date = _read_cursor(s, "openalex") or s.openalex_from_date
    concept_ids = [c.strip() for c in s.openalex_concept_ids.split(",") if c.strip()]
    client = OpenAlexClient(mailto=s.openalex_mailto, api_key=s.openalex_api_key, per_page=s.openalex_per_page)
    try:
        works = [client.normalize(w) for w in client.fetch_works(from_date, concept_ids, s.openalex_max_works)]
    finally:
        client.close()
    works = _dedupe_by_id(works)
    tag = re.sub(r"[^0-9A-Za-z-]", "_", from_date or "initial")
    _write_raw(raw_dir, "openalex", _today(), tag, works, source_url="https://api.openalex.org/works",
               query={"from_publication_date": from_date, "concept_ids": concept_ids, "max_works": s.openalex_max_works})
    new = _append_dedup(interim_dir / "works.jsonl", works)
    _write_cursor(s, "openalex", _today())
    return new


def _collect_crossref(s: Settings, interim_dir: Path, raw_dir: Path) -> int:
    """CrossRef（第 7 源）：DOI 锚点 + mailto polite pool。写入 works.jsonl（与 OpenAlex
    同文件，同属「学术 works」，下游 align 按 DOI 强锚点合并去重）。"""
    from_date = _read_cursor(s, "crossref") or s.crossref_from_date
    client = CrossrefClient(mailto=s.crossref_mailto, per_page=s.crossref_per_page)
    try:
        works = [
            client.normalize(w)
            for w in client.fetch_works(from_date, None, s.crossref_max_records)
        ]
    finally:
        client.close()
    works = [w for w in works if w.get("id")]
    works = _dedupe_by_id(works)
    tag = re.sub(r"[^0-9A-Za-z-]", "_", from_date or "initial")
    _write_raw(raw_dir, "crossref", _today(), tag, works, source_url="https://api.crossref.org/works",
               query={"from_publication_date": from_date, "max_records": s.crossref_max_records})
    new = _append_dedup(interim_dir / "works.jsonl", works)
    _write_cursor(s, "crossref", _today())
    return new


def _collect_arxiv(s: Settings, interim_dir: Path, raw_dir: Path) -> int:
    from_date = _read_cursor(s, "arxiv") or s.arxiv_from_date
    categories = [c.strip() for c in s.arxiv_categories.split(",") if c.strip()]
    client = ArxivClient()
    try:
        records = client.fetch_works(from_date, categories, s.arxiv_max_records)
    finally:
        client.close()
    records = _dedupe_by_id(records)
    tag = re.sub(r"[^0-9A-Za-z-]", "_", from_date or "initial")
    _write_raw(raw_dir, "arxiv", _today(), tag, records, source_url="https://export.arxiv.org/api/query",
               query={"from_date": from_date, "categories": categories, "max_records": s.arxiv_max_records})
    new = _append_dedup(interim_dir / "arxiv.jsonl", records)
    _write_cursor(s, "arxiv", _today())
    return new


def _collect_uspto(s: Settings, interim_dir: Path, raw_dir: Path) -> int:
    uspto_dir = Path(s.uspto_raw_dir)
    client = UsptoClient(uspto_dir, s.uspto_grant_glob, s.uspto_app_glob)
    files = client.list_files()
    cursor = _read_cursor(s, "uspto")  # 上次处理到的最新文件名日期
    new_files = [f for f in files if file_date(f) > (cursor or "")] if cursor else files
    records = client.fetch_patents(new_files, None, s.uspto_cpc_prefix, s.uspto_max_records)
    _write_raw(raw_dir, "uspto", _today(), "batch", records, source_url=str(uspto_dir),
               query={"files": [f.name for f in new_files], "cpc_prefix": s.uspto_cpc_prefix, "max_records": s.uspto_max_records})
    new = _append_dedup(interim_dir / "patents.jsonl", records)
    latest = max((file_date(f) for f in files), default=None)
    if latest:
        _write_cursor(s, "uspto", latest)
    _cleanup_old_weeks(uspto_dir, s.uspto_keep_weeks)
    return new


def _collect_gdelt(s: Settings, interim_dir: Path, raw_dir: Path) -> int:
    from_date = _read_cursor(s, "gdelt") or s.gdelt_from_date
    themes = [t.strip() for t in s.gdelt_theme_filter.split(",") if t.strip()]
    client = GdeltClient()
    try:
        records = client.fetch_news(from_date, themes, s.gdelt_max_records)
    finally:
        client.close()
    records = _dedupe_by_id(records)
    _write_raw(raw_dir, "gdelt", _today(), "batch", records, source_url="https://api.gdeltproject.org/api/v2/doc/doc",
               query={"from_date": from_date, "themes": themes, "max_records": s.gdelt_max_records})
    new = _append_dedup(interim_dir / "news.jsonl", records)
    _write_cursor(s, "gdelt", _today())
    return new


def _collect_github(s: Settings, interim_dir: Path, raw_dir: Path) -> int:
    from_date = _read_cursor(s, "github") or s.github_from_date
    topics = [t.strip() for t in s.github_topics.split(",") if t.strip()]
    client = GithubClient(token=s.github_token)
    try:
        repos = client.fetch_repos(from_date, topics, s.github_min_stars, s.github_max_repos)
    finally:
        client.close()
    repos = _dedupe_by_id(repos)
    _write_raw(raw_dir, "github", _today(), "batch", repos, source_url="https://api.github.com/search/repositories",
               query={"from_date": from_date, "topics": topics, "min_stars": s.github_min_stars, "max_repos": s.github_max_repos})
    new = _append_dedup(interim_dir / "github.jsonl", repos)
    # 每日 star 快照（P3 趋势核心信号，从一开始就记录）
    now = datetime.now().isoformat(timespec="seconds")
    stars = [
        {"full_name": r.get("name"), "stars": r.get("stars"), "fetched_at": now}
        for r in repos if r.get("name")
    ]
    append_jsonl(interim_dir / "github_stars.jsonl", stars)
    _write_cursor(s, "github", _today())
    return new


def _collect_rsshub(s: Settings, interim_dir: Path, raw_dir: Path) -> int:
    routes = [r.strip() for r in s.rsshub_routes.split(",") if r.strip()]
    client = RssHubClient(base_url=s.rsshub_base_url)
    try:
        items = client.fetch_items(routes, s.rsshub_max_items)
    finally:
        client.close()
    items = _dedupe_by_id(items)
    _write_raw(raw_dir, "rsshub", _today(), "batch", items, source_url=s.rsshub_base_url,
               query={"routes": routes, "max_items": s.rsshub_max_items})
    new = _append_dedup(interim_dir / "news.jsonl", items)
    return new


def _collect_patent_citations(s: Settings, interim_dir: Path, raw_dir: Path) -> int:
    """专利前向引用图（P0-1）：按 patent_citation_source 取后向引用对 → 反转 → 落 jsonl。

    三源同构（本地 USPTO XML / PatentsView bulk / BigQuery CSV），统一产出
    patent_citations.jsonl（head=被引专利, relation=cited_by, tail=引用专利, time=引用日）。
    免 key；本地 XML 路线零下载、立即可用（时态跨度受限于已保留的周文件数）。
    """
    import json
    from datetime import date

    from techtrend.prediction.citations import forward_fact
    from techtrend.sources.patentsview import (
        PatentsViewBulkClient,
        iter_citation_tsv,
        parse_bigquery_csv,
        parse_patent_dates,
    )

    source = s.patent_citation_source.strip()
    max_time = s.tkg_max_time or date.today().isoformat()
    min_time = s.patent_citation_min_time
    out_path = Path(s.patent_citations_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if source == "uspto_local":
        # 本地 XML：单周时态（全 time≈某一天），增量去重合并（幂等）。
        client = UsptoClient(Path(s.uspto_raw_dir), s.uspto_grant_glob, s.uspto_app_glob)
        files = client.list_files()
        backward = client.fetch_citations(files, max_records=s.patent_citation_max_edges)
        log.info("本地 USPTO XML 抽取后向引用对 %d 条（文件 %d 个）", len(backward), len(files))
        facts = [forward_fact(e, min_time=min_time, max_time=max_time) for e in backward]
        facts = [f for f in facts if f is not None]
        existing = {
            (r.get("head"), r.get("relation"), r.get("tail"), r.get("time"))
            for r in read_jsonl(out_path)
        }
        merged = [f for f in facts if (f["head"], f["relation"], f["tail"], f["time"]) not in existing]
        if merged:
            append_jsonl(out_path, merged)
            _write_raw(raw_dir, "patent_citations", _today(), "batch", merged,
                       source_url=str(s.uspto_raw_dir), query={"mode": source, "min_time": min_time, "max_time": max_time})
        log.info("patent_citations：新增 %d / 总 %d 条 → %s", len(merged), len(existing) + len(merged), out_path)
        return len(merged)

    if source == "patentsview":
        # 终版表名：g_patent.tsv（旧 patent.tsv）、g_us_patent_citation.tsv（旧 uspatentcitation.tsv）。
        # Preserve all in-window facts; sampling belongs inside each training fold.
        if s.patent_citation_max_patents > 0:
            raise ValueError("PATENT_CITATION_MAX_PATENTS 必须为 0：按未来总引用 top-N 采集会泄漏；规模控制应按时间分批或逐折选样")
        with PatentsViewBulkClient(Path(s.uspto_raw_dir) / "patentsview") as client:
            patent_tsv = client.download("g_patent.tsv")
            cite_tsv = client.download("g_us_patent_citation.tsv")
        date_by_id = parse_patent_dates(patent_tsv)
        log.info("g_patent 日期映射 %d 条", len(date_by_id))

        snapshot = reserve_snapshot_path(raw_dir / "patent_citations" / _today(), "patent_citations_bulk")
        n = 0
        with open(snapshot, "w", encoding="utf-8") as f:
            for e in iter_citation_tsv(cite_tsv, None, date_by_id):
                fact = forward_fact(e, min_time=min_time, max_time=max_time)
                if fact is None:
                    continue
                f.write(json.dumps(fact, ensure_ascii=False) + "\n")
                n += 1
        write_snapshot_metadata(snapshot, source="patentsview", row_count=n,
                                dataset_version=s.data_dir.name, source_url=str(cite_tsv),
                                query={"min_time": min_time, "max_time": max_time, "candidate_selection": "none"})
        shutil.copyfile(snapshot, out_path)
        log.info("patentsview 前向引用事实 %d 条 → %s（独立快照 %s）", n, out_path, snapshot)
        return n

    if source == "bigquery":
        csv_path = interim_dir / "uspto_forward_citations.csv"
        if not csv_path.exists():
            raise FileNotFoundError(f"BigQuery 导出文件不存在：{csv_path}")
        backward = parse_bigquery_csv(csv_path)
        log.info("BigQuery CSV 解析后向引用对 %d 条", len(backward))
        facts = [forward_fact(e, min_time=min_time, max_time=max_time) for e in backward]
        facts = [f for f in facts if f is not None]
        snapshot = _write_raw(raw_dir, "patent_citations", _today(), "batch", facts,
                              source_url=str(csv_path), query={"mode": source, "min_time": min_time, "max_time": max_time})
        shutil.copyfile(snapshot, out_path)
        log.info("bigquery 前向引用事实 %d 条 → %s（覆盖写）", len(facts), out_path)
        return len(facts)

    if source == "odp":
        # USPTO Open Data Portal（PatentsView 2026-03 退役后的继任者）。
        # 需免费 MyUSPTO 账号 + ID.me 身份核验 + ODP API key（X-API-Key），
        # 无法在本机自动获取；拿到 key 后在此实现 ODP 引文 bulk 下载。
        log.error(
            "ODP（USPTO Open Data Portal）需 ODP API key：注册 data.uspto.gov/myodp "
            "→ ID.me 身份核验 → data.uspto.gov/apis/getting-started 申请 key。"
            "PatentsView 旧 S3 bulk（2026-03 退役）与 bulkdata.uspto.gov（NXDOMAIN）均已下线。"
        )
        raise NotImplementedError("ODP 采集接口尚未实现，不能把未执行报告为 0 条成功")

    raise ValueError(f"未知 patent_citation_source={source}")


_HANDLERS = {
    "openalex": _collect_openalex,
    "crossref": _collect_crossref,
    "arxiv": _collect_arxiv,
    "uspto": _collect_uspto,
    "gdelt": _collect_gdelt,
    "github": _collect_github,
    "rsshub": _collect_rsshub,
    "patent_citations": _collect_patent_citations,
}
