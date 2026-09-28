"""techtrend.orchestration.collab（阶段 5 合并：确定性多智能体协同）最小回归。

只测纯函数（cross_examine 分类逻辑 + signal_agent_scores），不触发 CyGNet 训练。
运行（仓库根目录）：
    E:\\conda_envs\\techtrend\\python.exe -m pytest tests/test_collab.py -v
"""
from __future__ import annotations

from techtrend.config import Settings
from techtrend.orchestration.collab import cross_examine, signal_agent_scores


def test_cross_examine_classification_and_conflicts() -> None:
    # a：两路都高 → agree；b：仅信号高 → signal_only；c：仅链接高 → tkg_only
    signal = {"a": 0.9, "b": 0.6, "c": 0.1}
    link = {"a": 0.8, "b": 0.3, "c": 0.7}
    rows, conflicts = cross_examine(signal, link, signal_weight=0.5)

    by = {r["concept"]: r for r in rows}
    assert by["a"]["verdict"] == "agree"
    assert by["b"]["verdict"] == "signal_only"
    assert by["c"]["verdict"] == "tkg_only"

    # 共识分在 [0,1]，共识榜首为两路都高的 a
    assert all(0.0 <= r["consensus"] <= 1.0 for r in rows)
    assert rows[0]["concept"] == "a"

    # 冲突 = signal_only + tkg_only
    assert len(conflicts) == 2
    assert {c["concept"] for c in conflicts} == {"b", "c"}


def test_cross_examine_missing_link_defaults_to_signal_only() -> None:
    # 链接 agent 对 b 无意见（缺失）→ 仅信号高也归 signal_only
    signal = {"a": 0.9, "b": 0.8, "c": 0.1}
    link = {"a": 0.9}
    rows, conflicts = cross_examine(signal, link)
    by = {r["concept"]: r for r in rows}
    assert by["a"]["verdict"] == "agree"
    assert by["b"]["verdict"] == "signal_only"
    assert by["c"]["verdict"] == "neither"
    assert len(conflicts) == 1


def test_signal_agent_scores_from_works() -> None:
    s = Settings()
    works = []
    for month in range(12):
        ym = f"2025-{month + 1:02d}"
        works.append(
            {"publication_date": f"{ym}-15", "concepts": [{"id": "https://openalex.org/C100", "name": "A"}]}
        )
        works.append(
            {"publication_date": f"{ym}-15", "concepts": [{"id": "https://openalex.org/C200", "name": "B"}]}
        )
    scores = signal_agent_scores(works, s)
    assert set(scores) == {"C100", "C200"}
    assert all(0.0 <= v <= 1.0 for v in scores.values())
