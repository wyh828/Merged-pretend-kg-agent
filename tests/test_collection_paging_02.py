import httpx
import pytest

from techtrend.sources.openalex import OpenAlexClient
from techtrend.sources.crossref import CrossrefClient


@pytest.mark.parametrize("client_class,collection_key", [(OpenAlexClient, "results"), (CrossrefClient, "items")])
def test_capped_batch_requests_only_remaining_and_retains_cursor(client_class, collection_key, monkeypatch):
    client = client_class(per_page=2)
    requests = []
    def get_page(params):
        requests.append(dict(params))
        size = params.get("per_page", params.get("rows"))
        offset = 0 if params["cursor"] == "*" else 2
        rows = [{"id": str(i)} for i in range(offset, offset + size)]
        if collection_key == "results":
            return {"results": rows, "meta": {"count": 9, "next_cursor": f"next-{offset}"}}
        return {"message": {"items": rows, "total-results": 9, "next-cursor": f"next-{offset}"}}
    monkeypatch.setattr(client, "_get_page", get_page)
    try:
        batch = client.fetch_batch("2016-01-01", None, 3, until_date="2016-12-31")
        assert len(batch.records) == 3
        assert not batch.complete and batch.next_cursor == "next-2"
        assert [p.get("per_page", p.get("rows")) for p in requests] == [2, 1]
        assert requests[0]["cursor"] == "*"
        assert "2016-12-31" in requests[0]["filter"]
        assert requests[0]["sort"] in {"publication_date:asc", "published"}
    finally:
        client.close()


@pytest.mark.parametrize("client_class", [OpenAlexClient, CrossrefClient])
def test_bad_success_payload_cannot_be_claimed_empty_complete(client_class, monkeypatch):
    with client_class() as client:
        monkeypatch.setattr(client, "_get_page", lambda _: {"error": "schema changed"})
        with pytest.raises(ValueError):
            client.fetch_batch("2016-01-01", None, 2)


def test_openalex_modern_topics_preserve_existing_concept_contract():
    with OpenAlexClient(per_page=200) as client:
        assert client.per_page == 100
        record = client.normalize({"id": "W1", "topics": [{"id": "https://openalex.org/T1", "display_name": "Energy", "score": 0.9}]})
    assert record["source"] == "openalex"
    assert record["concepts"][0]["id"] == "https://openalex.org/T1"
    assert record["classification_scheme"] == "openalex_topics"


def test_crossref_registration_date_is_not_a_publication_date():
    record = CrossrefClient.normalize({"DOI": "10.1/x", "created": {"date-parts": [[2025, 1, 1]]}})
    assert record["publication_date"] is None
