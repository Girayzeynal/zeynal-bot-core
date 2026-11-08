"""Read-only production ledger readiness check.

Never creates a database, never prints private forecast data, and fails closed
when the configured Fly.io /data volume is absent.
"""
from __future__ import annotations

import json
import os
import sqlite3


def ledger_readiness(db_path: str = "/data/prediction_ledger.sqlite", mount_path: str = "/data") -> dict:
    report = {"volume_mounted": os.path.ismount(mount_path), "database_exists": False,
              "status": "blocked", "prediction_count": None,
              "outcome_count": None, "espn_provenance_count": None}
    if not report["volume_mounted"]:
        report["reason"] = "persistent_volume_not_mounted"
        return report
    root = os.path.realpath(mount_path)
    target = os.path.realpath(db_path)
    if os.path.commonpath((root, target)) != root:
        report["reason"] = "database_outside_volume"
        return report
    if not os.path.isfile(target):
        report["reason"] = "database_not_found"
        return report
    report["database_exists"] = True
    try:
        uri = "file:" + target + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=3) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            required = {"predictions", "outcomes", "fixture_starts", "fixture_provenance"}
            if not required.issubset(tables):
                report["reason"] = "ledger_tables_missing"
                return report
            report["prediction_count"] = db.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
            report["outcome_count"] = db.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]
            report["espn_provenance_count"] = db.execute(
                "SELECT COUNT(*) FROM fixture_provenance WHERE league='NBA' AND provider='ESPN'"
            ).fetchone()[0]
    except (sqlite3.Error, OSError, ValueError):
        report["reason"] = "ledger_read_error"
        return report
    report["status"] = "ready"
    return report


if __name__ == "__main__":
    path = os.getenv("PREDICTION_LEDGER_DB", "/data/prediction_ledger.sqlite")
    result = ledger_readiness(path)
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["status"] == "ready" else 2)
