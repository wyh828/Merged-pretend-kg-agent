"""Neo4j 驱动封装：连接 / 约束 / 幂等 MERGE 批量 upsert（P2 schema 泛化）。

- 唯一约束改在 `entity_id`（每 label 一条）；`openalex_id` 等降为来源溯源属性。
- 节点 label 取节点 `type`，边 label 由 triples 的 `head_type`/`tail_type` 决定，
  关系类型由 `_RELATION_TYPES` 白名单映射（均为静态白名单，安全拼进 Cypher）。
- 日常建库只增加约束；旧库迁移须单独审查，不能自动删除旧约束。
"""
import logging
import hashlib
import json
from collections import defaultdict
from typing import Any, Iterable

from neo4j import GraphDatabase

from techtrend.extraction.schema import ALL_ENTITY_TYPES

log = logging.getLogger(__name__)

_NODE_LABELS = tuple(ALL_ENTITY_TYPES)

# 关系名 → Neo4j 关系类型（静态白名单）
_RELATION_TYPES: dict[str, str] = {
    "belongs_to": "BELONGS_TO",
    "authored_by": "AUTHORED_BY",
    "affiliated_with": "AFFILIATED_WITH",
    "cites": "CITES",
    "uses": "USES",
    "improves": "IMPROVES",
    "compares": "COMPARES",
    "targets": "TARGETS",
    "competes": "COMPETES",
    "causes": "CAUSES",
    "mentions": "MENTIONS",
}
_EDGE_TYPES = tuple(_RELATION_TYPES.values())

_DOC_LABELS = {"Paper", "Patent", "Repo", "News"}


class Neo4jClient:
    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j", batch_size: int = 500) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.database = database
        self.batch_size = batch_size

    def verify_connectivity(self) -> None:
        self.driver.verify_connectivity()

    def create_schema(self) -> None:
        """增加 entity_id 唯一约束和索引，不删除或迁移已有数据。"""
        with self.driver.session(database=self.database) as session:
            for label in _NODE_LABELS:
                session.run(
                    f"CREATE CONSTRAINT {label.lower()}_entity_id IF NOT EXISTS "
                    f"FOR (x:{label}) REQUIRE x.entity_id IS UNIQUE"
                )
            session.run("CREATE INDEX concept_name IF NOT EXISTS FOR (c:Concept) ON (c.name)")
        log.info("Neo4j schema（entity_id 唯一约束 + 索引）已就绪")

    @staticmethod
    def _node_props(n: dict) -> dict[str, Any] | None:
        """节点属性按类型分支写入；返回 None 表示该节点标签非法，跳过。"""
        label = n.get("type")
        if label not in _NODE_LABELS:
            return None
        name = n.get("name") or n.get("title")
        props: dict[str, Any] = {"entity_id": n.get("entity_id"), "source": n.get("source")}
        if label in ("Paper", "Patent"):
            props["title"] = name
            if n.get("pub_date"):
                props["pub_date"] = n["pub_date"]
        elif label == "Repo":
            props["name"] = name
            if n.get("url"):
                props["url"] = n["url"]
            props["stars"] = n.get("stars") or 0
        elif label == "News":
            props["name"] = name
            if n.get("url"):
                props["url"] = n["url"]
            if n.get("tone") is not None:
                props["tone"] = n["tone"]
        else:
            props["name"] = name
        # 其余溯源属性（doi/kind 等）有则保留
        for k in ("doi", "kind"):
            if n.get(k):
                props[k] = n[k]
        return props

    def upsert_triples(
        self, triples: Iterable[dict], nodes: Iterable[dict] | None = None
    ) -> tuple[int, int]:
        """MERGE 批量 upsert → 返回图中（节点数, 边数）总数。"""
        triples = list(triples)
        nodes = list(nodes or [])

        node_groups, edge_groups = defaultdict(list), defaultdict(list)
        for n in nodes:
            props = self._node_props(n)
            if props is not None and n.get("entity_id"):
                node_groups[n["type"]].append({"eid": n["entity_id"], "props": props})
        for t in triples:
            rel = _RELATION_TYPES.get(t.get("relation"))
            hlabel, tlabel = t.get("head_type"), t.get("tail_type")
            hid, tid = t.get("head_id") or t.get("head"), t.get("tail_id") or t.get("tail")
            if not rel or hlabel not in _NODE_LABELS or tlabel not in _NODE_LABELS or not hid or not tid:
                continue
            edge_groups[hlabel, rel, tlabel].append({"hid": hid, "tid": tid, "event_id": self._event_id(t),
                **{k: t.get(k) for k in ("time", "source", "dataset_version", "available_at", "evidence_id", "collected_at")}})

        with self.driver.session(database=self.database) as session:
            # A failed chunk leaves earlier chunks committed. Replaying is
            # idempotent by node/event IDs and never removes prior evidence.
            for label, rows in node_groups.items():
                query = f"UNWIND $rows AS row MERGE (x:{label} {{entity_id: row.eid}}) SET x += row.props"
                self._write_batches(session, query, rows)
            for (hlabel, rel, tlabel), rows in edge_groups.items():
                query = ("UNWIND $rows AS row "
                         f"MERGE (h:{hlabel} {{entity_id: row.hid}}) "
                         f"MERGE (t:{tlabel} {{entity_id: row.tid}}) "
                         f"MERGE (h)-[r:{rel} {{event_id: row.event_id}}]->(t) "
                         "ON CREATE SET r.recorded_at = datetime() "
                         "SET r.time = row.time, r.source = row.source, r.dataset_version = row.dataset_version "
                         "SET r.evidence_id = row.evidence_id, r.collected_at = row.collected_at "
                         "SET r.available_at = coalesce(r.available_at, row.available_at)")
                self._write_batches(session, query, rows)
            node_count = session.run(
                f"MATCH (n) WHERE {' OR '.join('n:' + l for l in _NODE_LABELS)} "
                "RETURN count(n)"
            ).single()[0]
            edge_count = session.run(
                "MATCH ()-[r]->() WHERE type(r) IN $types RETURN count(r)",
                types=list(_EDGE_TYPES),
            ).single()[0]
        log.info("Neo4j upsert 完成：nodes=%d, edges=%d", node_count, edge_count)
        return int(node_count), int(edge_count)

    def _write_batches(self, session, query: str, rows: list[dict]) -> None:
        """Consume each bounded transaction before advancing; errors propagate."""
        for start in range(0, len(rows), self.batch_size):
            batch = rows[start:start + self.batch_size]
            session.execute_write(lambda tx: tx.run(query, rows=batch).consume())

    @staticmethod
    def _event_id(triple: dict) -> str:
        """Keep distinct dated/source/versioned evidence, idempotent across reruns."""
        values = [triple.get("head_id") or triple.get("head"), triple.get("relation"),
                  triple.get("tail_id") or triple.get("tail"), triple.get("time"),
                  triple.get("source"), triple.get("dataset_version"), triple.get("evidence_id")]
        return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode("utf-8")).hexdigest()

    def close(self) -> None:
        self.driver.close()
