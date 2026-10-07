"""Validate downloaded sharing ZIP files without extracting or changing them."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from techtrend.sharing import verify_archive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="+")
    args = parser.parse_args()
    for name in args.archives:
        print(json.dumps({"file": name, **verify_archive(Path(name))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
