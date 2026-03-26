from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from catalog import DB_PATH, bootstrap_catalog, get_catalog_summary


def main() -> None:
    bootstrap_catalog()
    summary = get_catalog_summary()
    payload = {
        "db_path": str(DB_PATH),
        "counts": summary["counts"],
        "latest_news": summary["latest_news"],
        "upcoming_games": summary["upcoming_games"],
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
