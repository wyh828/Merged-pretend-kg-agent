from techtrend.graph.neo4j_client import Neo4jClient


def test_graph_event_identity_preserves_dates_sources_and_dataset_versions():
    event = dict(head="a", relation="uses", tail="b", time="2020-01", source="source", dataset_version="dataset_01")
    first = Neo4jClient._event_id(event)
    assert Neo4jClient._event_id(dict(event)) == first
    for field, value in [("time", "2020-02"), ("source", "other"), ("dataset_version", "dataset_02")]:
        assert Neo4jClient._event_id({**event, field: value}) != first
