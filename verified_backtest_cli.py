"""Read-only CLI for provenance-verified basketball prediction reports."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile

from verified_backtest_report import report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", help="Existing SQLite prediction ledger (never created)")
    parser.add_argument("--league", default="NBA")
    args = parser.parse_args(argv)
    if not os.path.isfile(args.database):
        print(json.dumps({"status": "error", "reason": "database_not_found"}))
        return 2
    try:
        uri = "file:" + os.path.abspath(args.database) + "?mode=ro"
        with sqlite3.connect(uri, uri=True) as db:
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
        required = {"predictions", "outcomes", "fixture_starts", "fixture_provenance"}
        if not required.issubset(tables):
            print(json.dumps({"status": "error", "reason": "missing_ledger_tables"}))
            return 2
        # Evaluate a snapshot; never write to the original ledger.
        with tempfile.TemporaryDirectory() as directory:
            snapshot = os.path.join(directory, "ledger_snapshot.sqlite")
            with sqlite3.connect(uri, uri=True) as source:
                with sqlite3.connect(snapshot) as target:
                    source.backup(target)
            result = report(snapshot, args.league)
    except (sqlite3.Error, OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"status": "error", "error_type": type(exc).__name__}))
        return 1
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
