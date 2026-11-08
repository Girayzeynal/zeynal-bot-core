"""Read-only CLI for calibration eligibility checks.

Usage:
  python audit_calibration_archive.py --db /path/to/predictions.sqlite --league NBA
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from calibration_eligibility_audit import audit_calibration_eligibility
from prediction_ledger import PredictionLedger


def run(db_path: str, league: str = "NBA") -> dict:
    path = Path(db_path).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError("Archive path must be an existing file")
    # SQLite URI mode=ro prevents creating or mutating the source database.
    uri = path.as_uri() + "?mode=ro"

    class ReadOnlyLedger(PredictionLedger):
        def __init__(self):
            self.db_path = str(path)

        def _connect(self):
            return sqlite3.connect(uri, uri=True, timeout=10)

    ledger = ReadOnlyLedger()
    with ledger._connect() as db:
        required = {"predictions", "outcomes"}
        present = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if not required.issubset(present):
            raise ValueError("Archive is missing required tables: " + ", ".join(sorted(required - present)))
    return audit_calibration_eligibility(ledger, league)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only pregame calibration eligibility report")
    parser.add_argument("--db", required=True, help="Existing SQLite archive path")
    parser.add_argument("--league", default="NBA", help="League identifier (default NBA)")
    args = parser.parse_args(argv)
    report = run(args.db, args.league)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
