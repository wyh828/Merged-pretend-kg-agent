from techtrend.extraction.structured import build_nodes, extract_triples, short_id
from techtrend.graph.alignment import align_entities
from techtrend.sources.crossref import CrossrefClient


def test_doi_registrants_with_same_suffix_remain_distinct():
    assert short_id("doi:10.1000/shared") != short_id("doi:10.2000/shared")
    assert short_id("10.1000/shared") == "doi:10.1000/shared"
    assert short_id("https://openalex.org/W123") == "W123"


def test_crossref_provenance_and_doi_alignment():
    record = CrossrefClient.normalize({"DOI": "10.1000/shared", "subject": ["AI"], "reference": [{"DOI": "10.2000/shared"}]})
    triples = extract_triples([record])
    nodes = build_nodes([record])
    assert all(n["source"] == "crossref" for n in nodes)
    assert all(t["source"] == "crossref" for t in triples)
    assert {t["tail"] for t in triples} == {"crossref:AI", "doi:10.2000/shared"}
    nodes += [{"id": "W123", "entity_id": "W123", "type": "Paper", "source": "openalex", "doi": "https://doi.org/10.1000/shared"}]
    aligned, aligned_triples, _ = align_entities(nodes, triples)
    crossref = next(n for n in aligned if n["id"] == "doi:10.1000/shared")
    assert crossref["entity_id"] == "W123"
    assert all(t["head_id"] == "W123" for t in aligned_triples)
