"""CyGNet 复制机制（目标②主干）+ copy-only 确定性基线。

自实现（参考 Zhu et al. 2021 AAAI "Learning from History: Modeling Temporal
Knowledge Graphs with Sequential Copy-Generation Networks"），契合「技术演化高度
重复——同一技术反复与同类技术关联」这一规律：

- generate 模式：实体/关系嵌入，对候选 tail 打分（s 与 r 的组合嵌入与候选 o 点积）。
- copy 模式：由 (s, r) 的历史 tail 词表归一化频次得到 copy 分布。
- 融合：score = α·copy + (1-α)·generate（α 固定 tkg_alpha）。

评估口径：filtered 排名——对每条 (s,r,o,t)，o 与所有实体打分，剔除 (s,r) 在
train/val/test 中已存在的其它真 tail（known_tails），返回 MRR + Hits@1/3/10。
"""
import logging
from collections import Counter, defaultdict
from typing import Iterable

import numpy as np
import torch
import torch.nn as nn

from techtrend.prediction.metrics import hits_at, mrr_at

log = logging.getLogger(__name__)

_K = (1, 3, 10)


# ---------------------------------------------------------------------------
# 数据编码与历史词表
# ---------------------------------------------------------------------------
def encode_ids(triples: Iterable[dict]) -> tuple[dict[str, int], dict[str, int], dict[int, str], dict[int, str]]:
    """实体/关系 → 连续 id。返回 (e2id, r2id, id2e, id2r)。"""
    entities = sorted({t["head"] for t in triples} | {t["tail"] for t in triples})
    relations = sorted({t["relation"] for t in triples})
    e2id = {e: i for i, e in enumerate(entities)}
    r2id = {r: i for i, r in enumerate(relations)}
    id2e = {i: e for e, i in e2id.items()}
    id2r = {i: r for r, i in r2id.items()}
    return e2id, r2id, id2e, id2r


def build_history(
    train: list[dict], e2id: dict[str, int], r2id: dict[str, int]
) -> dict[tuple[int, int], Counter]:
    """(s, r) → 历史 tail 频次（CyGNet 的 copy 词表）。"""
    hist: dict[tuple[int, int], Counter] = defaultdict(Counter)
    for t in train:
        s = e2id.get(t["head"])
        r = r2id.get(t["relation"])
        o = e2id.get(t["tail"])
        if s is None or r is None or o is None:
            continue
        hist[(s, r)][o] += 1
    return hist


def build_copy_matrix(
    history: dict[tuple[int, int], Counter], num_entities: int, num_relations: int
) -> np.ndarray:
    """历史频次 → 归一化 copy 分布矩阵 [num_relations, num_entities, num_entities]。

    copy_matrix[r, s, o] = freq[(s,r)][o] / sum(freq[(s,r)])；无历史的行全 0。
    """
    cm = np.zeros((num_relations, num_entities, num_entities), dtype=np.float32)
    for (s, r), cnt in history.items():
        total = sum(cnt.values())
        if total <= 0:
            continue
        for o, c in cnt.items():
            cm[r, s, o] = c / total
    return cm


def copy_only_score(
    s: int, r: int, o: int, history: dict[tuple[int, int], Counter], id2e: dict[int, str] | None = None
) -> float:
    """Tier1 基线：仅复制历史——tail 在 (s,r) 历史中的频次。无历史则 0。

    这是 CyGNet「copy mode」的确定性退化版，先跑通拿第一个时态 MRR。
    （时间衰减作为后续增强，默认不启用。）
    """
    return float(history.get((s, r), Counter()).get(o, 0))


# ---------------------------------------------------------------------------
# 模型（torch）
# ---------------------------------------------------------------------------
class CyGNet(nn.Module):
    """复制 + 生成混合打分。

    生成模式输出 [B, N] 的 logits；copy 分布由外部 copy 矩阵提供（非参数）。
    融合：score = α·copy + (1-α)·softmax(logits)。
    """

    def __init__(self, num_entities: int, num_relations: int, dim: int, alpha: float = 0.5):
        super().__init__()
        self.num_entities = num_entities
        self.num_relations = num_relations
        self.dim = dim
        self.alpha = alpha
        self.entity_emb = nn.Embedding(num_entities, dim)
        self.relation_emb = nn.Embedding(num_relations, dim)
        nn.init.xavier_uniform_(self.entity_emb.weight)
        nn.init.xavier_uniform_(self.relation_emb.weight)

    def generate_logits(self, s: torch.Tensor, r: torch.Tensor) -> torch.Tensor:
        """DistMult 式打分：(E[s] ∘ R[r]) · E[o] → [B, N]。

        对单关系的对称共现边，逐元素乘积（而非相加）更贴合「相似性」语义，
        且与静态基线 RotatE/DistMult 同族，便于公平对照。
        """
        h = self.entity_emb(s) * self.relation_emb(r)  # [B, dim]
        return h @ self.entity_emb.weight.t()          # [B, N]


