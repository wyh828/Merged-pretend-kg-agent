"""Build versioned sharing packages from a validated offline Neo4j dump."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from techtrend.config import Settings, resolve_project_path
from techtrend.sharing import export_shares


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="Attempt/configs/sharing_00.yaml")
    parser.add_argument("--neo4j-dump", required=True)
    parser.add_argument("--graph-validation", required=True)
    args = parser.parse_args()
    output = export_shares(Settings(), resolve_project_path(args.config),
                           resolve_project_path(args.neo4j_dump), resolve_project_path(args.graph_validation))
    print(json.dumps({"status": "prepared", "directory": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
