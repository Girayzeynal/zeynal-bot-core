"""Read-only audit of NBA pregame forecasts awaiting verified results.

This command never creates a database or alters prediction/outcome rows.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3


def pending_outcome_audit(path: str) -> dict:
    if not os.path.isfile(path):
        raise ValueError("ledger_not_found")
    uri = "file:" + os.path.abspath(path) + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"predictions", "outcomes", "fixture_starts", "fixture_provenance"}.issubset(tables):
            raise ValueError("ledger_tables_missing")
        rows = db.execute("""
            SELECT p.fixture_id, p.prediction_ts_utc, p.scope,
                   f.start_ts_utc, v.provider, v.provider_fixture_id,
                   v.start_ts_utc
            FROM predictions p
            LEFT JOIN outcomes o ON o.league=p.league AND o.fixture_id=p.fixture_id
            LEFT JOIN fixture_starts f ON f.league=p.league AND f.fixture_id=p.fixture_id
            LEFT JOIN fixture_provenance v ON v.league=p.league AND v.fixture_id=p.fixture_id
            WHERE p.league='NBA' AND o.fixture_id IS NULL
            ORDER BY p.fixture_id
        """).fetchall()
    report = {"pending": len(rows), "eligible_for_espn_sync": 0, "blocked": {}, "fixtures": []}
    for fixture, prediction_ts, scope, start, provider, provider_id, provenance_start in rows:
        if start is None:
            reason = "MISSING_START"
        elif prediction_ts >= start:
            reason = "NOT_PREGAME"
        elif scope != "REGULATION_ONLY":
            reason = "SCOPE_UNSUPPORTED"
        elif not provider or not provider_id:
            reason = "MISSING_PROVENANCE"
        elif provenance_start != start:
            reason = "START_CONFLICT"
        elif provider != "ESPN":
            reason = "NON_ESPN_PROVIDER"
        else:
            reason = "ELIGIBLE_ESPN"
            report["eligible_for_espn_sync"] += 1
        if reason != "ELIGIBLE_ESPN":
            report["blocked"][reason] = report["blocked"].get(reason, 0) + 1
        report["fixtures"].append({"fixture_id": fixture, "status": reason})
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(pending_outcome_audit(args.database), sort_keys=True))
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"status": "error", "reason": str(exc)}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
