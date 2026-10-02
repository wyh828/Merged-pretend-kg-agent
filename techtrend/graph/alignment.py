"""跨源实体对齐：强 ID 锚点 → string 匹配 →（可选）LLM 消歧。

三级流水线（先到先得，后级只处理未对齐的）：
1. 强 ID 锚点：带源 ID 的节点（openalex 短 ID / arxiv: / uspto: / github: / gdelt: / rsshub: / cat: / cpc: / topic: / theme:）
   天然唯一，entity_id 已设；arXiv 论文若带 DOI，与 OpenAlex 论文（同 DOI）合并。
2. String 匹配：name-based 实体（LLM 技术实体 / USPTO 受让人·发明人 / GDELT 人·机构 / arXiv 作者）
   按 normalize_name + rapidfuzz.ratio ≥ threshold 映射到 OpenAlex 的 Concept / Institution / Author。
3. LLM 消歧（可选，align_enable_llm）：默认关，此处留空实现。

输出：
- nodes：每行补 entity_id（type 可能被折叠到 Concept/Institution/Author）。
- triples：补 head_id/tail_id（= 端点 entity_id），head_type/tail_type 同步为折叠后类型。
- audit：每行 {entity_id, type, name, source, anchor_id} 供「五源对齐」验收。
"""
import logging
import re
from typing import Iterable

from techtrend.extraction.structured import deterministic_entity_id, normalize_name

log = logging.getLogger(__name__)

# name-based 实体类型 → 对齐目标类型（OpenAlex 锚点）
_MATCH_TARGET = {
    "Technology": "Concept",
    "Method": "Concept",
    "Model": "Concept",
    "Framework": "Concept",
    "Dataset": "Concept",
    "Institution": "Institution",
    "Person": "Author",
    "Author": "Author",
}


def _norm_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    value = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/", "doi:"):
        if value.startswith(prefix):
            value = value[len(prefix):]
            break
    return value


def _fuzzy_match(name: str, candidates: dict[str, dict], threshold: float) -> dict | None:
    """在 candidates（normalized_name → node）中找 ≥ threshold 的最近名，无则 None。"""
    if not candidates:
        return None
    try:
        from rapidfuzz import fuzz, process

        best = process.extractOne(name, list(candidates.keys()), scorer=fuzz.ratio)
        if best and best[1] >= threshold * 100:
            return candidates[best[0]]
    except ImportError:
        import difflib

        best_key = max(candidates, key=lambda k: difflib.SequenceMatcher(None, name, k).ratio())
        if difflib.SequenceMatcher(None, name, best_key).ratio() >= threshold:
            return candidates[best_key]
    return None


def align_entities(
    nodes: Iterable[dict],
    triples: Iterable[dict],
    threshold: float = 0.90,
    use_llm: bool = False,
) -> tuple[list[dict], list[dict], list[dict]]:
    """对齐 nodes/triples → (对齐后 nodes, 对齐后 triples, audit 行)。"""
    nodes = [dict(n) for n in nodes]
    triples = [dict(t) for t in triples]

    # 1. 强 ID 锚点：DOI 跨源合并（arXiv 论文 → OpenAlex 论文）
    doi_index: dict[str, str] = {}
    for n in nodes:
        if n.get("type") == "Paper" and n.get("source") == "openalex" and n.get("doi"):
            key = _norm_doi(n["doi"])
            if key and n.get("entity_id"):
                doi_index.setdefault(key, n["entity_id"])
    merged_by_doi = 0
    for n in nodes:
        if n.get("type") == "Paper" and n.get("source") in ("arxiv", "crossref") and n.get("doi"):
            key = _norm_doi(n["doi"])
            if key in doi_index and n.get("entity_id") != doi_index[key]:
                n["entity_id"] = doi_index[key]
                merged_by_doi += 1

    # 2. String 匹配：构建 OpenAlex 锚点索引（normalized_name → node）
    anchored_index: dict[str, dict[str, dict]] = {"Concept": {}, "Institution": {}, "Author": {}}
    for n in nodes:
        if n.get("entity_id") and n.get("type") in anchored_index and n.get("name"):
            anchored_index[n["type"]].setdefault(normalize_name(n["name"]), n)

    audit: list[dict] = []
    aligned_by_string = 0
    for n in nodes:
        if n.get("entity_id"):
            continue
        target_type = _MATCH_TARGET.get(n.get("type"))
        name = n.get("name") or n.get("title") or ""
        matched = None
        if target_type and name:
            norm = normalize_name(name)
            # 精确命中优先
            exact = anchored_index[target_type].get(norm)
            if exact is not None:
                matched = exact
            else:
                matched = _fuzzy_match(norm, anchored_index[target_type], threshold)
        if matched is not None:
            n["entity_id"] = matched["entity_id"]
            n["type"] = target_type  # 折叠到锚点类型
            aligned_by_string += 1
            audit.append(
                {
                    "entity_id": n["entity_id"],
                    "type": n["type"],
                    "name": name,
                    "source": n.get("source"),
                    "anchor_id": matched["id"],
                }
            )
        else:
            n["entity_id"] = deterministic_entity_id(
                n.get("source") or "unknown", n["type"], name
            )
            audit.append(
                {
                    "entity_id": n["entity_id"],
                    "type": n["type"],
                    "name": name,
                    "source": n.get("source"),
                    "anchor_id": None,
                }
            )

    # 3. 重写 triples
    node_by_id = {n["id"]: n for n in nodes}
    out_triples: list[dict] = []
    for t in triples:
        hn = node_by_id.get(t["head"])
        tn = node_by_id.get(t["tail"])
        if hn is None or tn is None:
            continue  # 端点无节点（理论上不应发生），丢弃
        nt = dict(t)
        nt["head_id"] = hn["entity_id"]
        nt["tail_id"] = tn["entity_id"]
        nt["head_type"] = hn["type"]
        nt["tail_type"] = tn["type"]
        out_triples.append(nt)

    log.info(
        "对齐完成：entities=%d, doi_merged=%d, string_aligned=%d",
        len(nodes), merged_by_doi, aligned_by_string,
    )
    return nodes, out_triples, audit
