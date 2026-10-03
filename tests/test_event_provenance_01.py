from techtrend.extraction.structured import dedupe_events
from techtrend.graph.neo4j_client import Neo4jClient
from techtrend.io import read_jsonl
from techtrend.prediction.temporal import project_t2t
from techtrend.stages.collect import _append_dedup


def test_same_pair_has_distinct_dated_document_evidence():
    base = {"head": "a", "relation": "uses", "tail": "b", "source": "test", "time": "2020-01-01"}
    facts = [dict(base, evidence_id="doc1"), dict(base, evidence_id="doc2"), dict(base, time="2021-01-01")]
    assert len(dedupe_events(facts + facts)) == 3
    assert len({Neo4jClient._event_id(t) for t in facts}) == 3


def test_document_revision_cannot_create_backdated_cooccurrence():
    rows = [{"head": "doc", "head_type": "Paper", "tail": "old", "tail_type": "Concept", "time": "2020-01-01"},
            {"head": "doc", "head_type": "Paper", "tail": "future", "tail_type": "Concept", "time": "2030-01-01"}]
    assert project_t2t(rows, min_cooccur=1, max_entities=0) == []


def test_stored_documents_record_observation_time_and_version(tmp_path):
    path = tmp_path / "dataset_01" / "interim" / "works.jsonl"
    assert _append_dedup(path, [{"id": "a", "publication_date": "1990-01-01"}]) == 1
    assert _append_dedup(path, [{"id": "a"}]) == 0
    row = read_jsonl(path)[0]
    assert row["dataset_version"] == "dataset_01" and row["collected_at"].endswith("+00:00")
    assert "available_at" not in row
