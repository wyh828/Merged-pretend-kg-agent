import asyncio
from types import SimpleNamespace
from techtrend.signal.data_collectors.crossref import CrossrefCollector


def test_missing_count_becomes_failed_record_instead_of_zero():
    collector = CrossrefCollector()
    response = SimpleNamespace(payload={"message": {}}, fetched_at="2026-10-03T00:00:00Z", cache_hit=False)
    class Client:
        async def get_json(self, *args, **kwargs):
            return response
    topic = SimpleNamespace(topic_id="test", topic_label="Test")
    record = asyncio.run(collector._fetch_single(Client(), topic, "2016-01", "2016-01", {}, "test"))
    assert record["collection_status"] == "failed"
    assert record["activity_count"] is None


def test_optional_contact_is_not_fabricated(monkeypatch):
    monkeypatch.delenv("CROSSREF_MAILTO", raising=False)
    assert CrossrefCollector().resolve_contact({}) == ""
