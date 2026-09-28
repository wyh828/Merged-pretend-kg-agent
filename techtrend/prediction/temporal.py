"""TKG 数据准备：把 doc→Concept 事实流投影到持久实体 Concept×Concept 共现边。

P3 的时序外推要求「实体跨时间重复出现」。P2 图谱以 Paper/Patent/Repo/News 为头、
Concept 为尾，头是一次性实体（只在自身发表时间出现），直接喂 TKG 会因「test 头实体
无历史」退化。故投影到 Concept×Concept：

- 输入 triples 中 head_type ∈ DOC_ENTITY_TYPES 且 tail_type == Concept 的行，按 head
  （文档）分组，同一文档内出现的 Concept 两两成无向边 relates_to，time = 文档 time。
- 计数后仅保留共现次数 ≥ min_cooccur 的边（降噪、控规模）；按度截断至 max_entities
  后只保留端点都在内的边。
- 输出事实流 (head, relates_to, tail, time)，端点均为持久 entity_id（Concept）。

诚实声明：relates_to 是「同文档共现」的关联代理，不是经 LLM 验证的定向关系。

P4 起 cooccur 投影（project_t2t）为正式 TKG 边源：walk-forward + 同时态同协议下 CyGNet
于共现图反超 RotatE（0.9459 vs 0.4487），而定向图（0.1621 vs 0.2390）与专利引用图
（时态 DAG + 单事件边，P2-1 证伪）均不能证明 copy 优势。故专利引用图已从 TKG 边源移除，
仅保留 load_directed_edges 作消融对照。
"""
import logging
from collections import Counter, defaultdict
from itertools import combinations
from typing import Iterable

from techtrend.extraction.schema import DOC_ENTITY_TYPES, TECH_PAIR_RELATIONS

log = logging.getLogger(__name__)

# 对齐后技术实体折叠为 Concept；可扩展 ("Concept", "Institution")
PERSISTENT_TYPES = ("Concept",)

# 定向 tech→tech 边的端点类型：对齐后已折叠的 Concept + 未折叠的 LLM 技术实体类型。
# （对齐的 string 匹配命中 OpenAlex Concept 才折叠为 Concept；未命中的技术实体保持
# Technology/Method/Model/Framework/Dataset 原类型，仍是「可跨时间追踪的持久技术实体」。）
DIRECTED_TECH_TYPES = ("Concept", "Technology", "Method", "Model", "Framework", "Dataset")


def project_t2t(
    triples: Iterable[dict],
    relation: str = "relates_to",
    min_cooccur: int = 2,
    max_entities: int = 5000,
    doc_types: Iterable[str] | None = None,
    max_time: str | None = None,
) -> list[dict]:
    """doc→Concept 三元组 → Concept×Concept 共现事实流。

    返回 [{"head": entity_id, "relation": relation, "tail": entity_id, "time": iso}]。
    每个「同文档共现」事件产出一条无向边（两端各一条方向事实，保证 copy 机制对每个
    实体都有 (s, relates_to) 历史），仅保留共现次数 ≥ min_cooccur 的边。

    - doc_types：参与投影的文档类型（默认全部 DOC_ENTITY_TYPES）。GDELT News 是单日
      快照 + 事件主题（非技术实体），默认排除，见 config.tkg_doc_types。
    - max_time：丢弃 time > max_time 的坏数据（如 OpenAlex 未来日期）；None = 不过滤。
    """
    doc_types = set(doc_types) if doc_types else set(DOC_ENTITY_TYPES)

    # 1. 按文档分组，收集每个文档内的持久 Concept 集合 + 时间
    doc_concepts: dict[str, dict] = defaultdict(lambda: {"concepts": set(), "time": None})
    for t in triples:
        if t.get("head_type") not in doc_types:
            continue
        if t.get("tail_type") not in PERSISTENT_TYPES:
            continue
        time = t.get("time") or ""
        if max_time is not None and time > max_time:
            continue
        tail_id = t.get("tail_id") or t.get("tail")
        if not tail_id:
            continue
        head_id = t.get("head_id") or t.get("head")
        d = doc_concepts[head_id]
        d["concepts"].add(tail_id)
        if not d["time"]:
            d["time"] = time

    # 2. 无向共现边计数（canonical 排序，避免 (a,b)/(b,a) 重复计数）
    pair_count: Counter = Counter()
    for d in doc_concepts.values():
        cs = sorted(d["concepts"])
        for a, b in combinations(cs, 2):
            pair_count[(a, b)] += 1

    # 3. 仅保留共现次数 ≥ min_cooccur 的边
    kept_pairs = {p for p, c in pair_count.items() if c >= min_cooccur}
    if not kept_pairs:
        log.warning("project_t2t：无满足 min_cooccur=%d 的共现边", min_cooccur)
        return []

    # 4. 按度截断至 max_entities（保留度数最高的实体，端点均需在保留集内）
    degree: Counter = Counter()
    for a, b in kept_pairs:
        degree[a] += 1
        degree[b] += 1
    kept_entities: set[str] = set()
    if len(degree) <= max_entities:
        kept_entities = set(degree)
    else:
        top = sorted(degree.items(), key=lambda kv: (-kv[1], kv[0]))[:max_entities]
        kept_entities = {e for e, _ in top}
        kept_pairs = {
            (a, b) for a, b in kept_pairs if a in kept_entities and b in kept_entities
        }

    # 5. 重新投影：对每个文档内仍被保留的共现边，产出一条时间戳事实（双向）
    facts: list[dict] = []
    for d in doc_concepts.values():
        time = d["time"]
        if not time:
            continue
        concepts = sorted(c for c in d["concepts"] if c in kept_entities)
        for a, b in combinations(concepts, 2):
            if (a, b) not in kept_pairs:
                continue
            facts.append({"head": a, "relation": relation, "tail": b, "time": time})
            facts.append({"head": b, "relation": relation, "tail": a, "time": time})

    log.info(
        "project_t2t：%d 条共现边（≥%d）→ %d 条事实流，实体 %d",
        len(kept_pairs), min_cooccur, len(facts), len(kept_entities),
    )
    return facts


