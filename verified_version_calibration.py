"""Read-only, provenance-gated calibration of immutable prediction versions.

This report never updates forecasts, invents results, or treats post-tipoff
predictions as prematch observations.
"""
from __future__ import annotations

import os
import sqlite3


def version_calibration_report(db_path: str, league: str = "NBA") -> dict:
    if not os.path.isfile(db_path):
        return {"status": "unavailable", "reason": "ledger_not_found", "league": league}
    uri = "file:" + os.path.abspath(db_path) + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {"prediction_versions", "outcomes", "fixture_starts", "fixture_provenance"}
        if not required.issubset(tables):
            return {"status": "unavailable", "reason": "missing_tables", "league": league}
        rows = db.execute("""
            SELECT p.fixture_id, p.version_id, p.prediction_ts_utc,
                   p.expected_home, p.expected_away, p.scope,
                   o.result_ts_utc, o.actual_home, o.actual_away, o.scope,
                   f.start_ts_utc, v.start_ts_utc, v.provider, v.provider_fixture_id
            FROM prediction_versions p
            JOIN outcomes o ON o.league=p.league AND o.fixture_id=p.fixture_id
            JOIN fixture_starts f ON f.league=p.league AND f.fixture_id=p.fixture_id
            JOIN fixture_provenance v ON v.league=p.league AND v.fixture_id=p.fixture_id
            WHERE p.league=?
            ORDER BY p.fixture_id, p.version_id
        """, (league,)).fetchall()
    by_fixture = {}
    excluded = 0
    for (fixture, version, ts, home, away, pscope, result_ts, actual_home,
         actual_away, oscope, start, provider_start, provider, provider_id) in rows:
        if not (ts < start < result_ts and pscope == oscope and
                start == provider_start and provider == "ESPN" and
                isinstance(provider_id, str) and provider_id.strip()):
            excluded += 1
            continue
        error = abs((home + away) - (actual_home + actual_away))
        by_fixture.setdefault(fixture, []).append((version, error))
    if not by_fixture:
        return {"status": "no_verified_versions", "league": league,
                "verified_fixtures": 0, "verified_versions": 0,
                "excluded_versions": excluded, "metrics": None}
    first_errors = [versions[0][1] for versions in by_fixture.values()]
    last_errors = [versions[-1][1] for versions in by_fixture.values()]
    paired = [versions for versions in by_fixture.values() if len(versions) >= 2]
    return {
        "status": "evaluated", "league": league,
        "verified_fixtures": len(by_fixture),
        "verified_versions": sum(len(v) for v in by_fixture.values()),
        "excluded_versions": excluded,
        "paired_fixture_count": len(paired),
        "metrics": {
            "first_version_total_mae": sum(first_errors) / len(first_errors),
            "last_version_total_mae": sum(last_errors) / len(last_errors),
            "paired_first_total_mae": (
                sum(v[0][1] for v in paired) / len(paired) if paired else None),
            "paired_last_total_mae": (
                sum(v[-1][1] for v in paired) / len(paired) if paired else None),
        },
        "note": "Descriptive only; not a calibrated confidence score or proof of improvement.",
    }
