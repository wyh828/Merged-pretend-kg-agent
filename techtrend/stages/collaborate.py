"""协同阶段（阶段 5 合并，第 10 阶段）：信号 agent × 链接预测 agent 交叉质证。

- 输入：data/interim/{works,triples}.jsonl（信号 agent 用 works，链接 agent 用 triples）。
- 输出（output/）：
  - collab_consensus.json  共识排序（verdict + 两路证据分 + 共识分）
  - collab_conflicts.json  冲突清单（signal_only / tkg_only，两路意见分歧）
  - collab_review_request.json  冲突且启用 HITL 时写给 reviewer 角色（非阻塞）

确定性协同，不依赖 LLM，可复现可审计。冲突触发既有 HITL 门（review_enable_hitl）。
"""
import json
import logging

from techtrend.io import read_jsonl
from techtrend.orchestration.collab import collaborate
from techtrend.stages.base import Stage

log = logging.getLogger(__name__)


class CollaborateStage(Stage):
    name = "collaborate"

    def run(self) -> dict:
        s = self.settings
        try:
            output_dir = s.output_dir
            output_dir.mkdir(parents=True, exist_ok=True)
            interim_dir = s.data_dir / "interim"

            works = read_jsonl(interim_dir / "works.jsonl")
            triples = read_jsonl(interim_dir / "triples.jsonl")
            if not works and not triples:
                log.warning("works/triples 为空，请先运行 --stage collect/extract/align")
                return {"stage": self.name, "status": "error", "error": "works/triples 为空"}

            result = collaborate(works, triples, s)

            consensus_rows = result.pop("consensus_rows", [])
            conflict_rows = result.pop("conflict_rows", [])

            (output_dir / "collab_consensus.json").write_text(
                json.dumps(consensus_rows, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (output_dir / "collab_conflicts.json").write_text(
                json.dumps(conflict_rows, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            # 冲突 + 启用 HITL 且非自动放行 → 写给 reviewer 角色（非阻塞）
            if result.get("conflicts") and s.review_enable_hitl and not s.review_auto_approve:
                (output_dir / "collab_review_request.json").write_text(
                    json.dumps(
                        {
                            "conflicts": result["conflicts"],
                            "hint": "reviewer 角色：审校冲突清单，确认后写 collab_review_approve.json",
                        },
                        ensure_ascii=False, indent=2,
                    ),
                    encoding="utf-8",
                )
                log.info("协同冲突 %d 条，已写 collab_review_request.json 待审校", result["conflicts"])

            log.info(
                "collaborate 完成：agree=%d, signal_only=%d, tkg_only=%d, conflicts=%d",
                result["agree"], result["signal_only"], result["tkg_only"], result["conflicts"],
            )
            return {"stage": self.name, "status": "ok", **result}
        except Exception as exc:  # noqa: BLE001
            log.exception("collaborate 阶段失败")
            return {"stage": self.name, "status": "error", "error": str(exc)}
