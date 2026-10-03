"""图谱构建阶段：triples + nodes → Neo4j。"""
import logging

from techtrend.graph.loader import load_triples
from techtrend.graph.neo4j_client import Neo4jClient
from techtrend.io import read_jsonl
from techtrend.stages.base import Stage

log = logging.getLogger(__name__)


class BuildGraphStage(Stage):
    name = "build_graph"

    def run(self) -> dict:
        s = self.settings
        try:
            interim_dir = s.data_dir / "interim"
            triples = read_jsonl(interim_dir / "triples.jsonl")
            nodes = read_jsonl(interim_dir / "nodes.jsonl")
            if not triples:
                log.warning("triples.jsonl 为空，请先运行 --stage extract")
                return {"stage": self.name, "status": "ok", "nodes": 0, "edges": 0}

            client = Neo4jClient(s.neo4j_uri, s.neo4j_user, s.neo4j_password, database=s.neo4j_database)
            try:
                client.verify_connectivity()
                result = load_triples(client, triples, nodes)
            finally:
                client.close()

            log.info("build_graph 完成：nodes=%d, edges=%d", result["nodes"], result["edges"])
            return {"stage": self.name, "status": "ok", **result}
        except Exception as exc:  # noqa: BLE001
            log.exception("build_graph 阶段失败")
            return {"stage": self.name, "status": "error", "error": str(exc)}
