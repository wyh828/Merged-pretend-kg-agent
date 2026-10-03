from types import SimpleNamespace
from techtrend.graph.neo4j_client import Neo4jClient


def test_database_import_uses_bounded_batches_and_preserves_event_fields():
    writes = []
    class Result:
        def consume(self):
            return None
        def single(self):
            return [52]
    class Session:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute_write(self, fn): return fn(self)
        def run(self, query, **params):
            if "rows" in params:
                writes.append((query, params["rows"]))
            return Result()
    client = Neo4jClient.__new__(Neo4jClient)
    client.database = "neo4j"
    client.batch_size = 20
    client.driver = SimpleNamespace(session=lambda **_: Session())
    nodes = [{"type": "Paper", "entity_id": f"W{i}", "name": "test"} for i in range(52)]
    event = {"head": "W0", "head_type": "Paper", "tail": "T1", "tail_type": "Concept",
             "relation": "belongs_to", "time": "2016-01-01", "source": "openalex",
             "dataset_version": "test_02", "collected_at": "2026-10-03", "available_at": None}
    client.upsert_triples([event], nodes)
    assert [len(rows) for _, rows in writes] == [20, 20, 12, 1]
    row = writes[-1][1][0]
    assert row["event_id"] == client._event_id(event)
    assert row["time"] == "2016-01-01" and row["available_at"] is None
    assert "UNWIND $rows AS row" in writes[-1][0]
