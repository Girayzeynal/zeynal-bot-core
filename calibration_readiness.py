"""Read-only audit of whether the production ledger can support calibration."""
from __future__ import annotations

import os
import sqlite3


def audit_calibration_readiness(db_path: str, league: str = "NBA") -> dict:
    if not os.path.isfile(db_path):
        return {"status": "blocked", "reason": "ledger_not_found", "league": league}
    uri = "file:" + os.path.abspath(db_path) + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {"prediction_versions", "outcomes", "fixture_starts", "fixture_provenance"}
        missing = sorted(required - tables)
        if missing:
            return {"status": "blocked", "reason": "missing_tables",
                    "missing_tables": missing, "league": league}
        counts = {}
        for table in sorted(required):
            counts[table] = db.execute(
                f"SELECT COUNT(*) FROM {table} WHERE league=?", (league,)
            ).fetchone()[0]
        verified = db.execute("""
            SELECT COUNT(*)
            FROM prediction_versions p
            JOIN outcomes o ON o.league=p.league AND o.fixture_id=p.fixture_id
            JOIN fixture_starts f ON f.league=p.league AND f.fixture_id=p.fixture_id
            JOIN fixture_provenance v ON v.league=p.league AND v.fixture_id=p.fixture_id
            WHERE p.league=? AND p.prediction_ts_utc < f.start_ts_utc
              AND f.start_ts_utc < o.result_ts_utc AND p.scope=o.scope
              AND v.start_ts_utc=f.start_ts_utc
              AND v.provider='ESPN' AND trim(v.provider_fixture_id)!=''
        """, (league,)).fetchone()[0]
    return {"status": "ready" if verified else "blocked",
            "reason": None if verified else "no_verified_prematch_pairs",
            "league": league, "counts": counts, "verified_versions": verified}
