"""triples → Neo4j 装载。"""
import logging
from typing import Iterable

from techtrend.graph.neo4j_client import Neo4jClient

log = logging.getLogger(__name__)


def load_triples(
    client: Neo4jClient, triples: Iterable[dict], nodes: Iterable[dict] | None = None
) -> dict:
    """建 schema 后批量 upsert，返回 {"nodes": N, "edges": M}。"""
    client.create_schema()
    n, m = client.upsert_triples(triples, nodes)
    return {"nodes": n, "edges": m}
