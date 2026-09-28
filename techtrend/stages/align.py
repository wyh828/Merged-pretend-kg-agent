"""对齐阶段（P2 新增）：跨源实体对齐。

- 输入：data/interim/{triples,nodes}.jsonl。
- 输出：回写同文件（nodes 补 entity_id / triples 补 head_id·tail_id）+ data/interim/alignment.jsonl 审计。
- 调 graph.alignment.align_entities（强 ID 锚点 → string 匹配 → 可选 LLM 消歧）。
"""
import logging

from techtrend.graph.alignment import align_entities
from techtrend.io import read_jsonl, write_jsonl
from techtrend.stages.base import Stage

log = logging.getLogger(__name__)


class AlignStage(Stage):
    name = "align"

    def run(self) -> dict:
        s = self.settings
        try:
            interim_dir = s.data_dir / "interim"
            nodes = read_jsonl(interim_dir / "nodes.jsonl")
            triples = read_jsonl(interim_dir / "triples.jsonl")
            if not nodes and not triples:
                log.warning("nodes/triples 为空，请先运行 --stage extract")
                return {
                    "stage": self.name, "status": "ok", "entities": 0,
                    "merged": 0, "aligned_by_anchor": 0, "aligned_by_string": 0,
                }

            nodes_out, triples_out, audit = align_entities(
                nodes, triples,
                threshold=s.align_name_threshold,
                use_llm=s.align_enable_llm,
            )

            write_jsonl(interim_dir / "nodes.jsonl", nodes_out)
            write_jsonl(interim_dir / "triples.jsonl", triples_out)
            write_jsonl(interim_dir / "alignment.jsonl", audit)

            string_aligned = sum(1 for a in audit if a.get("anchor_id"))
            anchored = sum(1 for n in nodes_out if n.get("entity_id") == n.get("id"))
            log.info(
                "align 完成：entities=%d, anchored=%d, string_aligned=%d",
                len(nodes_out), anchored, string_aligned,
            )
            return {
                "stage": self.name,
                "status": "ok",
                "entities": len(nodes_out),
                "merged": string_aligned,
                "aligned_by_anchor": anchored,
                "aligned_by_string": string_aligned,
            }
        except Exception as exc:  # noqa: BLE001
            log.exception("align 阶段失败")
            return {"stage": self.name, "status": "error", "error": str(exc)}
