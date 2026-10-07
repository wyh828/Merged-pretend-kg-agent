"""Offline import, function inventory, and optional tiny CPU model checks.

Run from any directory with this checkout's Python. No network or database calls.
Synthetic fixtures verify execution only; their metrics are not research evidence.
"""
from __future__ import annotations

import argparse
import ast
import importlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def inventory() -> list[dict]:
    """Read every project Python file and record its declared function contract."""
    records = []
    paths = [ROOT / name for name in ("main.py", "cron.py", "backfill_cited_by_count.py")]
    paths.extend(sorted((ROOT / "techtrend").rglob("*.py")))
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        def visit(node, prefix=""):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    name = prefix + child.name
                    records.append({"file": path.relative_to(ROOT).as_posix(), "line": child.lineno,
                                    "name": name, "arguments": ast.unparse(child.args),
                                    "returns": ast.unparse(child.returns) if child.returns else "unspecified",
                                    "purpose": (ast.get_docstring(child) or "No docstring").splitlines()[0],
                                    "calls": sorted({ast.unparse(c.func) for c in ast.walk(child) if isinstance(c, ast.Call)})})
                    visit(child, name + ".")
                elif isinstance(child, ast.ClassDef):
                    visit(child, prefix + child.name + ".")
                else:
                    visit(child, prefix)
        visit(tree)
    return records


def check_imports() -> dict[str, str]:
    """Import project modules; initialization errors are returned individually."""
    results = {}
    for path in sorted((ROOT / "techtrend").rglob("*.py")):
        parts = path.relative_to(ROOT).with_suffix("").parts
        module = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        try:
            importlib.import_module(module)
            results[module] = "ok"
        except Exception as exc:
            results[module] = f"error: {type(exc).__name__}: {exc}"
    return results


def check_models() -> dict:
    """Train one CPU epoch on eight synthetic facts, never on project data."""
    from techtrend.prediction import run_rotate
    from techtrend.prediction.cygnet import train_cygnet, evaluate_cygnet
    facts = [{"head": str(i), "relation": "r", "tail": str((i + 1) % 8), "time": "2023-01-01"} for i in range(8)]
    rotate = run_rotate(facts, facts[:2], dim=8, epochs=1, device="cpu")
    bundle = train_cygnet(facts, [], dim=8, epochs=1, neg_samples=2)
    cygnet = evaluate_cygnet(bundle, facts[:2], known_triples=facts)
    assert all(v is not None for v in rotate.values()), rotate
    assert cygnet["mrr"] is not None, cygnet
    return {"fixture": "synthetic eight facts; seed=42; CPU; one epoch; not experiment results",
            "rotate": rotate, "cygnet": cygnet}


def run() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", action="store_true")
    parser.add_argument("--inventory", action="store_true")
    args = parser.parse_args()
    functions = inventory()
    if args.inventory:
        target = ROOT / "Attempt/docs/function_inventory_00.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(functions, ensure_ascii=False, indent=2), encoding="utf-8")
    imports = check_imports()
    result = {"functions": len(functions), "modules": len(imports),
              "import_errors": {k: v for k, v in imports.items() if v != "ok"}}
    if args.models:
        result["model_checks"] = check_models()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["import_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(run())
