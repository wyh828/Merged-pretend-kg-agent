"""实体/关系类型常量（P2：技术实体 + 7 关系 + mentions 兜底）。"""

# LLM 抽取的技术实体类型（对齐后映射到 Concept/Institution/Author 或确定性 ID）
TECH_ENTITY_TYPES = (
    "Technology",
    "Method",
    "Model",
    "Framework",
    "Dataset",
    "Institution",
    "Person",
)

# 源文档节点类型
DOC_ENTITY_TYPES = ("Paper", "Patent", "Repo", "News")

# P1 已固化类型（结构化抽取产出）
P1_ENTITY_TYPES = ("Concept", "Author")

# 全部节点类型（Neo4j 标签白名单）
ALL_ENTITY_TYPES = DOC_ENTITY_TYPES + P1_ENTITY_TYPES + TECH_ENTITY_TYPES

# LLM 抽取的 7 关系 → 中文语义
RELATION_RULES_LLM = {
    "uses": "使用",
    "improves": "改进",
    "compares": "对比",
    "belongs_to": "属于",
    "targets": "针对",
    "competes": "竞品",
    "causes": "因果",
}

# 定向 tech→tech 关系白名单（exclude belongs_to：属层级 doc→tech；causes 罕见可留）
# 用于 LLM 二次 pass 抽「技术间定向关系」，与 doc→tech 的 RELATION_RULES_LLM 区分：
# 两端都是技术实体，不包含 belongs_to 这种层级关系。
TECH_PAIR_RELATIONS = ("uses", "improves", "compares", "targets", "competes", "causes")

# 新闻类兜底：News → 实体（仅被提及）
RELATION_MENTIONS = "mentions"

# P1 结构化关系
P1_RELATIONS = ("belongs_to", "authored_by", "affiliated_with", "cites")

# 全部关系（供图谱写边类型白名单）
ALL_RELATIONS = (
    P1_RELATIONS
    + tuple(RELATION_RULES_LLM.keys())
    + (RELATION_MENTIONS,)
)
