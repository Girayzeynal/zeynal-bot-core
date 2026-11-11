"""Import ESPN completed NBA results for existing pregame ledger fixtures.

Run explicitly against a persistent SQLite volume; no schedule or background
execution is implied. Default dry-run never writes to the ledger.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from espn_final_parser import parse_espn_regulation_final
from espn_outcome_join import import_verified_espn_outcome

ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"


def eligible_espn_ids(path: str) -> list[str]:
    if not os.path.isfile(path):
        raise ValueError("ledger_not_found")
    uri = "file:" + os.path.abspath(path) + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"predictions", "fixture_provenance", "fixture_starts", "outcomes"}.issubset(tables):
            raise ValueError("ledger_tables_missing")
        rows = db.execute(
            """SELECT DISTINCT v.provider_fixture_id
               FROM fixture_provenance v
               JOIN fixture_starts f ON f.league=v.league AND f.fixture_id=v.fixture_id
               JOIN predictions p ON p.league=v.league AND p.fixture_id=v.fixture_id
               LEFT JOIN outcomes o ON o.league=v.league AND o.fixture_id=v.fixture_id
               WHERE v.league='NBA' AND v.provider='ESPN'
                 AND v.start_ts_utc=f.start_ts_utc
                 AND p.scope='REGULATION_ONLY'
                 AND p.prediction_ts_utc<f.start_ts_utc
                 AND o.fixture_id IS NULL
                 AND v.provider_fixture_id != ''
               ORDER BY v.provider_fixture_id"""
        ).fetchall()
    return [str(row[0]) for row in rows]


def fetch_espn_event(event_id: str) -> dict:
    if not event_id.isdigit() or len(event_id) > 20:
        raise ValueError("invalid_espn_event_id")
    request = Request(ESPN_SUMMARY + "?event=" + event_id, headers={"User-Agent": "zeynal-bot-core/1.0"})
    with urlopen(request, timeout=12) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError("invalid_espn_response")
    header = payload.get("header")
    competitions = header.get("competitions") if isinstance(header, dict) else None
    if not isinstance(competitions, list) or len(competitions) != 1:
        raise ValueError("missing_competition")
    competition = competitions[0]
    if not isinstance(competition, dict) or str(competition.get("id")) != event_id:
        raise ValueError("event_identity_mismatch")
    # ESPN summary header embeds competitors and game status at competition level.
    status = competition.get("status")
    if not isinstance(status, dict):
        raise ValueError("missing_status")
    return {"id": event_id, "status": status, "competitions": [competition]}


def run(path: str, apply: bool = False, limit: int = 20) -> dict:
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("invalid_limit")
    ids = eligible_espn_ids(path)[:limit]
    results = []
    for event_id in ids:
        try:
            event = fetch_espn_event(event_id)
            parsed = parse_espn_regulation_final(event)
            if parsed is None:
                results.append({"event_id": event_id, "status": "NOT_VERIFIED_FINAL"})
            elif apply:
                outcome = import_verified_espn_outcome(path, event, int(time.time()))
                results.append({"event_id": event_id, "status": outcome["status"]})
            else:
                results.append({"event_id": event_id, "status": "VERIFIED_DRY_RUN",
                                "regulation_home": parsed["home"], "regulation_away": parsed["away"]})
        except HTTPError as exc:
            results.append({"event_id": event_id, "status": "PROVIDER_ACCESS_DENIED" if exc.code == 403 else "PROVIDER_HTTP_ERROR", "http_status": exc.code})
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
            results.append({"event_id": event_id, "status": "ERROR", "error_type": type(exc).__name__})
    return {"mode": "apply" if apply else "dry_run", "scanned": len(results), "results": results}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database")
    parser.add_argument("--apply", action="store_true", help="Write verified results; default dry-run")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)
    try:
        report = run(args.database, args.apply, args.limit)
    except (ValueError, sqlite3.Error, OSError) as exc:
        print(json.dumps({"status": "error", "error_type": type(exc).__name__, "reason": str(exc)}))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
