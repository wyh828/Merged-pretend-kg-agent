"""结构化三元组抽取（非 LLM）：纯字段映射，零幻觉、零 abstract 依赖。

关系 → 来源字段（各源）：
    OpenAlex  belongs_to / authored_by / affiliated_with / cites
    arXiv     belongs_to（category → Concept）/ authored_by（作者）
    USPTO     belongs_to（CPC → Concept）/ affiliated_with（受让人→Institution）/ authored_by（发明人→Person）
    GitHub    belongs_to（topic → Concept）
    GDELT     belongs_to（theme → Concept）/ mentions（persons/organizations）
    RSSHub    无结构化（LLM 兜底）

节点契约（供对齐与图谱写入）：
    每行 {id, type, entity_id, name, source, ...extra}
    - `id`：源内唯一键（triples 的 head/tail 引用它）；有强 ID 的节点 entity_id=id，
      仅名字的节点（受让人/发明人/LLM 实体等）entity_id=None，由 align 阶段补。
每条三元组：{head, head_type, relation, tail, tail_type, time, source}。
"""
import hashlib
import logging
from typing import Iterable

from techtrend.extraction.schema import DOC_ENTITY_TYPES

log = logging.getLogger(__name__)

RELATION_RULES = {
    "belongs_to": "concepts",
    "authored_by": "authorships[].author",
    "affiliated_with": "authorships[].institutions",
    "cites": "referenced_works",
}

_ENTITY_TYPES = {"Paper", "Concept", "Author", "Institution"}

# _NodeBuilder.add 的 entity_id 缺省哨兵：表示「锚定到 node_id」
_ANCHOR = object()


def short_id(openalex_id: str | None) -> str | None:
    """https://openalex.org/W... → W..."""
    if not openalex_id:
        return None
    return openalex_id.rstrip("/").rsplit("/", 1)[-1]


