"""Archive official EuroLeague / EuroCup season feeds without API-Sports keys.

Retains source JSON and provenance even if provider schema changes. Only games
with explicit played/result status and integer final scores enter games table.
"""
import asyncio
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import aiohttp

COMPETITIONS = {"EuroLeague": "E", "EuroCup": "U"}
BASE = "https://api-live.euroleague.net/v2/competitions"
DB = "data/archive/europe_official_2026_27.sqlite"


def score_from_side(side):
    if not isinstance(side, dict):
        return None
    for key in ("score", "points", "totalScore"):
        v = side.get(key)
        if type(v) is int and v >= 0:
            return v
    return None


def parse_completed(item):
    if not isinstance(item, dict):
        return None
    if item.get("played") is not True and str(item.get("gameStatus", "")).lower() not in ("result", "finished", "final"):
        return None
    home = item.get("local") or item.get("home")
    away = item.get("road") or item.get("away")
    h, a = score_from_side(home), score_from_side(away)
    if h is None or a is None or h == a:
        return None
    code = item.get("gameCode") or item.get("game_code")
    if code is None:
        return None
    when = item.get("utcDate") or item.get("utc_date")
    if not isinstance(when, str):
        return None
    try:
        dt = datetime.fromisoformat(when.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return None
        ts = int(dt.timestamp())
    except ValueError:
        return None
    def team_id(side):
        if not isinstance(side, dict):
            return None
        for key in ("code", "clubCode", "id", "name"):
            if side.get(key):
                return str(side[key])
        return None
    hid, aid = team_id(home), team_id(away)
    if not hid or not aid or hid == aid:
        return None
    return str(code), ts, hid, aid, h, a


async def run(db_path=DB):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    observed = int(datetime.now(timezone.utc).timestamp())
    timeout = aiohttp.ClientTimeout(total=45)
    counts = {}
    async with aiohttp.ClientSession(timeout=timeout) as session:
        with sqlite3.connect(db_path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS source_snapshots (
                  league TEXT PRIMARY KEY, url TEXT NOT NULL,
                  sha256 TEXT NOT NULL, observed_ts_utc INTEGER NOT NULL,
                  response_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS games (
                  league TEXT NOT NULL, provider TEXT NOT NULL,
                  fixture_id TEXT NOT NULL, start_ts_utc INTEGER NOT NULL,
                  home_team_id TEXT NOT NULL, away_team_id TEXT NOT NULL,
                  home_score INTEGER NOT NULL, away_score INTEGER NOT NULL,
                  observed_ts_utc INTEGER NOT NULL,
                  PRIMARY KEY (league,provider,fixture_id));
            """)
            for league, code in COMPETITIONS.items():
                url = f"{BASE}/{code}/seasons/{code}2026/games"
                async with session.get(url) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"{league}: official feed HTTP {resp.status}")
                    raw = await resp.read()
                payload = json.loads(raw)
                if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                    raise RuntimeError(f"{league}: unexpected official response shape")
                rows = payload["data"]
                if not rows:
                    raise RuntimeError(f"{league}: empty season feed, not archived")
                digest = hashlib.sha256(raw).hexdigest()
                # Diagnose schema drift without treating unparsed rows as finals.
                from collections import Counter
                diagnostics = {
                    "sample_field_names": sorted({
                        key for item in rows[:5] if isinstance(item, dict)
                        for key in item.keys()
                    })[:60],
                    "played_true": sum(isinstance(item, dict) and item.get("played") is True
                                       for item in rows),
                    "status_values": dict(Counter(
                        str(item.get("gameStatus", "<missing>"))
                        for item in rows if isinstance(item, dict)
                    ).most_common(12)),
                    "parseable_finals": sum(parse_completed(item) is not None for item in rows),
                }
                print(json.dumps({"league": league, "diagnostics": diagnostics}, sort_keys=True))
                # Aggregate rejection causes; never expose raw athlete/team records in CI logs.
                rejected = {"not_played": 0, "missing_team_side": 0,
                            "missing_side_score": 0, "tied_score": 0,
                            "missing_game_code": 0, "missing_utc_date": 0,
                            "missing_team_identity": 0}
                for item in rows:
                    if not isinstance(item, dict):
                        rejected["not_played"] += 1
                        continue
                    if item.get("played") is not True and str(item.get("gameStatus", "")).lower() not in ("result", "finished", "final"):
                        rejected["not_played"] += 1
                        continue
                    home, away = item.get("local") or item.get("home"), item.get("road") or item.get("away")
                    if not isinstance(home, dict) or not isinstance(away, dict):
                        rejected["missing_team_side"] += 1
                        continue
                    hs, aas = score_from_side(home), score_from_side(away)
                    if hs is None or aas is None:
                        rejected["missing_side_score"] += 1
                        continue
                    if hs == aas:
                        rejected["tied_score"] += 1
                        continue
                    if item.get("gameCode") is None and item.get("game_code") is None:
                        rejected["missing_game_code"] += 1
                        continue
                    if not isinstance(item.get("utcDate") or item.get("utc_date"), str):
                        rejected["missing_utc_date"] += 1
                        continue
                    if parse_completed(item) is None:
                        rejected["missing_team_identity"] += 1
                print(json.dumps({"league": league, "rejection_counts": rejected}, sort_keys=True))
                with db:
                    db.execute("INSERT OR REPLACE INTO source_snapshots VALUES (?,?,?,?,?)",
                               (league, url, digest, observed, raw.decode("utf-8")))
                    for item in rows:
                        parsed = parse_completed(item)
                        if parsed is None:
                            continue
                        game_id, ts, hid, aid, hs, aas = parsed
                        old = db.execute(
                            "SELECT start_ts_utc,home_team_id,away_team_id,home_score,away_score "
                            "FROM games WHERE league=? AND provider='EUROLEAGUE_OFFICIAL' AND fixture_id=?",
                            (league, game_id)).fetchone()
                        if old and old != (ts, hid, aid, hs, aas):
                            raise RuntimeError(f"{league}: conflicting historical result {game_id}")
                        db.execute("INSERT OR IGNORE INTO games VALUES (?,?,?,?,?,?,?,?,?)",
                                   (league, "EUROLEAGUE_OFFICIAL", game_id, ts, hid, aid, hs, aas, observed))
                count = db.execute("SELECT count(*) FROM games WHERE league=?", (league,)).fetchone()[0]
                counts[league] = {"games": count, "source_rows": len(rows), "sha256": digest}
                print(f"{league}: ARCHIVED_GAMES={count} SOURCE_ROWS={len(rows)} SHA256={digest}")
    print(json.dumps(counts))
    if not all(x["games"] > 0 for x in counts.values()):
        raise RuntimeError("At least one league has zero validated final-score rows; inspect saved source snapshots")


if __name__ == "__main__":
    asyncio.run(run())
