"""Verify the dedicated local Neo4j with isolated synthetic evidence and cleanup."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from techtrend.config import get_settings
from techtrend.graph.neo4j_client import Neo4jClient


def main() -> None:
    settings = get_settings()
    client = Neo4jClient(settings.neo4j_uri, settings.neo4j_user,
                         settings.neo4j_password, database=settings.neo4j_database)
    ids = ["local_validation_01:paper", "local_validation_01:concept"]
    result = {"checked_at": datetime.now(timezone.utc).isoformat(),
              "database": settings.neo4j_database, "data_kind": "synthetic_validation"}
    try:
        client.verify_connectivity()
        client.create_schema()
        with client.driver.session(database=client.database) as session:
            assert session.run("MATCH (n) WHERE n.entity_id IN $ids RETURN count(n)",
                               ids=ids).single()[0] == 0, "Validation IDs already exist; refusing overwrite"
        facts = [{"head": ids[0], "tail": ids[1], "relation": "belongs_to",
                  "head_type": "Paper", "tail_type": "Concept", "time": time,
                  "source": "synthetic_validation", "dataset_version": "validation_01"}
                 for time in ("2022-01-01", "2023-01-01")]
        try:
            client.upsert_triples(facts)
            client.upsert_triples(facts)
            with client.driver.session(database=client.database) as session:
                row = session.run(
                    "MATCH (h {entity_id: $hid})-[r:BELONGS_TO]->(t {entity_id: $tid}) "
                    "RETURN count(r) AS edges, collect(r.time) AS times, "
                    "count(r.recorded_at) AS recorded, count(r[$available_key]) AS available",
                    available_key="available_at",
                    hid=ids[0], tid=ids[1]).single()
                assert row["edges"] == 2 and sorted(row["times"]) == ["2022-01-01", "2023-01-01"]
                assert row["recorded"] == 2 and row["available"] == 0
                result.update({"connectivity": "passed", "event_history": "passed",
                               "idempotence": "passed", "unverified_availability_not_invented": "passed"})
        finally:
            # Only the two IDs confirmed absent above and created by this check.
            with client.driver.session(database=client.database) as session:
                session.run("MATCH (n) WHERE n.entity_id IN $ids DETACH DELETE n", ids=ids).consume()
        with client.driver.session(database=client.database) as session:
            assert session.run("MATCH (n) WHERE n.entity_id IN $ids RETURN count(n)",
                               ids=ids).single()[0] == 0
            result["fixture_cleanup"] = "passed"
            result["research_node_count"] = session.run("MATCH (n) RETURN count(n)").single()[0]
            result["server_version"] = session.run("CALL dbms.components() YIELD versions RETURN versions[0]").single()[0]
    finally:
        client.close()
    output = ROOT / "output" / "validation_01"
    output.mkdir(parents=True, exist_ok=True)
    index = 1
    while True:
        try:
            with (output / f"database_check_{index:02d}.json").open("x", encoding="utf-8") as file:
                json.dump(result, file, ensure_ascii=False, indent=2)
            break
        except FileExistsError:
            index += 1
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
