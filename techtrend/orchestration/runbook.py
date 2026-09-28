"""每日运行手册（P5 编排核心）。

run_daily(settings) 按 roles.py 的角色顺序串行执行底层 9 阶段
（collect → extract → align → build_graph → predict → evaluate → report → notify → visualize），
每一步打角色标签 + 独立 summary，最终追加一条 run_manifest.jsonl（无论成败）。

- 短路守卫：daily_skip_if_no_new 且全源 0 新增 → 跳下游（extract/align/build_graph/
  predict/evaluate），直接 report+notify，manifest 记 noop=true。避免空跑烧 LLM/CPU。
- HITL 审校：review_enable_hitl 且非 auto → report 前写 review_request.json 并等待
  review_approve.json（超时可配，0 = 不限）。
- 与 hermes-agent 解耦：本模块不 import 任何调度器，只依赖底层 Stage。

「0 新增短路」判定只看 id 去重后的 new_records（collect 各源 handler 返回值），
不看 github star 快照（star 时序需每日新点，见 PROJECT_PLAN §十 风险）。
"""
import json
import logging
import time
from datetime import datetime
from pathlib import Path

from techtrend.config import Settings
from techtrend.io import append_jsonl
from techtrend.orchestration.roles import STAGE_ROLE
from techtrend.stages import get_default_stages

log = logging.getLogger(__name__)

# 底层 9 阶段名（含第 8 阶段 notify、第 9 阶段 visualize）
ALL_STAGES: tuple[str, ...] = (
    "collect", "extract", "align", "build_graph", "predict", "evaluate", "report", "notify", "visualize",
)
# 短路守卫跳过的下游阶段（report+notify 仍执行）
_DOWNSTREAM = ("extract", "align", "build_graph", "predict", "evaluate")


def _run_id() -> str:
    return datetime.now().strftime("%Y%m%dT%H%M%S")


def _new_records(collect_result: dict) -> dict[str, int]:
    """从 collect 结果抽各源 id 去重后的新增条数（只取 int，忽略 error/unknown/star 快照）。"""
    sources = collect_result.get("sources", {}) or {}
    return {k: v for k, v in sources.items() if isinstance(v, int) and not isinstance(v, bool)}


def _is_noop(sources: dict, settings: Settings) -> bool:
    """全源 0 新增 → 短路下游。有源 error 时不短路（无法确定是否真无新增）。"""
    if not settings.daily_skip_if_no_new:
        return False
    if settings.daily_mode != "incremental":
        return False
    new = {k: v for k, v in sources.items() if isinstance(v, int) and not isinstance(v, bool)}
    if not new:
        return False
    has_error = any(v == "error" for v in sources.values())
    return not has_error and sum(new.values()) == 0


def _run_stage(stage_pool: dict, name: str, role_label: str) -> dict:
    """执行单个底层阶段，打角色标签；异常不抛出（记录 error 继续）。"""
    stage = stage_pool.get(name)
    if stage is None:
        log.error("未知阶段 %s", name)
        return {"stage": name, "status": "error", "error": "unknown stage"}
    log.info("[role=%s] → 进入阶段 [%s]", role_label, name)
    try:
        result = stage.run()
    except Exception as exc:  # noqa: BLE001 —— 单阶段异常不阻断后续，记 error
        log.exception("[role=%s] 阶段 %s 抛异常", role_label, name)
        result = {"stage": name, "status": "error", "error": str(exc)}
    log.info("[role=%s] ← 阶段 [%s] status=%s", role_label, name, result.get("status"))
    return result


