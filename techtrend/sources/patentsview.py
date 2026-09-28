"""PatentsView 前向引用数据源（P0-1，免 key）。

两条子路线（均免 key，见 P4_P3_METRIC_OPT_PLAN.md §2 路线①）：

- **子路线 A（bulk 下载，首选）**：下载 PatentsView bulk 引文对表
  `g_us_patent_citation.tsv.zip`（专利→被引专利，终版表名，旧名 `uspatentcitation.tsv`）
  + `g_patent.tsv.zip`（patent_id → 专利号/授权日，旧名 `patent.tsv`），
  本地反转即得前向引用。确定性、零配额，缺点是 US-only + 需整表下载（数百 MB～GB）。
- **子路线 B（BigQuery 导出，备选）**：`patents-public-data.patents.publications`
  反向 join 导出为 CSV 后由本模块解析。schema 以控制台实际为准，不照抄字段名。

产物契约（与本地 USPTO XML 抽取对齐，三源合一）：
    data/interim/patent_citations.jsonl
    每行 {"head", "relation", "tail", "time", "head_date", "source"}
    head=被引专利（奠基专利），relation="cited_by"，tail=引用专利，time=引用发生时间（引用专利公开日）。

本模块只负责「拿数据 + 归一化到统一后向引用对」，前向反转与聚合在
`techtrend.prediction.citations` 完成。
"""
import csv
import logging
import zipfile
from pathlib import Path
from typing import Iterable

import httpx

log = logging.getLogger(__name__)

# PatentsView bulk 下载根（S3 公开桶）。
# 注意：PatentsView 于 2026-03-20 退役，该 S3 桶已下线（请求 403）；终版数据迁移至
# USPTO Open Data Portal（data.uspto.gov，需 ODP API key + ID.me）与 Zenodo 镜像
# （zenodo.org/records/15058362）。本机无直连外网、唯一出口 Oracle Cloud IP 被 Zenodo
# WAF 403，故 bulk 文件需用户手动下载后放到 dest_dir，`download()` 检测到 .zip 即跳过
# 网络只解压。终版表名带 `g_` 前缀（granted）：`g_us_patent_citation.tsv`、
# `g_patent.tsv`。
_BULK_ROOT = "https://s3.amazonaws.com/data.patentsview.org/download"

# 引文对表列名（以实际表头为准，解析时按表头名定位，不硬编码列序）。
# 终版（12/31/2024）把引文表列改名：citation_id→citation_patent_id、date→citation_date；
# patent 表 patent_id/patent_number/patent_date 不变。下面 _CITATION_FILE/_PATENT_FILE
# 与 parse_* 均按「新旧兼容」处理。
_CITATION_FILE = "g_us_patent_citation.tsv"
_PATENT_FILE = "g_patent.tsv"


class PatentsViewBulkClient:
    """下载并解析 PatentsView bulk 引文对表（免 key）。"""

    def __init__(self, dest_dir: Path, timeout: float = 120.0) -> None:
        self.dest_dir = Path(dest_dir)
        self.dest_dir.mkdir(parents=True, exist_ok=True)
        self.client = httpx.Client(timeout=timeout, follow_redirects=True, trust_env=False)

    # ---- 下载 ----
    def download(self, filename: str, force: bool = False) -> Path:
        """下载 bulk 文件（.tsv.zip）到 dest_dir，返回解压后的 .tsv 路径。

        .tsv 已存在则直接返回；否则若 .zip 已存在（用户手动下载，本机网络可能无法直连
        Zenodo/PatentsView）则只解压、不联网；否则才联网下载。
        """
        zip_path = self.dest_dir / f"{filename}.zip"
        tsv_path = self.dest_dir / filename
        if tsv_path.exists() and not force:
            log.info("已存在 %s，跳过下载", tsv_path.name)
            return tsv_path
        if zip_path.exists() and not force:
            log.info("已存在 %s（手动下载），跳过联网，直接解压", zip_path.name)
        else:
            url = f"{_BULK_ROOT}/{filename}.zip"
            log.info("下载 %s（可能数百 MB，请耐心）", url)
            with self.client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(zip_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=1 << 20):
                        f.write(chunk)
        log.info("解压 %s", zip_path.name)
        with zipfile.ZipFile(zip_path) as zf:
            member = next((n for n in zf.namelist() if n.endswith(filename)), filename)
            zf.extract(member, self.dest_dir)
            extracted = self.dest_dir / member
            if extracted != tsv_path and extracted.exists():
                extracted.replace(tsv_path)
        return tsv_path

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "PatentsViewBulkClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# ---------------------------------------------------------------------------
# 归一化：PatentsView bulk / BigQuery CSV → 统一后向引用对
# ---------------------------------------------------------------------------
def iter_citation_tsv(
    path: Path,
    patent_number_by_id: dict[str, str] | None = None,
    patent_date_by_id: dict[str, str] | None = None,
) -> Iterable[dict]:
    """流式解析 `g_us_patent_citation.tsv` → 逐条 yield 后向引用对 dict（不落 list）。

    供 100M 级引用对流式处理避免 OOM。表头按名定位（新旧列名兼容）：
    patent_id（引用专利）、citation_id/citation_patent_id（被引专利）、
    date/citation_date（引用日）。yield 的 dict 与 `UsptoClient.fetch_citations` 同构：
    {"citing","citing_date","cited","cited_date"}。
    """
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        cols = {c.lower(): c for c in (reader.fieldnames or [])}
        pid = _col(cols, "patent_id")
        # 终版改名：citation_id→citation_patent_id、date→citation_date
        cid = _col(cols, "citation_id", "citation_patent_id")
        dcol = _col(cols, "date", "citation_date")
        if not pid or not cid:
            log.error("引文表缺 patent_id/(citation_id|citation_patent_id) 列，实际表头：%s", reader.fieldnames)
            return
        for row in reader:
            citing_id = (row.get(pid) or "").strip()
            cited_id = (row.get(cid) or "").strip()
            if not citing_id or not cited_id:
                continue
            yield {
                "citing": _map_id(citing_id, patent_number_by_id),
                "citing_date": _map_date(citing_id, patent_date_by_id)
                or _norm_date(row.get(dcol) or ""),
                "cited": _map_id(cited_id, patent_number_by_id),
                "cited_date": _map_date(cited_id, patent_date_by_id),
            }


