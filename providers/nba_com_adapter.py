"""NBA.com historical box-score baseline candidate (fail closed).

NBA Stats endpoints may reject cloud-hosted requests; no fabricated data is used.
"""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger("zeynal-core.nbacom")
NBA_STATS = "https://stats.nba.com/stats/leaguegamefinder"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
}
# NBA.com team IDs are stable; names/abbreviations come from the NBA directory.
NBA_TEAMS = {
    "ATL": 1610612737, "BOS": 1610612738, "BKN": 1610612751,
    "CHA": 1610612766, "CHI": 1610612741, "CLE": 1610612739,
    "DAL": 1610612742, "DEN": 1610612743, "DET": 1610612765,
    "GS": 1610612744, "GSW": 1610612744, "HOU": 1610612745,
    "IND": 1610612754, "LAC": 1610612746, "LAL": 1610612747,
    "MEM": 1610612763, "MIA": 1610612748, "MIL": 1610612749,
    "MIN": 1610612750, "NO": 1610612740, "NOP": 1610612740,
    "NY": 1610612752, "NYK": 1610612752, "OKC": 1610612760,
    "ORL": 1610612753, "PHI": 1610612755, "PHX": 1610612756,
    "POR": 1610612757, "SAC": 1610612758, "SA": 1610612759,
    "SAS": 1610612759, "TOR": 1610612761, "UTAH": 1610612762,
    "UTA": 1610612762, "WAS": 1610612764,
}


class NBAComAdapter:
    def __init__(self, session: Optional[aiohttp.ClientSession] = None) -> None:
        self._session = session
        self._owns_session = session is None

    async def aclose(self) -> None:
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    async def fetch_team_recent_games(
        self, league: str, team: str, n_games: int
    ) -> Optional[List[Dict[str, Any]]]:
        if not isinstance(league, str) or not isinstance(team, str) or type(n_games) is not int or league.strip().upper() != "NBA" or not 1 <= n_games <= 20:
            return None
        team_id = NBA_TEAMS.get(team.strip().upper())
        if team_id is None:
            return None
        now = datetime.now(timezone.utc)
        season = now.year if now.month >= 10 else now.year - 1
        rows: Dict[str, Dict[str, Any]] = {}
        conflicting_ids: set[str] = set()
        diagnostics = {"http_error": 0, "request_error": 0,
                       "schema_error": 0, "valid_response": 0, "candidate_rows": 0}
        for year in (season, season - 1):
            params = {
                "LeagueID": "00", "PlayerOrTeam": "T",
                "Season": f"{year}-{str(year+1)[-2:]}",
                "SeasonType": "Regular Season", "TeamID": str(team_id),
                "Sorter": "DATE", "Direction": "DESC",
            }
            try:
                if self._session is None or self._session.closed:
                    self._session = aiohttp.ClientSession(
                        timeout=aiohttp.ClientTimeout(total=12), headers=HEADERS
                    )
                    self._owns_session = True
                async with self._session.get(NBA_STATS, params=params) as response:
                    if response.status != 200:
                        diagnostics["http_error"] += 1
                        logger.info("[NBACOM-DIAG] season=%s status=%d", year, response.status)
                        continue
                    payload = await response.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
                diagnostics["request_error"] += 1
                category = "timeout" if isinstance(exc, asyncio.TimeoutError) else (
                    "transport" if isinstance(exc, aiohttp.ClientError) else "response_parse"
                )
                diagnostics[category] = diagnostics.get(category, 0) + 1
                logger.info("[NBACOM-DIAG] season=%s request_failed=%s", year, category)
                continue
            if not isinstance(payload, dict):
                diagnostics["schema_error"] += 1
                continue
            diagnostics["valid_response"] += 1
            result_sets = payload.get("resultSets") or []
            if isinstance(result_sets, dict):
                result_sets = list(result_sets.values())
            if not isinstance(result_sets, list):
                continue
            for result in result_sets:
                if not isinstance(result, dict):
                    continue
                headers = result.get("headers") or []
                needed = {"TEAM_ID", "GAME_ID", "GAME_DATE", "MATCHUP", "PTS", "PLUS_MINUS", "WL"}
                if not isinstance(headers, list) or not needed.issubset(set(headers)):
                    diagnostics["schema_error"] += 1
                    continue
                idx = {key: headers.index(key) for key in needed}
                for row in result.get("rowSet") or []:
                    try:
                        if int(row[idx["TEAM_ID"]]) != team_id:
                            continue
                        game_id = str(row[idx["GAME_ID"]])
                        date = datetime.strptime(str(row[idx["GAME_DATE"]])[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                        # Game date is not a precise tip-off timestamp. Avoid using
                        # midnight as provenance for a same-day fixture.
                        if date.date() >= now.date() or not game_id.isdigit():
                            continue
                        pts = float(row[idx["PTS"]])
                        margin = float(row[idx["PLUS_MINUS"]])
                        against = pts - margin
                        if not all(map(math.isfinite, (pts, margin, against))):
                            continue
                        if pts < 0 or against < 0 or pts == against or row[idx["WL"]] not in ("W", "L") or (pts > against) != (row[idx["WL"]] == "W"):
                            continue
                        matchup = str(row[idx["MATCHUP"]])
                        if " vs. " in matchup:
                            home = True
                        elif " @ " in matchup:
                            home = False
                        else:
                            continue
                        record = {
                            "ts_utc": int(date.timestamp()),
                            "pts_for": pts, "pts_against": against,
                            "pace": None, "home": home,  # Possessions not supplied by this endpoint.
                            "game_id": game_id, "source": "nba_com",
                        }
                        if game_id in conflicting_ids:
                            continue
                        if game_id in rows and rows[game_id] != record:
                            conflicting_ids.add(game_id)
                            rows.pop(game_id, None)
                            continue
                        rows[game_id] = record
                        diagnostics["candidate_rows"] += 1
                    except (IndexError, KeyError, TypeError, ValueError):
                        continue
            if len(rows) >= n_games:
                break
        selected = sorted(rows.values(), key=lambda x: x["ts_utc"])[-n_games:]
        logger.info("[NBACOM-DIAG] team=%s candidate_games=%d diagnostics=%s", team, len(selected), diagnostics)
        return selected or None
