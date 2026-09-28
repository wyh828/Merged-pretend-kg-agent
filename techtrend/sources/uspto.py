"""USPTO 客户端：本地 bulk 周书目 XML 解析（无 key、无网络）。

- 数据源形态：USPTO 首页书目 XML 已本地化到 `data/raw/`（授权 `ipgb*.xml` / 申请 `ipab*.xml`）。
- 每个周文件实为「多个 `<?xml?>` + 根元素」**拼接**的多文档流，需按 `<?xml` 边界切分后逐篇解析。
- 用 `ElementTree` 逐篇解析（不整棵 DOM 进内存），只保留 CPC 前缀命中（AI/ML）记录，
  且只取 KG 需要的字段：专利号/标题/摘要/受让人/发明人/日期/CPC。
- 增量由 CollectStage 以文件名日期游标管理（`data/.uspto_cursor`）。
"""
import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterator

log = logging.getLogger(__name__)


def _iter_documents(path: Path) -> Iterator[ET.Element]:
    """流式产出单篇书目文档（跳过 `<?xml?>` 与 `<!DOCTYPE>` 声明行）。"""
    buf: list[str] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            stripped = line.lstrip()
            if stripped.startswith("<?xml"):
                if buf:
                    yield _parse_buf(buf)
                buf = []
                continue
            if stripped.startswith("<!DOCTYPE"):
                continue
            buf.append(line.rstrip("\n"))
        if buf:
            yield _parse_buf(buf)


def _parse_buf(buf: list[str]) -> ET.Element | None:
    try:
        return ET.fromstring("\n".join(buf))
    except ET.ParseError as exc:
        log.warning("USPTO 单篇解析失败：%s", exc)
        return None


def _addressbook_name(ab: ET.Element) -> str | None:
    """addressbook → 显示名（orgname / name / last-name+first-name）。"""
    for tag in ("orgname", "name"):
        v = ab.findtext(tag)
        if v and v.strip():
            return v.strip()
    last = ab.findtext("last-name")
    first = ab.findtext("first-name")
    if last or first:
        return " ".join(x for x in (first, last) if x).strip()
    return None


def _cpc_code(cpc: ET.Element) -> str | None:
    """classification-cpc → section+class+subclass（如 G06N）。"""
    parts = [cpc.findtext(t) or "" for t in ("section", "class", "subclass")]
    code = "".join(parts).strip()
    return code or None


def _extract_citations(root: ET.Element) -> list[dict]:
    """<us-references-cited><us-citation> → 后向引用（本专利引用了谁）。

    返回 [{"doc_number","country","kind","date"}]，date 为被引专利公开日（YYYYMMDD）。
    仅取 US 专利引用（country==US）；非 US / 无 doc-number 的跳过。
    这是前向引用图的原料：反转后 (被引专利 ← 本专利) 即得前向引用。
    """
    out: list[dict] = []
    for cit in root.findall(".//us-references-cited/us-citation"):
        did = cit.find(".//patcit/document-id")
        if did is None:
            continue
        country = (did.findtext("country") or "").strip()
        if country and country != "US":
            continue
        doc_number = (did.findtext("doc-number") or "").strip()
        if not doc_number:
            continue
        date = (did.findtext("date") or "").strip()
        out.append(
            {
                "doc_number": doc_number,
                "country": country or "US",
                "kind": (did.findtext("kind") or "").strip(),
                "date": date,
            }
        )
    return out


def _uspto_id(doc_number: str) -> str:
    """doc-number → 统一专利 ID（与书目 `id` 字段一致：uspto:<doc-number>）。"""
    return f"uspto:{doc_number}"


