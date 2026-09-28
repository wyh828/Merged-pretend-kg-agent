"""时序逻辑规则挖掘 + 候选打分（可解释层）。

单关系 relates_to 下，规则空间退化为传递性 / 对称性规则：

- 对称性：(X relates_to Y) → (Y relates_to X)（共现边天然对称，置信度≈1）。
- 传递性：(X relates_to Y, T1) ∧ (Y relates_to Z, T2) → (X relates_to Z, T3)，
  要求 T1 < T3 且 T2 < T3（时序优先：体先于头发生）。

定向多关系图（uses/improves/compares/targets/competes）下，规则空间按关系展开，
三类规则（除 implication 外均带时序约束，head 时间晚于 body）：

- symmetry[r]      ：(X r Y) → (Y r X)   同关系反向边（competes/compares 近似对称）。
- implication[r1,r2]：(X r1 Y) → (X r2 Y)  同边不同关系（improves→uses 语义蕴含）。
- transitivity[r1,r2]：(X r1 Y)∧(Y r2 Z) → (X r1 Z)  传递性（需三角形，头边时间晚于体两端）。

规则是「哪些技术关联模式反复出现」的可读解释，同时作为打分器。判别力有限，
CyGNet 才是达标主力，本模块定位为解释层 + 对照。
"""
import logging
from collections import defaultdict
from typing import Iterable

log = logging.getLogger(__name__)


def mine_rules(
    train: list[dict],
    min_support: int = 5,
    min_confidence: float = 0.3,
    max_len: int = 3,
) -> list[dict]:
    """挖掘时序规则，返回 [{"label","body","head","support","confidence","len"}]。

    单关系图（共现 relates_to）退化为 1 条 symmetry + 1 条 transitivity；多关系定向图
    （uses/improves/…）按关系展开 symmetry / implication / transitivity，恢复 TLogic 判别力。
    """
    # (h, r, t) → 最早 time（ISO 日期字符串可直接比较）
    edge_time: dict[tuple[str, str, str], str] = {}
    for t in train:
        h, r, tl, tm = t.get("head"), t.get("relation"), t.get("tail"), t.get("time") or ""
        if not h or not r or not tl or not tm:
            continue
        k = (h, r, tl)
        if k not in edge_time or tm < edge_time[k]:
            edge_time[k] = tm

    relations = sorted({r for (_, r, _) in edge_time})
    # 邻接（带最早时间）：out[X][r][Z]=time（X r Z）、inn[Z][r][X]=time
    out: dict[str, dict[str, dict[str, str]]] = defaultdict(lambda: defaultdict(dict))
    inn: dict[str, dict[str, dict[str, str]]] = defaultdict(lambda: defaultdict(dict))
    for (h, r, tl), tm in edge_time.items():
        if tm < out[h][r].get(tl, "9999"):
            out[h][r][tl] = tm
        if tm < inn[tl][r].get(h, "9999"):
            inn[tl][r][h] = tm

    rules: list[dict] = []

    # symmetry[r]：(X r Y) → (Y r X)
    for r in relations:
        fwd = {(h, tl) for (h, rr, tl) in edge_time if rr == r}
        sym = sum(1 for (h, tl) in fwd if (tl, r, h) in edge_time)
        rules.append({
            "label": f"symmetry[{r}]",
            "body": f"(X {r} Y)",
            "head": f"(Y {r} X)",
            "support": sym,
            "confidence": round(sym / len(fwd), 4) if fwd else 0.0,
            "len": 1,
        })

    # implication[r1,r2]：(X r1 Y) → (X r2 Y)（同边不同关系）
    for r1 in relations:
        for r2 in relations:
            if r1 == r2:
                continue
            body = sum(1 for (h, rr, _tl) in edge_time if rr == r1)
            sup = sum(1 for (h, rr, tl) in edge_time if rr == r1 and (h, r2, tl) in edge_time)
            rules.append({
                "label": f"implication[{r1}->{r2}]",
                "body": f"(X {r1} Y)",
                "head": f"(X {r2} Y)",
                "support": sup,
                "confidence": round(sup / body, 4) if body else 0.0,
                "len": 1,
            })

    # transitivity[r1,r2]：(X r1 Y)∧(Y r2 Z) → (X r1 Z)（头边时间晚于体两端）
    for r1 in relations:
        for r2 in relations:
            body_pairs: set[tuple[str, str]] = set()
            supported: set[tuple[str, str]] = set()
            for y in inn:
                x_nbrs = inn[y].get(r1, {})   # X r1 Y
                z_nbrs = out[y].get(r2, {})   # Y r2 Z
                if not x_nbrs or not z_nbrs:
                    continue
                for x, t_xy in x_nbrs.items():
                    for z, t_yz in z_nbrs.items():
                        if x == z:
                            continue
                        body_pairs.add((x, z))
                        t_xz = edge_time.get((x, r1, z))
                        if t_xz is not None and t_xy < t_xz and t_yz < t_xz:
                            supported.add((x, z))
            rules.append({
                "label": f"transitivity[{r1},{r2}]",
                "body": f"(X {r1} Y) ∧ (Y {r2} Z)",
                "head": f"(X {r1} Z)",
                "support": len(supported),
                "confidence": round(len(supported) / len(body_pairs), 4) if body_pairs else 0.0,
                "len": 2,
            })

    out_rules = [
        r for r in rules
        if r["support"] >= min_support and r["confidence"] >= min_confidence and r["len"] <= max_len
    ]
    log.info(
        "TLogic 规则挖掘：symmetry=%d, implication=%d, transitivity=%d → 保留 %d 条",
        sum(1 for r in rules if r["label"].startswith("symmetry")),
        sum(1 for r in rules if r["label"].startswith("implication")),
        sum(1 for r in rules if r["label"].startswith("transitivity")),
        len(out_rules),
    )
    return out_rules


def score_candidates(
    s: str, r: str, rules: list[dict], graph: dict, t: str
) -> dict[str, float]:
    """对查询 (s, r, ?, t) 沿规则做带时间约束的图游走，匹配规则置信度之和为候选分。

    graph：{"out": {X: {Y: time}}, "edge_time": {(X,Y): time}}（见 :func:`_min_edge_times`）。
    返回 {candidate_entity_id: score}。
    """
    conf = {rule["label"]: rule["confidence"] for rule in rules}
    out = graph.get("out", {})
    scores: dict[str, float] = defaultdict(float)

    # 1-hop 对称性：直接邻居（时间 < t）
    for y, t_xy in out.get(s, {}).items():
        if t_xy < t:
            scores[y] += conf.get("symmetry", 0.0)
        # 2-hop 传递性：经 y 到 z（两端时间均 < t）
        for z, t_yz in out.get(y, {}).items():
            if z != s and t_yz < t:
                scores[z] += conf.get("transitivity", 0.0)

    return dict(scores)
