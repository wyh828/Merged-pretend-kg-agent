from techtrend.prediction.citations import build_patent_citation_monthly


def test_filtered_empty_citations_do_not_crash():
    assert build_patent_citation_monthly([{"head": "a", "time": "2024-01-01"}], min_citations=2).empty


def test_cumulative_citations_follow_calendar_order_across_patents():
    facts = [{"head": "a", "time": "2024-03-01"}, {"head": "b", "time": "2024-01-01"}, {"head": "b", "time": "2024-02-01"}]
    df = build_patent_citation_monthly(facts, min_citations=1)
    assert list(df.columns) == ["2024-01", "2024-02", "2024-03"]
    assert list(df.loc["a"]) == [0, 0, 1]
    assert list(df.loc["b"]) == [1, 2, 2]
