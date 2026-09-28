"""抽取模块（P2：结构化 + LLM 抽取）。"""
from techtrend.extraction.structured import (
    RELATION_RULES,
    build_nodes,
    dedupe_earliest,
    deterministic_entity_id,
    extract_arxiv,
    extract_github,
    extract_news,
    extract_patents,
    extract_triples,
    normalize_name,
    short_id,
)
from techtrend.extraction.llm import LLMExtractor
from techtrend.extraction.schema import (
    ALL_ENTITY_TYPES,
    ALL_RELATIONS,
    DOC_ENTITY_TYPES,
    P1_ENTITY_TYPES,
    RELATION_MENTIONS,
    RELATION_RULES_LLM,
    TECH_ENTITY_TYPES,
)

__all__ = [
    "RELATION_RULES",
    "short_id",
    "normalize_name",
    "deterministic_entity_id",
    "extract_triples",
    "extract_arxiv",
    "extract_patents",
    "extract_github",
    "extract_news",
    "build_nodes",
    "dedupe_earliest",
    "LLMExtractor",
    "TECH_ENTITY_TYPES",
    "DOC_ENTITY_TYPES",
    "P1_ENTITY_TYPES",
    "ALL_ENTITY_TYPES",
    "ALL_RELATIONS",
    "RELATION_RULES_LLM",
    "RELATION_MENTIONS",
]
