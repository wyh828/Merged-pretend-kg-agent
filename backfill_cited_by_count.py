"""一次性回填：给存量 works.jsonl 补齐 cited_by_count（P1-1 数据人口）。

背景：`cited_by_count` 一直在 OpenAlex `select` 字段里，但 `normalize()` 此前漏掉它，
导致已采集的 ~2008 条 work 该字段全缺。修复 normalize 后，新采集会带上该字段，
但存量游标已推进到「今天」，不会重采旧 work → 需要本脚本用 `ids.openalex` 过滤器
按 ID 批量回拉 cited_by_count 并原地补齐。

用法：
    python backfill_cited_by_count.py [--dry-run] [--chunk 50]

幂等：只回拉缺失 cited_by_count 的 ID；重复运行不产生副作用。
"""
import argparse
import json
import sys
from pathlib import Path

import httpx

from techtrend.config import Settings
from techtrend.io import read_jsonl, write_jsonl

_BASE = "https://api.openalex.org"
_SELECT = "id,cited_by_count"


def _openalex_id(wid: str) -> str:
    return wid.rsplit("/", 1)[-1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只打印，不写回")
    ap.add_argument("--chunk", type=int, default=50, help="每请求 ID 数（filter 长度安全上限）")
    args = ap.parse_args()

    s = Settings()
    path = Path(s.data_dir) / "interim" / "works.jsonl"
    works = read_jsonl(path)
    if not works:
        print("works.jsonl 为空")
        return 1

    missing = [w for w in works if w.get("cited_by_count") is None]
    print(f"works 总数 {len(works)}，缺 cited_by_count 的 {len(missing)} 条")
    if not missing:
        print("无需回填")
        return 0

    headers = {}
    params: dict = {"select": _SELECT, "per-page": str(args.chunk)}
    if s.openalex_mailto:
        headers["User-Agent"] = f"mailto:{s.openalex_mailto}"
        params["mailto"] = s.openalex_mailto
    if s.openalex_api_key:
        params["api_key"] = s.openalex_api_key

    # id -> cited_by_count
    counts: dict[str, int] = {}
    ids = [_openalex_id(w["id"]) for w in missing]
    with httpx.Client(base_url=_BASE, timeout=30, headers=headers) as client:
        for i in range(0, len(ids), args.chunk):
            chunk = ids[i : i + args.chunk]
            r = client.get("/works", params={**params, "filter": "ids.openalex:" + "|".join(chunk)})
            r.raise_for_status()
            for row in r.json().get("results", []):
                counts[_openalex_id(row["id"])] = row.get("cited_by_count")
            got = sum(1 for c in chunk if c in counts)
            print(f"  chunk {i // args.chunk + 1}: 请求 {len(chunk)}，命中 {got}")

    # 回填（含 cited_by_count=0 的合法值；仍为 None 的保留 None）
    patched = 0
    for w in works:
        if w.get("cited_by_count") is None:
            c = counts.get(_openalex_id(w["id"]))
            if c is not None:
                w["cited_by_count"] = c
                patched += 1

    print(f"回填 {patched} 条（仍缺 {len(missing) - patched} 条，多为 API 未命中/已删除）")
    if not args.dry_run and patched:
        write_jsonl(path, works)
        print(f"已写回 {path}")
    elif args.dry_run:
        print("[dry-run] 未写回")
    return 0


if __name__ == "__main__":
    sys.exit(main())