def train_cygnet(
    train: list[dict],
    val: list[dict],
    dim: int = 128,
    epochs: int = 30,
    neg_samples: int = 10,
    alpha: float = 0.5,
    lr: float = 0.01,
    seed: int = 42,
) -> dict:
    """负采样 + margin ranking 训练（每条正例采 neg_samples 个非真 tail）；val 上早停选最优轮次。

    返回 bundle dict：
      {model, e2id, r2id, id2e, id2r, history, copy_matrix, num_entities, num_relations}
    供 :func:`evaluate_cygnet` / :func:`future_link_scores` 使用。
    """
    torch.manual_seed(seed)
    e2id, r2id, id2e, id2r = encode_ids(train + val)
    num_entities, num_relations = len(e2id), len(r2id)

    history = build_history(train, e2id, r2id)
    copy_matrix_np = build_copy_matrix(history, num_entities, num_relations)

    model = CyGNet(num_entities, num_relations, dim, alpha=alpha)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)

    def _to_ids(triples: list[dict]):
        s = torch.tensor([e2id[t["head"]] for t in triples], dtype=torch.long)
        r = torch.tensor([r2id[t["relation"]] for t in triples], dtype=torch.long)
        o = torch.tensor([e2id[t["tail"]] for t in triples], dtype=torch.long)
        return s, r, o

    s_tr, r_tr, o_tr = _to_ids(train)
    s_val, r_val, o_val = _to_ids(val) if val else (None, None, None)
    n = len(s_tr)
    batch = 4096

    def _neg_margin_loss(s, r, o):
        # 生成模式单独训练：负采样 + margin ranking（计划书「负采样 + 打分」）。
        # copy 是固定先验，只在推理时与生成分布融合（α），不进训练损失——
        # 否则 copy 会「遮蔽」生成模式的梯度，使其学不会泛化。
        b = len(s)
        logits = model.generate_logits(s, r)                      # [b, N]
        neg = torch.randint(0, num_entities, (b, neg_samples))
        neg = torch.where(neg == o.unsqueeze(1), (o.unsqueeze(1) + 1) % num_entities, neg)
        idx = torch.arange(b)
        pos = logits[idx, o]                                      # [b]
        neg_s = logits[idx.unsqueeze(1), neg]                     # [b, neg]
        return torch.relu(1.0 - pos.unsqueeze(1) + neg_s).mean()

    best_state = None
    best_val = float("inf")
    log.info(
        "CyGNet 训练：entities=%d, relations=%d, dim=%d, epochs=%d, neg=%d, alpha=%.2f",
        num_entities, num_relations, dim, epochs, neg_samples, alpha,
    )
    for epoch in range(1, epochs + 1):
        model.train()
        perm = torch.randperm(n)
        total_loss = 0.0
        nb = 0
        for i in range(0, n, batch):
            idx = perm[i : i + batch]
            loss = _neg_margin_loss(s_tr[idx], r_tr[idx], o_tr[idx])
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            total_loss += float(loss.item())
            nb += 1
        train_loss = total_loss / max(nb, 1)

        val_loss = train_loss
        if s_val is not None:
            model.eval()
            with torch.no_grad():
                val_loss = float(_neg_margin_loss(s_val, r_val, o_val).item())
        if val_loss < best_val:
            best_val = val_loss
            best_state = {
                "entity_emb": model.entity_emb.weight.detach().clone(),
                "relation_emb": model.relation_emb.weight.detach().clone(),
            }
        if epoch % 5 == 0 or epoch == 1:
            log.info("  epoch %d/%d  train_loss=%.4f  val_loss=%.4f", epoch, epochs, train_loss, val_loss)

    if best_state is not None:
        model.entity_emb.weight.data.copy_(best_state["entity_emb"])
        model.relation_emb.weight.data.copy_(best_state["relation_emb"])

    return {
        "model": model,
        "e2id": e2id,
        "r2id": r2id,
        "id2e": id2e,
        "id2r": id2r,
        "history": history,
        "copy_matrix": copy_matrix_np,
        "num_entities": num_entities,
        "num_relations": num_relations,
    }


# ---------------------------------------------------------------------------
# 评估（numpy 向量化）
# ---------------------------------------------------------------------------
def _score_all_np(bundle: dict, s: np.ndarray, r: np.ndarray) -> np.ndarray:
    """批量对全部实体打分 [B, N]。"""
    model = bundle["model"]
    E = model.entity_emb.weight.detach().numpy()
    R = model.relation_emb.weight.detach().numpy()
    alpha = model.alpha
    h = E[s] * R[r]                                   # [B, dim] DistMult
    logits = h @ E.T                                  # [B, N]
    logits = logits - logits.max(axis=1, keepdims=True)
    e = np.exp(logits)
    gen = e / e.sum(axis=1, keepdims=True)            # [B, N] softmax 生成分布
    copy = bundle["copy_matrix"][r, s]                # [B, N]
    return alpha * copy + (1.0 - alpha) * gen


