"""Run from any directory; all data remains below this checkout's DATA_DIR."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from techtrend.config import Settings
from techtrend.data_preparation import DataPreparation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    prep = DataPreparation(Settings(), args.config)
    result = prep.run()
    print(json.dumps({k: v for k, v in result.items() if k not in {"effective_config", "failures", "environment"}},
                     ensure_ascii=False, indent=2))
    return 1 if result["stopped"] or result["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