def normalize_name(name: str | None) -> str:
    """小写 / 去空白 / 去标点（对齐用）。"""
    import re

    if not name:
        return ""
    s = name.lower()
    s = re.sub(r"[\s_\-]+", " ", s)
    s = re.sub(r"[^\w ]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def deterministic_entity_id(source: str, type_: str, name: str) -> str:
    """确定性 entity_id（name-based 实体未命中时的兜底）。"""
    h = hashlib.sha1(f"{source}|{type_}|{normalize_name(name)}".encode("utf-8")).hexdigest()[:12]
    return f"{type_.lower()}:{h}"


def _triple(head, head_type, relation, tail, tail_type, time, source) -> dict:
    return {
        "head": head,
        "head_type": head_type,
        "relation": relation,
        "tail": tail,
        "tail_type": tail_type,
        "time": time,
        "source": source,
    }


class _NodeBuilder:
    """按 (type, id) 去重合并的节点注册表，产出 {id,type,entity_id,name,source,...}。

    约定：`entity_id` 缺省（_ANCHOR）→ 锚定到 node_id（有强 ID 的节点）；
    显式传 `entity_id=None` → 仅名字的实体，entity_id 留待 align 阶段补。
    """

    def __init__(self) -> None:
        self._nodes: dict[tuple[str, str], dict] = {}

    def add(
        self,
        node_id: str,
        ntype: str,
        name: str | None,
        entity_id: str | None = _ANCHOR,
        source: str | None = None,
        **extra,
    ) -> None:
        if not node_id or not ntype:
            return
        key = (ntype, node_id)
        existing = self._nodes.get(key)
        if existing is None:
            node = {
                "id": node_id,
                "type": ntype,
                "entity_id": node_id if entity_id is _ANCHOR else entity_id,
                "name": name,
                "source": source,
            }
            node.update(extra)
            self._nodes[key] = node
        else:
            if name and not existing.get("name"):
                existing["name"] = name
            if source and not existing.get("source"):
                existing["source"] = source
            for k, v in extra.items():
                if v is not None and existing.get(k) in (None, ""):
                    existing[k] = v

    def result(self) -> list[dict]:
        return list(self._nodes.values())


# ---------------------------------------------------------------------------
# OpenAlex（P1，复用 + entity_id/source/doi 补全）
# ---------------------------------------------------------------------------
def extract_triples(
    works: Iterable[dict], max_concepts: int = 5, max_refs: int = 10
) -> list[dict]:
    triples: list[dict] = []
    for w in works:
        head = short_id(w.get("id"))
        if not head:
            continue
        date = w.get("publication_date")

        concepts = sorted(
            (c for c in (w.get("concepts") or []) if c.get("id")),
            key=lambda c: c.get("score") or 0.0,
            reverse=True,
        )[:max_concepts]
        for c in concepts:
            cid = short_id(c.get("id"))
            if cid:
                triples.append(_triple(head, "Paper", "belongs_to", cid, "Concept", date, "openalex"))

        for a in w.get("authorships") or []:
            author = a.get("author") or {}
            aid = short_id(author.get("id"))
            if aid:
                triples.append(_triple(head, "Paper", "authored_by", aid, "Author", date, "openalex"))
            for inst in a.get("institutions") or []:
                iid = short_id(inst.get("id"))
                if iid:
                    triples.append(
                        _triple(head, "Paper", "affiliated_with", iid, "Institution", date, "openalex")
                    )

        for ref in (w.get("referenced_works") or [])[:max_refs]:
            rid = short_id(ref)
            if rid:
                triples.append(_triple(head, "Paper", "cites", rid, "Paper", date, "openalex"))

    return triples


def build_nodes(works: Iterable[dict], max_refs: int = 10) -> list[dict]:
    nb = _NodeBuilder()
    for w in works:
        nb.add(
            short_id(w.get("id")), "Paper", w.get("title"), source="openalex",
            pub_date=w.get("publication_date"), doi=w.get("doi"),
        )
        for c in w.get("concepts") or []:
            nb.add(short_id(c.get("id")), "Concept", c.get("name"), source="openalex")
        for a in w.get("authorships") or []:
            author = a.get("author") or {}
            nb.add(short_id(author.get("id")), "Author", author.get("name"), source="openalex")
            for inst in a.get("institutions") or []:
                nb.add(short_id(inst.get("id")), "Institution", inst.get("name"), source="openalex")
        for ref in (w.get("referenced_works") or [])[:max_refs]:
            nb.add(short_id(ref), "Paper", None, source="openalex")
    return nb.result()


# ---------------------------------------------------------------------------
# arXiv
# ---------------------------------------------------------------------------
def extract_arxiv(records: Iterable[dict]) -> tuple[list[dict], list[dict]]:
    """Paper→Concept（category）/ Paper→Author。"""
    triples: list[dict] = []
    nb = _NodeBuilder()
    for r in records:
        pid = r.get("id")
        if not pid:
            continue
        nb.add(pid, "Paper", r.get("title"), source="arxiv", pub_date=r.get("publication_date"), doi=r.get("doi"))
        for cat in r.get("categories") or []:
            cid = f"cat:{cat}"
            nb.add(cid, "Concept", cat, entity_id=cid, source="arxiv")
            triples.append(_triple(pid, "Paper", "belongs_to", cid, "Concept", r.get("publication_date"), "arxiv"))
        for a in r.get("authors") or []:
            name = a.get("name")
            if not name:
                continue
            aid = deterministic_entity_id("arxiv", "Author", name)
            nb.add(aid, "Author", name, entity_id=None, source="arxiv")
            triples.append(_triple(pid, "Paper", "authored_by", aid, "Author", r.get("publication_date"), "arxiv"))
    return triples, nb.result()


# ---------------------------------------------------------------------------
# USPTO
# ---------------------------------------------------------------------------
def extract_patents(records: Iterable[dict]) -> tuple[list[dict], list[dict]]:
    """Patent→Concept（CPC）/ Patent→Institution（受让人）/ Patent→Person（发明人）。"""
    triples: list[dict] = []
    nb = _NodeBuilder()
    for r in records:
        pid = r.get("id")
        if not pid:
            continue
        nb.add(pid, "Patent", r.get("title"), source="uspto", pub_date=r.get("publication_date"), kind=r.get("kind"))
        for cpc in r.get("cpc") or []:
            cid = f"cpc:{cpc}"
            nb.add(cid, "Concept", cpc, entity_id=cid, source="uspto")
            triples.append(_triple(pid, "Patent", "belongs_to", cid, "Concept", r.get("publication_date"), "uspto"))
        for name in r.get("assignees") or []:
            iid = deterministic_entity_id("uspto", "Institution", name)
            nb.add(iid, "Institution", name, entity_id=None, source="uspto")
            triples.append(_triple(pid, "Patent", "affiliated_with", iid, "Institution", r.get("publication_date"), "uspto"))
        for name in r.get("inventors") or []:
            pid2 = deterministic_entity_id("uspto", "Person", name)
            nb.add(pid2, "Person", name, entity_id=None, source="uspto")
            triples.append(_triple(pid, "Patent", "authored_by", pid2, "Person", r.get("publication_date"), "uspto"))
    return triples, nb.result()


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------
def extract_github(records: Iterable[dict]) -> tuple[list[dict], list[dict]]:
    """Repo→Concept（topic）。"""
    triples: list[dict] = []
    nb = _NodeBuilder()
    for r in records:
        rid = r.get("id")
        if not rid:
            continue
        nb.add(rid, "Repo", r.get("name"), source="github", url=r.get("url"), stars=r.get("stars"),
               pub_date=r.get("created_at"))
        for topic in r.get("topics") or []:
            cid = f"topic:{topic}"
            nb.add(cid, "Concept", topic, entity_id=cid, source="github")
            triples.append(_triple(rid, "Repo", "belongs_to", cid, "Concept", r.get("created_at"), "github"))
    return triples, nb.result()


# ---------------------------------------------------------------------------
# 新闻（GDELT + RSSHub）
# ---------------------------------------------------------------------------
def extract_news(records: Iterable[dict]) -> tuple[list[dict], list[dict]]:
    """News→Concept（GDELT theme）/ News→Person·Institution（mentions）。"""
    triples: list[dict] = []
    nb = _NodeBuilder()
    for r in records:
        nid = r.get("id")
        if not nid:
            continue
        name = r.get("title") or r.get("name")
        nb.add(nid, "News", name, source=r.get("source"), url=r.get("url"),
               pub_date=r.get("publication_date"), tone=r.get("tone"))
        date = r.get("publication_date")
        src = r.get("source") or "news"
        for theme in r.get("themes") or []:
            cid = f"theme:{theme}"
            nb.add(cid, "Concept", theme, entity_id=cid, source=src)
            triples.append(_triple(nid, "News", "belongs_to", cid, "Concept", date, src))
        for p in r.get("persons") or []:
            eid = deterministic_entity_id(src, "Person", p)
            nb.add(eid, "Person", p, entity_id=None, source=src)
            triples.append(_triple(nid, "News", "mentions", eid, "Person", date, src))
        for o in r.get("organizations") or []:
            eid = deterministic_entity_id(src, "Institution", o)
            nb.add(eid, "Institution", o, entity_id=None, source=src)
            triples.append(_triple(nid, "News", "mentions", eid, "Institution", date, src))
    return triples, nb.result()


# ---------------------------------------------------------------------------
# 通用
# ---------------------------------------------------------------------------
def dedupe_earliest(triples: list[dict]) -> list[dict]:
    """同 (head, relation, tail) 只保留最早 time（ISO 日期可直接按字符串比较）。"""
    best: dict[tuple, dict] = {}
    for t in triples:
        key = (t["head"], t["relation"], t["tail"])
        prev = best.get(key)
        if prev is None or (t.get("time") or "") < (prev.get("time") or ""):
            best[key] = t
    return list(best.values())
