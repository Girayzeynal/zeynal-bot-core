"""Backfill completed 2026/27 NBA scoreboard games into a separate SQLite archive.

Usage: python -m tools.archive_nba_2026_27 --database data/archive/nba_2026_27.sqlite
This is NOT the prospective prediction ledger. Network errors fail the run.
"""
import argparse
import asyncio
import json
import sqlite3
from datetime import date, timedelta, datetime, timezone
from pathlib import Path

from providers.espn_adapter import ESPNAdapter


START = date(2026, 10, 1)
END = date(2027, 7, 1)  # exclusive; season including playoffs
SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
 provider TEXT NOT NULL, fixture_id TEXT NOT NULL, season TEXT NOT NULL,
 start_ts_utc INTEGER NOT NULL, home_team_id TEXT NOT NULL,
 away_team_id TEXT NOT NULL, home_score INTEGER NOT NULL, away_score INTEGER NOT NULL,
 score_scope TEXT NOT NULL, source_observed_utc INTEGER NOT NULL,
 PRIMARY KEY (provider, fixture_id)
);
CREATE TABLE IF NOT EXISTS scan_days (
 day TEXT PRIMARY KEY, fetched_at_utc INTEGER NOT NULL, completed_count INTEGER NOT NULL
);
"""


def persist_day(db, day, games, observed):
    if not isinstance(games, list):
        raise ValueError("Invalid provider response")
    ids = set()
    for game in games:
        key = game["provider_fixture_id"]
        if key in ids:
            raise ValueError("Duplicate fixture on same date")
        ids.add(key)
    with db:
        for game in games:
            fields = (game["provider"], game["provider_fixture_id"], "2026/27",
                      game["start_ts_utc"], game["home_team_id"], game["away_team_id"],
                      game["actual_home"], game["actual_away"], game["scope"], observed)
            existing = db.execute(
                "SELECT start_ts_utc, home_team_id, away_team_id, home_score, away_score, score_scope "
                "FROM games WHERE provider=? AND fixture_id=?", fields[:2]).fetchone()
            if existing is not None and existing != (fields[3], fields[4], fields[5], fields[6], fields[7], fields[8]):
                raise ValueError("Conflicting previously archived result: " + str(fields[1]))
            db.execute("INSERT OR IGNORE INTO games VALUES (?,?,?,?,?,?,?,?,?,?)", fields)
        db.execute("INSERT OR REPLACE INTO scan_days VALUES (?,?,?)",
                   (day, observed, len(games)))


async def backfill(database, start, end):
    if start < START or end > END or start >= end:
        raise ValueError("Date window must fall inside 2026/27 season")
    Path(database).parent.mkdir(parents=True, exist_ok=True)
    adapter = ESPNAdapter()
    scanned = 0
    try:
        with sqlite3.connect(database) as db:
            db.executescript(SCHEMA)
            day = start
            while day < end:
                key = day.strftime("%Y%m%d")
                # Quality-report endpoint raises on missing/malformed HTTP responses;
                # an unavailable day must not be marked as an empty game day.
                result = await adapter.fetch_nba_scoreboard_quality_report(key)
                games = result["completed_events"]
                persist_day(db, day.isoformat(), games, result["observed_at_utc"])
                scanned += 1
                day += timedelta(days=1)
            return {"scanned_days": scanned,
                    "archived_games": db.execute("SELECT COUNT(*) FROM games").fetchone()[0],
                    "first_day": start.isoformat(), "last_day": (end-timedelta(days=1)).isoformat()}
    finally:
        await adapter.aclose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="data/archive/nba_2026_27.sqlite")
    parser.add_argument("--start", default=START.isoformat())
    parser.add_argument("--end", default=min(date.today()+timedelta(days=1), END).isoformat())
    args = parser.parse_args()
    try:
        result = asyncio.run(backfill(args.database, date.fromisoformat(args.start),
                                      date.fromisoformat(args.end)))
    except Exception as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}))
        return 1
    print(json.dumps({"status": "COMPLETED", **result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