def build_known_tails(
    triples: list[dict], e2id: dict[str, int], r2id: dict[str, int]
) -> dict[tuple[int, int], np.ndarray]:
    """(s, r) → 全部时间段出现过的 tail 集合（int 数组，含 test 自身），供 filtered 剔除。"""
    tails: dict[tuple[int, int], set[int]] = defaultdict(set)
    for t in triples:
        s = e2id.get(t["head"])
        r = r2id.get(t["relation"])
        o = e2id.get(t["tail"])
        if s is None or r is None or o is None:
            continue
        tails[(s, r)].add(o)
    return {k: np.fromiter(v, dtype=np.int64) for k, v in tails.items()}


def evaluate_cygnet(
    bundle: dict,
    test: list[dict],
    k: tuple[int, ...] = _K,
    known_triples: list[dict] | None = None,
) -> dict:
    """CyGNet filtered 排名评估（向量化，chunk 处理）。返回 MRR + Hits@1/3/10。

    known_triples：filtered 剔除用的「全部已知三元组」（train+val+test），与 RotatE 的
    pykeen filtered 口径一致（剔除其它已知 tail，而非仅 test tail），保证同协议对比。
    缺省退化为 test（向后兼容）。
    """
    e2id, r2id = bundle["e2id"], bundle["r2id"]
    all_triples = known_triples if known_triples is not None else test
    known_tails = build_known_tails(all_triples, e2id, r2id)

    rows = [(e2id[t["head"]], r2id[t["relation"]], e2id[t["tail"]]) for t in test
            if t["head"] in e2id and t["relation"] in r2id and t["tail"] in e2id]
    if not rows:
        log.warning("test 无已知实体三元组，CyGNet 评估跳过")
        return {"mrr": None, "hits_at_1": None, "hits_at_3": None, "hits_at_10": None}

    ranks: list[int] = []
    chunk = 8192
    for start in range(0, len(rows), chunk):
        batch_rows = rows[start : start + chunk]
        s = np.array([x[0] for x in batch_rows], dtype=np.int64)
        r = np.array([x[1] for x in batch_rows], dtype=np.int64)
        o = np.array([x[2] for x in batch_rows], dtype=np.int64)
        scores = _score_all_np(bundle, s, r)           # [B, N]
        o_score = scores[np.arange(len(s)), o]
        for i in range(len(s)):
            sc = scores[i]
            o_sc = o_score[i]
            # filtered 排名（剔除 (s,r) 已知 tail），并用「平均秩」破同分：全 0（无历史）时
            # 正确 tail 不再侥幸并列第 1，而是 ~N/2 的平均秩，避免 copy-only 被无信息同分虚高。
            known = known_tails.get((int(s[i]), int(r[i])))
            mask = np.ones(len(sc), dtype=bool)
            if known is not None and len(known):
                mask[known] = False
            mask[o[i]] = True  # 正确 tail 自身保留（标准 filtered 协议：只剔除「其它」已知 tail）
            cand = sc[mask]
            above = int(np.sum(cand > o_sc))
            ties = int(np.sum(cand == o_sc))           # 含正确 tail 自身
            ranks.append(above + 1 + (ties - 1) / 2.0)

    return {
        "mrr": mrr_at(ranks),
        "hits_at_1": hits_at(ranks, 1),
        "hits_at_3": hits_at(ranks, 3),
        "hits_at_10": hits_at(ranks, 10),
        "ranks": ranks,
    }


def evaluate_copy_only(
    e2id: dict[str, int],
    r2id: dict[str, int],
    history: dict[tuple[int, int], Counter],
    test: list[dict],
    k: tuple[int, ...] = _K,
    known_triples: list[dict] | None = None,
) -> dict:
    """copy-only 基线 filtered 排名评估（确定性，无训练，纯 copy 分布）。"""
    num_entities = len(e2id)
    num_relations = len(r2id)
    copy_matrix = build_copy_matrix(history, num_entities, num_relations)
    model = CyGNet(num_entities, num_relations, 1, alpha=1.0)  # alpha=1 → 纯 copy
    bundle = {
        "model": model, "e2id": e2id, "r2id": r2id,
        "copy_matrix": copy_matrix, "num_entities": num_entities,
    }
    return evaluate_cygnet(bundle, test, k=k, known_triples=known_triples)


def future_link_scores(bundle: dict, heads: list[str]) -> dict[str, float]:
    """每个实体的「未来链接概率」——未来查询头对该实体的平均融合分。

    heads：未来（test）窗口内出现的查询头 entity_id。返回 {entity_id: score}。
    """
    e2id = bundle["e2id"]
    id2e = bundle["id2e"]
    ids = [e2id[h] for h in heads if h in e2id]
    if not ids:
        return {}
    s = np.array(ids, dtype=np.int64)
    r = np.zeros(len(s), dtype=np.int64)  # 单关系 relates_to
    scores = _score_all_np(bundle, s, r)  # [B, N]
    agg = scores.mean(axis=0)             # 每实体平均未来链接分
    return {id2e[i]: float(agg[i]) for i in range(len(agg))}