class UsptoClient:
    def __init__(
        self,
        raw_dir: Path,
        grant_glob: str = "ipgb*/ipgb*.xml",
        app_glob: str = "ipab*/ipab*.xml",
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.grant_glob = grant_glob
        self.app_glob = app_glob

    # ---- 文件发现（供 CollectStage 按游标增量）----
    def list_files(self) -> list[Path]:
        """按文件名日期升序返回全部周书目 XML。"""
        files = sorted(
            set(self.raw_dir.glob(self.grant_glob))
            | set(self.raw_dir.glob(self.app_glob))
        )
        return sorted(files, key=file_date)

    # ---- 解析 ----
    def fetch_patents(
        self,
        files: list[Path],
        from_date: str | None,
        cpc_prefix: str,
        max_records: int,
    ) -> list[dict]:
        """逐文件流式解析，CPC 前缀 + 日期过滤 + max_records 截断。"""
        prefixes = [p.strip() for p in cpc_prefix.split(",") if p.strip()]
        from_yyyymmdd = from_date.replace("-", "") if from_date else None
        records: list[dict] = []
        for path in files:
            for root in _iter_documents(path):
                if root is None:
                    continue
                rec = self._parse_biblio(root)
                if rec is None:
                    continue
                if not self._match(rec, prefixes, from_yyyymmdd):
                    continue
                records.append(self.normalize(rec))
                if len(records) >= max_records:
                    return records
        return records

    def fetch_citations(
        self,
        files: list[Path],
        max_records: int = 1_000_000,
    ) -> list[dict]:
        """流式提取「后向引用边」（不按 CPC 过滤、不限制主题）。

        返回 [{"citing","citing_date","cited","cited_date"}]：
        - citing / cited 均为统一专利 ID（uspto:<doc-number>）；
        - citing_date = 本专利公开日（ISO），cited_date = 被引专利公开日（YYYYMMDD，可能缺失/不完整）。
        反转后即得前向引用（cited 被 cited_by citing）。
        这是专利引用时序（目标③回归真值 + 目标④ S 曲线）的原料，与书目解析解耦；
        专利引用图经 P2-1 证伪，不再作为 TKG 边源。
        """
        edges: list[dict] = []
        for path in files:
            for root in _iter_documents(path):
                if root is None:
                    continue
                doc_ref = root.find(".//publication-reference/document-id")
                if doc_ref is None:
                    continue
                doc_number = doc_ref.findtext("doc-number")
                if not doc_number:
                    continue
                date = doc_ref.findtext("date") or ""
                citing = _uspto_id(doc_number)
                citing_date = (
                    f"{date[:4]}-{date[4:6]}-{date[6:8]}" if len(date) == 8 else date
                )
                for cit in _extract_citations(root):
                    edges.append(
                        {
                            "citing": citing,
                            "citing_date": citing_date,
                            "cited": _uspto_id(cit["doc_number"]),
                            "cited_date": cit["date"],
                        }
                    )
                if len(edges) >= max_records:
                    return edges
        return edges

    @staticmethod
    def _match(rec: dict, prefixes: list[str], from_yyyymmdd: str | None) -> bool:
        cpc = rec.get("cpc") or []
        if not any(any(c.startswith(p) for p in prefixes) for c in cpc):
            return False
        if from_yyyymmdd:
            date = (rec.get("publication_date") or "").replace("-", "")
            if date and date < from_yyyymmdd:
                return False
        return True

    # ---- 单篇字段提取 ----
    def _parse_biblio(self, root: ET.Element) -> dict | None:
        doc_ref = root.find(".//publication-reference/document-id")
        if doc_ref is None:
            return None
        doc_number = doc_ref.findtext("doc-number")
        if not doc_number:
            return None
        kind = doc_ref.findtext("kind") or ""
        date = doc_ref.findtext("date") or ""  # YYYYMMDD

        # CPC 码（主分类 + 进一步分类，取 3 级）
        cpc_codes: list[str] = []
        for cpc in root.findall(".//classifications-cpc//classification-cpc"):
            code = _cpc_code(cpc)
            if code and code not in cpc_codes:
                cpc_codes.append(code)

        # 受让人 / 发明人（addressbook 名称）
        assignees: list[str] = []
        for a in root.findall(".//assignees/assignee/addressbook"):
            name = _addressbook_name(a)
            if name and name not in assignees:
                assignees.append(name)
        inventors: list[str] = []
        for inv in root.findall(".//inventors/inventor/addressbook"):
            name = _addressbook_name(inv)
            if name and name not in inventors:
                inventors.append(name)

        # 摘要（abstract 下多个 <p> 拼接）
        abstract_parts = [p.text or "" for p in root.findall(".//abstract/p")]
        abstract = " ".join(x.strip() for x in abstract_parts if x.strip())

        return {
            "id": f"uspto:{doc_number}",
            "title": root.findtext(".//invention-title") or "",
            "abstract": abstract,
            "assignees": assignees,
            "inventors": inventors,
            "publication_date": f"{date[:4]}-{date[4:6]}-{date[6:8]}" if len(date) == 8 else date,
            "cpc": cpc_codes,
            "kind": kind,
            "citations": _extract_citations(root),
        }

    # ---- 归一化 ----
    @staticmethod
    def normalize(record: dict) -> dict:
        record = dict(record)
        record.setdefault("source", "uspto")
        return record

    def close(self) -> None:
        pass

    def __enter__(self) -> "UsptoClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def file_date(path: Path) -> str:
    """从文件名提取日期（如 ipgb20260915.xml → 20260915），失败返回空串。"""
    m = re.search(r"(\d{8})", path.name)
    return m.group(1) if m else ""
