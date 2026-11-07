"""Archive API-Sports completed basketball games; never fabricate missing scores.

Explicit league/date window only. Requires existing API_SPORTS_KEY. A provider
quota/error aborts the scan and never marks the day as complete.
"""
import argparse
import asyncio
import json
import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import aiohttp

LEAGUES = {"EuroLeague": 120, "EuroCup": 194}
SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
 league TEXT NOT NULL, provider TEXT NOT NULL, fixture_id TEXT NOT NULL,
 start_ts_utc INTEGER NOT NULL, home_team_id TEXT NOT NULL,
 away_team_id TEXT NOT NULL, home_score INTEGER NOT NULL, away_score INTEGER NOT NULL,
 status TEXT NOT NULL, observed_ts_utc INTEGER NOT NULL,
 PRIMARY KEY(league,provider,fixture_id)
);
CREATE TABLE IF NOT EXISTS scan_days (
 league TEXT NOT NULL, day TEXT NOT NULL, observed_ts_utc INTEGER NOT NULL,
 completed_count INTEGER NOT NULL, PRIMARY KEY(league,day)
);
"""


def parse_game(raw, league_id):
    if not isinstance(raw, dict) or not isinstance(raw.get("league"), dict):
        return None
    if str(raw["league"].get("id")) != str(league_id) or raw["league"].get("season") != "2026-2027":
        return None
    status = raw.get("status") or {}
    if not isinstance(status, dict) or status.get("short") not in ("FT", "AOT"):
        return None
    teams, scores = raw.get("teams"), raw.get("scores")
    if not isinstance(teams, dict) or not isinstance(scores, dict):
        return None
    try:
        game_id = str(raw["id"])
        start = datetime.fromisoformat(raw["date"].replace("Z", "+00:00"))
        if start.tzinfo is None:
            return None
        home, away = teams["home"], teams["away"]
        home_id, away_id = str(home["id"]), str(away["id"])
        h, a = scores["home"]["total"], scores["away"]["total"]
        if (not game_id.isascii() or not game_id.isdigit()
                or not home_id.isdigit() or not away_id.isdigit()
                or home_id == away_id or type(h) is not int or type(a) is not int
                or h < 0 or a < 0 or h == a):
            return None
        return (game_id, int(start.timestamp()), home_id, away_id, h, a, status["short"])
    except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
        return None


def persist(db, league, day, games, observed):
    seen = set()
    with db:
        for g in games:
            if g[0] in seen:
                raise ValueError("duplicate fixture in provider response")
            seen.add(g[0])
            old = db.execute("SELECT start_ts_utc,home_team_id,away_team_id,home_score,away_score,status "
                             "FROM games WHERE league=? AND provider='API-SPORTS' AND fixture_id=?",
                             (league, g[0])).fetchone()
            if old is not None and old != g[1:]:
                raise ValueError("conflicting historical game: " + g[0])
            db.execute("INSERT OR IGNORE INTO games VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (league, "API-SPORTS", *g[:6], g[6], observed))
        db.execute("INSERT OR REPLACE INTO scan_days VALUES (?,?,?,?)",
                   (league, day, observed, len(games)))


async def backfill(database, leagues, start, end):
    key = os.environ.get("API_SPORTS_KEY")
    if not key:
        raise RuntimeError("API_SPORTS_KEY missing; no API calls made")
    if start < date(2026, 9, 1) or end > date(2027, 8, 1) or start >= end:
        raise ValueError("invalid 2026/27 date window")
    Path(database).parent.mkdir(parents=True, exist_ok=True)
    timeout = aiohttp.ClientTimeout(total=25)
    async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
        with sqlite3.connect(database) as db:
            db.executescript(SCHEMA)
            for league in leagues:
                day = start
                while day < end:
                    async with session.get(
                        os.environ.get("API_SPORTS_BASE", "https://v1.basketball.api-sports.io").rstrip("/") + "/games",
                        headers={"x-apisports-key": key},
                        params={"league": LEAGUES[league], "date": day.isoformat(), "timezone": "UTC"},
                    ) as response:
                        if response.status != 200:
                            raise RuntimeError(f"{league} {day}: HTTP {response.status}")
                        payload = await response.json()
                    if (not isinstance(payload, dict) or payload.get("errors")
                            or not isinstance(payload.get("response"), list)):
                        raise RuntimeError(f"{league} {day}: provider error/quota/malformed response")
                    rows = [parse_game(raw, LEAGUES[league]) for raw in payload["response"]]
                    completed = [r for r in rows if r is not None]
                    persist(db, league, day.isoformat(), completed, int(datetime.now(timezone.utc).timestamp()))
                    day += timedelta(days=1)
            return {
                league: {
                    "games": db.execute("SELECT COUNT(*) FROM games WHERE league=?", (league,)).fetchone()[0],
                    "days": db.execute("SELECT COUNT(*) FROM scan_days WHERE league=?", (league,)).fetchone()[0],
                } for league in leagues
            }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="data/archive/europe_2026_27.sqlite")
    parser.add_argument("--leagues", nargs="+", choices=sorted(LEAGUES), default=["EuroLeague", "EuroCup"])
    parser.add_argument("--start", default="2026-09-01")
    parser.add_argument("--end", default=min(date.today() + timedelta(days=1), date(2027, 8, 1)).isoformat())
    args = parser.parse_args()
    try:
        result = asyncio.run(backfill(args.database, args.leagues, date.fromisoformat(args.start), date.fromisoformat(args.end)))
        print(json.dumps({"status": "COMPLETED", "archive": result}))
    except Exception as exc:
        print(json.dumps({"status": "FAILED", "reason": str(exc)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
