from techtrend.extraction.llm import LLMExtractor, _parse_json


def test_non_object_llm_json_is_rejected():
    assert _parse_json('[1, 2]') is None
    assert _parse_json('```json\n{"triples": []}\n```') == {"triples": []}


def test_malformed_triples_do_not_crash_or_hide_valid_items():
    valid = {"relation": "uses", "tail": "Python", "tail_type": "Technology"}
    assert LLMExtractor._validate([None, "bad", {"tail": 2}, valid, valid]) == [valid]
    assert LLMExtractor._validate({"invalid": "container"}) == []


def test_malformed_pairs_are_rejected_without_network():
    extractor = object.__new__(LLMExtractor)
    extractor._chat = lambda *_: '{"pairs": [{"head": 2, "relation": "uses", "tail": "B"}]}'
    assert extractor.extract_tech_pairs({}, ["A", "B"]) == []
