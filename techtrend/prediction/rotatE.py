"""RotatE 链接预测基线（pykeen 包装）。

- build_triples_factory：字符串三元组 → pykeen TriplesFactory。
- temporal_split：按 time 升序切分（train 早 80% / test 晚 20%），禁止 shuffle 防泄漏。
- run_rotate：pykeen.pipeline(model="RotatE") → 取 filtered MRR / Hits@1/3/10。
"""
import logging
from typing import Iterable

log = logging.getLogger(__name__)

_FILTERED_METRICS = {
    "filtered_mrr": "both.realistic.inverse_harmonic_mean_rank",
    "hits_at_1": "both.realistic.hits_at_1",
    "hits_at_3": "both.realistic.hits_at_3",
    "hits_at_10": "both.realistic.hits_at_10",
}


def _as_labeled(triples: Iterable[dict]) -> list[tuple[str, str, str]]:
    return [(t["head"], t["relation"], t["tail"]) for t in triples]


def _as_array(triples: Iterable[dict]):
    """pykeen 1.11 的 from_labeled_triples 需要 shape (n,3) dtype str 的 ndarray。"""
    import numpy as np

    return np.asarray(_as_labeled(triples), dtype=str)


def build_triples_factory(triples: Iterable[dict]):
    """构建 TriplesFactory（实体/关系 ID 编码）。"""
    from pykeen.triples import TriplesFactory

    return TriplesFactory.from_labeled_triples(triples=_as_array(triples))


def temporal_split(triples: list[dict], train_ratio: float = 0.8) -> tuple[list[dict], list[dict]]:
    """按 time 升序切分，train=早 80%、test=晚 20%，时间不重叠。

    注意：本 P1 图谱以 Paper 为头实体，Paper 是「一次性」实体（只在自身发表时间出现），
    时态切分后 test 的 Paper 几乎全部不在 train 中，transductive 评估会退化为空集。
    故时态切分保留给 P3 的 TKG / 持久实体图使用；静态 RotatE 基线用 :func:`random_split`。
    """
    ordered = sorted(triples, key=lambda t: (t.get("time") or ""))
    k = int(len(ordered) * train_ratio)
    return ordered[:k], ordered[k:]


def random_split(triples: list[dict], train_ratio: float = 0.8, seed: int = 42) -> tuple[list[dict], list[dict]]:
    """随机切分（固定种子，可复现），train/test 共享实体。

    静态 KG 嵌入（RotatE）的链接预测标准做法是随机切分（FB15k/WN18 范式）；
    时态切分属于 TKG 外推（P3）。
    """
    import random

    shuffled = list(triples)
    random.Random(seed).shuffle(shuffled)
    k = int(len(shuffled) * train_ratio)
    return shuffled[:k], shuffled[k:]


def _filter_known(triples, entity_to_id, relation_to_id) -> list[tuple[str, str, str]]:
    """丢弃含 train 未见过实体/关系的 test 三元组（时态切分常引入新实体）。"""
    out = []
    for h, r, t in _as_labeled(triples):
        if h in entity_to_id and t in entity_to_id and r in relation_to_id:
            out.append((h, r, t))
    return out


def _filter_known_array(triples, entity_to_id, relation_to_id):
    import numpy as np

    return np.asarray(
        _filter_known(triples, entity_to_id, relation_to_id), dtype=str
    )


def run_rotate(
    train: list[dict],
    test: list[dict],
    dim: int = 128,
    epochs: int = 50,
    device: str | None = None,
) -> dict:
    """跑 pykeen RotatE，返回 filtered 指标 dict。"""
    from pykeen.pipeline import pipeline
    from pykeen.triples import TriplesFactory

    train_tf = TriplesFactory.from_labeled_triples(triples=_as_array(train))
    known_test = _filter_known_array(
        test, train_tf.entity_to_id, train_tf.relation_to_id
    )
    if len(known_test) == 0:
        log.warning("test 中无已知实体的三元组，跳过 RotatE 评估")
        return {k: None for k in _FILTERED_METRICS}
    test_tf = TriplesFactory.from_labeled_triples(
        triples=known_test,
        entity_to_id=train_tf.entity_to_id,
        relation_to_id=train_tf.relation_to_id,
        create_inverse_triples=False,
    )
    log.info(
        "RotatE：train=%d triples, test=%d triples（过滤后）, dim=%d, epochs=%d",
        train_tf.num_triples, test_tf.num_triples, dim, epochs,
    )
    result = pipeline(
        model="RotatE",
        model_kwargs=dict(embedding_dim=dim),
        training=train_tf,
        testing=test_tf,
        training_kwargs=dict(num_epochs=epochs),
        random_seed=42,
        device=device,
    )
    mr = result.metric_results
    out: dict = {}
    for key, name in _FILTERED_METRICS.items():
        try:
            out[key] = float(mr.get_metric(name))
        except Exception as exc:  # noqa: BLE001 —— 指标缺失时记录并置 None
            log.warning("取指标 %s 失败：%s", name, exc)
            out[key] = None
    return out
