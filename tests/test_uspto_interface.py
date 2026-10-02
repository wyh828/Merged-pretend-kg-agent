import asyncio
from types import SimpleNamespace

import pytest
from techtrend.signal.data_collectors import uspto


@pytest.mark.parametrize("mode", ["odp", "patentsearch"])
def test_uspto_uses_supported_http_header_argument(monkeypatch, tmp_path, mode):
    seen = []
    class Client:
        def __init__(self, *_): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def get_json(self, url, params, *, cache_key, extra_headers):
            seen.append(extra_headers)
            return SimpleNamespace(payload={"queryStatus": {"totalResults": 7}}, fetched_at="test", cache_hit=False)
        async def post_json(self, url, body, *, cache_key, extra_headers):
            seen.append(extra_headers)
            return SimpleNamespace(payload={"total_patent_count": 7}, fetched_at="test", cache_hit=False)
    monkeypatch.setattr(uspto, "PoliteApiClient", Client)
    monkeypatch.setenv("USPTO_API_KEY", "test-only")
    topic = SimpleNamespace(topic_id="test", topic_label="test", openalex_query="test")
    cfg = SimpleNamespace(start_date="2024-01", end_date="2024-02", topics=[topic], raw_api_path=tmp_path)
    records = asyncio.run(uspto.UsptoCollector().collect(cfg, {}, {"api_mode": mode}))
    assert len(records) == 1
    assert records[0]["collection_status"] == "ok"
    assert records[0]["activity_count"] == 7
    assert seen[0]["X-API-KEY"] == "test-only"
