"""抽取阶段（P2）：结构化（字段映射）+ LLM（技术实体/关系）合并。

- 输入：data/interim/{works,arxiv,patents,news,github}.jsonl。
- 输出：data/interim/triples.jsonl + nodes.jsonl（多 source 合并，供 align 阶段）。
- LLM 抽取：无 key 时整体跳过并 warning，只跑结构化（维持无 key 也能跑通）。
"""
import logging
from collections import Counter
from datetime import datetime

from techtrend.extraction.llm import LLMExtractor
from techtrend.extraction.structured import (
    build_nodes,
    dedupe_earliest,
    deterministic_entity_id,
    extract_arxiv,
    extract_github,
    extract_news,
    extract_patents,
    extract_triples,
    short_id,
)
from techtrend.io import read_jsonl, write_jsonl
from techtrend.stages.base import Stage

log = logging.getLogger(__name__)


class ExtractStage(Stage):
    name = "extract"

    def run(self) -> dict:
        s = self.settings
        try:
            interim_dir = s.data_dir / "interim"
            interim_dir.mkdir(parents=True, exist_ok=True)

            works = read_jsonl(interim_dir / "works.jsonl")
            arxiv = read_jsonl(interim_dir / "arxiv.jsonl")
            patents = read_jsonl(interim_dir / "patents.jsonl")
            github = read_jsonl(interim_dir / "github.jsonl")
            news = read_jsonl(interim_dir / "news.jsonl")

            triples: list[dict] = []
            nodes: dict[tuple[str, str], dict] = {}

            # ---- 1. 结构化抽取 ----
            triples.extend(
                extract_triples(works, max_concepts=s.extract_max_concepts, max_refs=s.extract_max_refs)
            )
            self._merge_nodes(nodes, build_nodes(works, max_refs=s.extract_max_refs))

            for extractor, records in (
                (extract_arxiv, arxiv),
                (extract_patents, patents),
                (extract_github, github),
                (extract_news, news),
            ):
                t, n = extractor(records)
                triples.extend(t)
                self._merge_nodes(nodes, n)

            # ---- 2. LLM 抽取（有 key 才跑）----
            llm_calls = 0
            if s.llm_api_key:
                extractor = LLMExtractor(
                    api_key=s.llm_api_key,
                    base_url=s.llm_base_url,
                    model=s.llm_model,
                    max_tokens=s.llm_max_tokens,
                    temperature=s.llm_temperature,
                )
                llm_calls, directed_pairs = self._run_llm(
                    extractor, arxiv, patents, github, news, triples, nodes
                )
                self._run_tone(extractor, news, nodes)
                # 定向 tech→tech 边的时间跨度来源：arXiv/USPTO 均为近期快照（单月），
                # 无时态分布；OpenAlex works（2023→2026）才有时态跨度，供 TKG 外推。
                llm_calls += self._run_openalex_tech_pairs(extractor, works, directed_pairs, nodes)
            else:
                log.warning("未配置 LLM_API_KEY，跳过 LLM 抽取（仅结构化抽取）")
                directed_pairs = []

            # ---- 3. 去重 + 补 created_at ----
            triples = dedupe_earliest(triples)
            # 定向 tech→tech 边在 dedupe 之后追加：跨文档重复是 min_support 计数，不能折叠。
            triples.extend(directed_pairs)
            now = datetime.now().isoformat(timespec="seconds")
            for t in triples:
                t["created_at"] = now

            write_jsonl(interim_dir / "triples.jsonl", triples)
            write_jsonl(interim_dir / "nodes.jsonl", list(nodes.values()))

            relations = dict(Counter(t["relation"] for t in triples))
            log.info(
                "extract 完成：triples=%d, relations=%s, llm_calls=%d",
                len(triples), relations, llm_calls,
            )
            return {
                "stage": self.name,
                "status": "ok",
                "triples": len(triples),
                "relations": relations,
                "llm_calls": llm_calls,
            }
        except Exception as exc:  # noqa: BLE001
            log.exception("extract 阶段失败")
            return {"stage": self.name, "status": "error", "error": str(exc)}

    @staticmethod
    def _merge_nodes(nodes: dict, new_nodes: list[dict]) -> None:
        for node in new_nodes:
            key = (node["type"], node["id"])
            existing = nodes.get(key)
            if existing is None:
                nodes[key] = node
            else:
                for k, v in node.items():
                    if v is not None and existing.get(k) in (None, ""):
                        existing[k] = v

    def _run_llm(self, extractor, arxiv, patents, github, news, triples, nodes) -> tuple[int, list[dict]]:
        """LLM 抽取 doc→tech（文档→技术实体/关系）。返回 (调用 doc 数, 定向对三元组)。

        本方法不再产定向 tech→tech 边（directed_pairs 恒为空）：arXiv/USPTO 均为近期单月
        快照（时间戳全落在同一月），其定向对无时态分布，注入 TKG 后会在最后一天形成
        ~49% 的事实尖峰，使 temporal_split_3way 退化为 train=全部 / val=test=0。
        定向边的时态跨度来源改为 OpenAlex works（2023→2026，见 _run_openalex_tech_pairs）；
        doc→tech 关系仍照常抽取，供静态 KG / 共现投影使用。
        """
        s = self.settings
        calls = 0
        budget = s.llm_max_docs_per_run
        directed_pairs: list[dict] = []
        groups = [
            (arxiv, "Paper", "publication_date"),
            (patents, "Patent", "publication_date"),
            (github, "Repo", "created_at"),
            ([r for r in news if r.get("source") == "rsshub"], "News", "publication_date"),
        ]
        for docs, doc_type, time_field in groups:
            for doc in docs:
                if calls >= budget:
                    log.warning("LLM 抽取达上限 %d 篇，停止", budget)
                    return calls, directed_pairs
                frags = extractor.extract(doc)
                for frag in frags:
                    tail = frag["tail"]
                    tail_type = frag["tail_type"]
                    tail_id = deterministic_entity_id(doc.get("source") or "llm", tail_type, tail)
                    self._merge_nodes(
                        nodes,
                        [{"id": tail_id, "type": tail_type, "entity_id": None, "name": tail,
                          "source": doc.get("source")}],
                    )
                    triples.append(
                        {
                            "head": doc.get("id"),
                            "head_type": doc_type,
                            "relation": frag["relation"],
                            "tail": tail_id,
                            "tail_type": tail_type,
                            "time": doc.get(time_field),
                            "source": doc.get("source"),
                        }
                    )
                calls += 1
        return calls, directed_pairs

    def _run_openalex_tech_pairs(self, extractor, works, directed_pairs, nodes) -> int:
        """对 OpenAlex works（有摘要 + 时态跨度）抽定向 tech→tech 边。

        已知技术实体 = work 的 concept 名（受控词表），head/tail 直接映射回 concept
        短 ID（= entity_id，build_nodes 已锚定，无需 align 折叠）。这是定向图的时态
        跨度来源：arXiv/USPTO 是近期单月快照，单独喂 TKG 会因单时间组而无法切分。
        """
        s = self.settings
        if not s.techpair_enable:
            return 0
        calls = 0
        budget = s.techpair_openalex_max_docs
        relations = {r.strip() for r in s.techpair_relations.split(",") if r.strip()}
        exclude = {c.strip() for c in s.openalex_concept_ids.split(",") if c.strip()}
        from datetime import date

        max_time = s.tkg_max_time or date.today().isoformat()
        for w in works:
            if calls >= budget:
                log.warning("OpenAlex 定向对抽取达上限 %d 篇，停止", budget)
                break
            if not (w.get("abstract") or "").strip():
                continue
            if (w.get("publication_date") or "") > max_time:
                continue  # 未来坏数据，TKG 也会被 max_time 过滤，直接跳过省 LLM 预算
            # 取 score 前 12 的非筛选概念（AI/CS 太泛，剔除），聚焦具体技术实体
            concepts = sorted(
                (c for c in (w.get("concepts") or []) if short_id(c.get("id")) not in exclude),
                key=lambda c: c.get("score") or 0.0,
                reverse=True,
            )[:12]
            name2cid: dict[str, str] = {}
            names: list[str] = []
            for c in concepts:
                cid = short_id(c.get("id"))
                name = (c.get("name") or "").strip()
                if cid and name and name not in name2cid:
                    name2cid[name] = cid
                    names.append(name)
            if not names:
                continue
            for pair in extractor.extract_tech_pairs(w, names, relations):
                h = name2cid.get(pair["head"])
                t = name2cid.get(pair["tail"])
                if not h or not t:
                    continue
                directed_pairs.append(
                    {
                        "head": h,
                        "head_type": "Concept",
                        "relation": pair["relation"],
                        "tail": t,
                        "tail_type": "Concept",
                        "time": w.get("publication_date"),
                        "source": "openalex",
                    }
                )
            calls += 1
        return calls

    @staticmethod
    def _run_tone(extractor, news, nodes) -> None:
        """为 RSSHub 中文新闻节点补 LLM tone（-1..1）。"""
        for r in news:
            if r.get("source") != "rsshub":
                continue
            text = (r.get("title") or "") + " " + (r.get("text") or "")
            if not text.strip():
                continue
            tone = extractor.extract_tone(text)
            if tone is None:
                continue
            key = ("News", r.get("id"))
            node = nodes.get(key)
            if node is not None:
                node["tone"] = tone