def parse_citation_tsv(
    path: Path,
    patent_number_by_id: dict[str, str] | None = None,
    patent_date_by_id: dict[str, str] | None = None,
) -> list[dict]:
    """解析 `g_us_patent_citation.tsv` → 后向引用对列表（list(iter_citation_tsv(...))）。

    小数据量用；大文件请用 `iter_citation_tsv` 流式处理避免 OOM。
    """
    return list(iter_citation_tsv(path, patent_number_by_id, patent_date_by_id))


def parse_patent_dates(path: Path) -> dict[str, str]:
    """解析 `g_patent.tsv` → {patent_id: ISO patent_date}（只取日期，供流式引文处理）。

    终版 g_patent 的 patent_id 即专利号本身；只建日期映射，省去 number_by_id（新 schema 下是
    恒等映射），流式处理 100M 引文时更省内存。
    """
    date_by_id: dict[str, str] = {}
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        cols = {c.lower(): c for c in (reader.fieldnames or [])}
        pid = _col(cols, "patent_id")
        pdate = _col(cols, "patent_date")
        if not pid or not pdate:
            log.error("patent 表缺 patent_id/patent_date 列，实际表头：%s", reader.fieldnames)
            return date_by_id
        for row in reader:
            pidv = (row.get(pid) or "").strip()
            if not pidv:
                continue
            date_by_id[pidv] = _norm_date(row.get(pdate) or "")
    return date_by_id


def parse_patent_tsv(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """解析 PatentsView `g_patent.tsv` → (patent_number_by_id, patent_date_by_id)。

    表头按名定位：patent_id（终版 g_patent 无 patent_number 列，patent_id 即专利号本身）、
    patent_number（旧 patent.tsv 才有，可选）、patent_date（归一化为 ISO YYYY-MM-DD）。
    """
    number_by_id: dict[str, str] = {}
    date_by_id: dict[str, str] = {}
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        cols = {c.lower(): c for c in (reader.fieldnames or [])}
        pid = _col(cols, "patent_id")
        pnum = _col(cols, "patent_number")
        pdate = _col(cols, "patent_date")
        if not pid:
            log.error("patent 表缺 patent_id 列，实际表头：%s", reader.fieldnames)
            return number_by_id, date_by_id
        for row in reader:
            pidv = (row.get(pid) or "").strip()
            if not pidv:
                continue
            # 终版 g_patent 无 patent_number 列，patent_id 即专利号；旧表才走 patent_number
            pnumv = (row.get(pnum) or "").strip() if pnum else ""
            number_by_id[pidv] = pnumv or pidv
            date_by_id[pidv] = _norm_date(row.get(pdate) or "")
    return number_by_id, date_by_id


def _norm_date(d: str) -> str:
    """日期归一化为 ISO YYYY-MM-DD（g_patent.patent_date 实际已是 ISO；兜底 M/D/YYYY）。"""
    d = (d or "").strip()
    if not d:
        return ""
    if len(d) >= 10 and d[4] == "-" and d[:4].isdigit():
        return d[:10]
    parts = d.split("/")
    if len(parts) == 3:
        try:
            m, dd, y = int(parts[0]), int(parts[1]), int(parts[2])
            if y < 100:
                y += 1900 if y > 50 else 2000
            return f"{y:04d}-{m:02d}-{dd:02d}"
        except ValueError:
            return ""
    return d[:10]


def _col(cols: dict[str, str], *names: str) -> str | None:
    """按候选列名（小写）定位实际表头列，返回首个命中的原始列名；无则 None。"""
    for n in names:
        if n in cols:
            return cols[n]
    return None


def _map_id(pid: str, number_by_id: dict[str, str] | None) -> str:
    """patent_id → 统一专利 ID（uspto:<doc-number>）。无映射时退化为 uspto:<raw_id>。"""
    num = (number_by_id or {}).get(pid)
    return f"uspto:{num or pid}"


def _map_date(pid: str, date_by_id: dict[str, str] | None) -> str:
    return (date_by_id or {}).get(pid, "")


def parse_bigquery_csv(
    path: Path,
    patent_col: str = "patent",
    cited_by_col: str = "cited_by",
    cited_date_col: str = "cited_by_date",
    patent_date_col: str = "publication_date",
) -> list[dict]:
    """解析 BigQuery 导出的前向引用 CSV（路线②备选）。

    默认列：patent=被引专利号 / cited_by=引用专利号 / cited_by_date=引用发生日 /
    publication_date=被引专利公开日。schema 以控制台实际导出为准，用列名参数覆盖。
    返回 [{"citing","citing_date","cited","cited_date"}]（把前向引用重排为后向对，与其余源同构）。
    """
    edges: list[dict] = []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cited = (row.get(patent_col) or "").strip()
            citing = (row.get(cited_by_col) or "").strip()
            if not cited or not citing:
                continue
            edges.append(
                {
                    "citing": f"uspto:{citing}",
                    "citing_date": (row.get(cited_date_col) or "").strip(),
                    "cited": f"uspto:{cited}",
                    "cited_date": (row.get(patent_date_col) or "").strip(),
                }
            )
    return edges
