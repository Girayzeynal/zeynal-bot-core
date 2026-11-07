"""Optional independent NBA official scoreboard evidence collection.

Separate provider evidence, no mutation of canonical ESPN games. NBA Stats
may rate-limit GitHub runners; unavailable evidence is reported, not invented.
"""
import asyncio
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import aiohttp

ESPN_DB = "data/archive/nba_2026_27.sqlite"
OUT_DB = "data/archive/nba_official_crosscheck_2026_27.sqlite"
URL = "https://stats.nba.com/stats/scoreboardv3"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
}


def parse_final(game):
    if not isinstance(game, dict) or game.get("gameStatus") != 3:
        return None
    home, away = game.get("homeTeam"), game.get("awayTeam")
    if not isinstance(home, dict) or not isinstance(away, dict):
        return None
    hs, aas = home.get("score"), away.get("score")
    if type(hs) is not int or type(aas) is not int or hs < 0 or aas < 0 or hs == aas:
        return None
    game_id = str(game.get("gameId", ""))
    if not game_id.isdigit():
        return None
    ht, at = home.get("teamId"), away.get("teamId")
    if not ht or not at or ht == at:
        return None
    return game_id, str(ht), str(at), hs, aas


async def run():
    if not Path(ESPN_DB).exists():
        raise RuntimeError("ESPN archive not found; cannot determine archived dates")
    with sqlite3.connect(ESPN_DB) as source:
        dates = [x[0] for x in source.execute("SELECT day FROM scan_days ORDER BY day")]
    if not dates:
        raise RuntimeError("No ESPN scan days available")
    Path(OUT_DB).parent.mkdir(parents=True, exist_ok=True)
    observed = int(datetime.now(timezone.utc).timestamp())
    timeout = aiohttp.ClientTimeout(total=12)
    failures = []
    fetched_days = 0
    fetched_final_games = 0
    with sqlite3.connect(OUT_DB) as db:
        db.executescript("""
          CREATE TABLE IF NOT EXISTS official_games(
            game_id TEXT PRIMARY KEY, game_day TEXT NOT NULL,
            home_team_id TEXT NOT NULL, away_team_id TEXT NOT NULL,
            home_score INTEGER NOT NULL, away_score INTEGER NOT NULL,
            observed_ts_utc INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS snapshots(
            game_day TEXT PRIMARY KEY, url TEXT NOT NULL, sha256 TEXT NOT NULL,
            observed_ts_utc INTEGER NOT NULL, raw_json TEXT NOT NULL);
        """)
        async with aiohttp.ClientSession(timeout=timeout, headers=HEADERS) as session:
            # A bounded recent-date check avoids hundreds of NBA Stats calls.
            for day in dates[-7:]:
                params = {"GameDate": day, "LeagueID": "00"}
                try:
                    async with session.get(URL, params=params) as response:
                        if response.status != 200:
                            raise RuntimeError(f"HTTP {response.status}")
                        raw = await response.read()
                    data = json.loads(raw)
                    games = data.get("scoreboard", {}).get("games")
                    if not isinstance(games, list):
                        raise RuntimeError("Invalid official scoreboard schema")
                    digest = hashlib.sha256(raw).hexdigest()
                    current_finals = [parsed for item in games if (parsed := parse_final(item))]
                    fetched_days += 1
                    fetched_final_games += len(current_finals)
                    with db:
                        db.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?)",
                                   (day, str(response.url), digest, observed, raw.decode("utf-8")))
                        for parsed in current_finals:
                            db.execute("INSERT OR REPLACE INTO official_games VALUES (?,?,?,?,?,?,?)",
                                       (parsed[0], day, *parsed[1:], observed))
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, RuntimeError) as exc:
                    failures.append({"day": day, "error": str(exc)})
                await asyncio.sleep(0.25)
        count = db.execute("SELECT count(*) FROM official_games").fetchone()[0]
        status = ("SOURCE_FETCHED_NOT_CROSSCHECKED"
                  if fetched_days and fetched_final_games and not failures
                  else "PARTIAL_OR_UNAVAILABLE")
        print(json.dumps({
            "official_games_stored": count,
            "official_games_fetched_this_run": fetched_final_games,
            "days_fetched_this_run": fetched_days,
            "attempted_days": len(dates[-7:]),
            "failures": failures,
            "status": status,
            "score_comparison": "NOT_IMPLEMENTED",
        }))
        if not fetched_final_games:
            raise RuntimeError(
                "No fresh official NBA final results retrieved in this run; "
                "historical SQLite rows cannot establish current success"
            )


if __name__ == "__main__":
    asyncio.run(run())