def load_directed_edges(
    triples: Iterable[dict],
    relations: Iterable[str] | None = None,
    min_support: int = 2,
    max_time: str | None = None,
) -> list[dict]:
    """从 triples.jsonl 过滤定向 tech→tech 事实流（P3.5 优化边源）。

    保留 head/tail 均为技术实体（DIRECTED_TECH_TYPES）且 relation∈relations 的行
    （对齐后端点可能折叠为 Concept，也可能保持 Technology/… 原类型，两者都算）。
    按 (head, relation, tail) 计数，仅保留计数 ≥ min_support 的边；每条边按出现时间
    展开为事实流（保留重复时间以喂 copy 机制），端点取 head_id/tail_id（对齐后的 entity_id）。

    返回 [{"head","relation","tail","time"}]。
    """
    relations = set(relations) if relations else set(TECH_PAIR_RELATIONS)
    edge_times: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for t in triples:
        if t.get("head_type") not in DIRECTED_TECH_TYPES:
            continue
        if t.get("tail_type") not in DIRECTED_TECH_TYPES:
            continue
        relation = t.get("relation")
        if relation not in relations:
            continue
        h = t.get("head_id") or t.get("head")
        tl = t.get("tail_id") or t.get("tail")
        if not h or not tl:
            continue
        time = t.get("time") or ""
        if not time:
            continue
        if max_time is not None and time > max_time:
            continue
        edge_times[(h, relation, tl)].append(time)

    facts: list[dict] = []
    kept_edges = 0
    for (h, relation, tl), times in edge_times.items():
        if len(times) < min_support:
            continue
        kept_edges += 1
        for time in sorted(set(times)):
            facts.append({"head": h, "relation": relation, "tail": tl, "time": time})

    log.info(
        "load_directed_edges：%d 条定向边（≥%d）→ %d 条事实流，关系 %d 种",
        kept_edges, min_support, len(facts), len({r for _, r, _ in edge_times}),
    )
    return facts


def temporal_split_3way(
    triples: list[dict],
    train_ratio: float = 0.7,
    val_ratio: float = 0.1,
) -> tuple[list[dict], list[dict], list[dict]]:
    """按 time 升序切 train/val/test 三段，时间不重叠（禁止 shuffle）。

    切分点落在「时间戳边界」上——同一天的事实不会被切到两段，保证时间不重叠的语义。
    若某段为空（数据不足），返回空列表（调用方负责 warning + 降级）。
    """
    ordered = sorted(triples, key=lambda t: (t.get("time") or ""))
    n = len(ordered)
    if n == 0:
        return [], [], []

    # 按时间分组，把整组时间戳分配进 train/val/test，逼近目标比例
    groups: list[tuple[str, int]] = []
    cur_time = None
    cur_count = 0
    for t in ordered:
        tm = t.get("time") or ""
        if tm != cur_time:
            if cur_time is not None:
                groups.append((cur_time, cur_count))
            cur_time, cur_count = tm, 0
        cur_count += 1
    groups.append((cur_time, cur_count))

    train_end = max(1, int(n * train_ratio))
    val_end = max(train_end + 1, int(n * (train_ratio + val_ratio)))

    def _cut(threshold: int) -> int:
        """返回 [0, threshold) 事实对应的时间组数（整组归属，不跨时间戳）。"""
        acc = 0
        for i, (_, c) in enumerate(groups):
            if acc >= threshold:
                return i
            acc += c
        return len(groups)

    gi_train = _cut(train_end)
    gi_val = _cut(val_end)

    train_n = sum(c for _, c in groups[:gi_train])
    val_n = sum(c for _, c in groups[gi_train:gi_val])
    train = ordered[:train_n]
    val = ordered[train_n : train_n + val_n]
    test = ordered[train_n + val_n :]

    log.info(
        "时态 3-way 切分：train=%d, val=%d, test=%d（时间不重叠）",
        len(train), len(val), len(test),
    )
    return train, val, test


def encode_entities(triples: Iterable[dict]) -> tuple[dict[int, str], dict[str, int]]:
    """实体 → 连续 id（供 torch 索引）。返回 (id2e, e2id)。"""
    entities = sorted({t["head"] for t in triples} | {t["tail"] for t in triples})
    id2e = {i: e for i, e in enumerate(entities)}
    e2id = {e: i for i, e in enumerate(entities)}
    return id2e, e2id