def _review_checkpoint(settings: Settings, run_id: str, results: list[dict]) -> bool:
    """HITL 审校卡点（reviewer 角色）。auto 放行时直接返回 True。

    非 auto：写 review_request.json，轮询等 review_approve.json（{"approve": true/false}），
    超时（review_timeout_seconds>0）按 auto 放行，避免无人值守卡死。
    """
    if not settings.review_enable_hitl or settings.review_auto_approve:
        return True

    out_dir = settings.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    req_path = out_dir / "review_request.json"
    appr_path = out_dir / "review_approve.json"

    req = {
        "run_id": run_id,
        "errors": [r for r in results if r.get("status") == "error"],
        "hint": "确认后写 review_approve.json（{\"approve\": true}）继续，或删除该文件重试",
    }
    req_path.write_text(json.dumps(req, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("HITL 审校：已写 %s，等待 %s", req_path, appr_path)

    deadline = time.time() + settings.review_timeout_seconds if settings.review_timeout_seconds > 0 else None
    while True:
        if appr_path.exists():
            try:
                data = json.loads(appr_path.read_text(encoding="utf-8"))
                approved = bool(data.get("approve", True))
            except Exception:  # noqa: BLE001 —— 坏文件当作未就绪，消费后继续等
                appr_path.unlink(missing_ok=True)
                time.sleep(2)
                continue
            appr_path.unlink(missing_ok=True)  # 消费掉
            if not approved:
                log.warning("HITL 审校被拒绝，仍继续（无人值守不阻断）")
            return approved
        if deadline is not None and time.time() > deadline:
            log.warning("HITL 审校超时（%ds），按 auto 放行", settings.review_timeout_seconds)
            return True
        time.sleep(2)


def _append_manifest(settings: Settings, manifest: dict) -> None:
    path = Path(settings.run_manifest_file)
    append_jsonl(path, [manifest])
    log.info("run_manifest 追加一条 → %s", path)


def run_daily(settings: Settings) -> dict:
    """执行一次每日运行，返回 run manifest dict。"""
    started = datetime.now()
    run_id = _run_id()
    stage_pool = {s.name: s for s in get_default_stages(settings)}
    manifest_stages: dict[str, str] = {n: "pending" for n in ALL_STAGES}
    results: list[dict] = []

    # 1) collector → collect（增量，各源 cursor + id 去重）
    collect_result = _run_stage(stage_pool, "collect", role_label="collector")
    results.append(collect_result)
    manifest_stages["collect"] = collect_result.get("status", "error")
    new_records = _new_records(collect_result)

    # 2) 守卫：全源 0 新增 → 短路下游，直接 report+notify
    noop = _is_noop(collect_result.get("sources", {}), settings)
    if noop:
        log.info("全源 0 新增 → 短路下游（%s），直接 report+notify", ",".join(_DOWNSTREAM))
        for st in _DOWNSTREAM:
            manifest_stages[st] = "skipped"
    else:
        # 3) extractor → extract + align + build_graph
        for st in ("extract", "align", "build_graph"):
            r = _run_stage(stage_pool, st, role_label=STAGE_ROLE.get(st, "extractor"))
            results.append(r)
            manifest_stages[st] = r.get("status", "error")
        # 4) analyst → predict　5) integrator → evaluate
        for st in ("predict", "evaluate"):
            r = _run_stage(stage_pool, st, role_label=STAGE_ROLE.get(st, "analyst"))
            results.append(r)
            manifest_stages[st] = r.get("status", "error")

    # 6) reviewer → HITL 审校卡点（report 前）
    hitl_approved = _review_checkpoint(settings, run_id, results)

    # 7) reporter → report + notify + visualize
    for st in ("report", "notify", "visualize"):
        r = _run_stage(stage_pool, st, role_label="reporter")
        results.append(r)
        manifest_stages[st] = r.get("status", "error")

    finished = datetime.now()
    status = "ok" if all(manifest_stages[s] in ("ok", "skipped") for s in ALL_STAGES) else "error"

    manifest = {
        "run_id": run_id,
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": finished.isoformat(timespec="seconds"),
        "mode": settings.daily_mode,
        "status": status,
        "new_records": new_records,
        "stages": manifest_stages,
        "noop": noop,
        "hitl_approved": hitl_approved,
    }
    _append_manifest(settings, manifest)
    log.info(
        "run_daily 完成：run_id=%s status=%s noop=%s new_records=%s",
        run_id, status, noop, new_records,
    )
    return manifest


__all__ = ["run_daily", "ALL_STAGES"]
