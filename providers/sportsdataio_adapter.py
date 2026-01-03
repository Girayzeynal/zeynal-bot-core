from __future__ import annotations

import asyncio
import json
import os
import re
import time
import calendar
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import aiohttp


SPORTSDATA_BASE = "https://api.sportsdata.io/v3/nba/scores/json"


# =====================================================
# CACHE
# =====================================================

@dataclass
class _CacheEntry:
    ts: float
    value: Any


class _TTLCache:
    def __init__(self, ttl_sec: int) -> None:
        self.ttl_sec = int(ttl_sec)
        self._data: Dict[str, _CacheEntry] = {}

    def get(self, key: str) -> Any:
        ent = self._data.get(key)
        if not ent:
            return None
        if (time.time() - ent.ts) > self.ttl_sec:
            self._data.pop(key, None)
            return None
        return ent.value

    def set(self, key: str, value: Any) -> None:
        self._data[key] = _CacheEntry(time.time(), value)


# =====================================================
# SPORTS DATA IO ADAPTER
# =====================================================

class SportsDataIOAdapter:
    """
    SportsDataIO provider adapter.

    - Provides REAL possessions-based pace
    - Provides per-game time-series in UTC
    - Acts as authoritative override for pace vs ESPN proxy
    """

    name = "SPORTSDATAIO"
    confidence = 0.85

    def __init__(self, session: Optional[aiohttp.ClientSession] = None) -> None:
        self.api_key = (os.getenv("SPORTSDATA_API_KEY") or "").strip()
        self._session: Optional[aiohttp.ClientSession] = session
        self._owns_session: bool = session is None

        self._cache = _TTLCache(
            ttl_sec=int(os.getenv("SPORTSDATA_CACHE_TTL_SEC", "900"))
        )

        self._disk_cache_dir = (os.getenv("FAZ_CACHE_DIR") or "").strip()

    # -------------------------------------------------
    # HTTP
    # -------------------------------------------------

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session and not self._session.closed:
            return self._session
        timeout = aiohttp.ClientTimeout(total=25)
        self._session = aiohttp.ClientSession(timeout=timeout)
        self._owns_session = True
        return self._session

    async def aclose(self) -> None:
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    async def close(self) -> None:  # backward compat
        await self.aclose()

    async def _request_json(self, url: str) -> Optional[Any]:
        if not self.api_key:
            return None

        cache_key = f"json:{url}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        disk_key = None
        if self._disk_cache_dir:
            safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", cache_key)[:180]
            disk_key = os.path.join(self._disk_cache_dir, f"{safe}.json")

            try:
                if os.path.exists(disk_key):
                    if (time.time() - os.path.getmtime(disk_key)) <= self._cache.ttl_sec:
                        with open(disk_key, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        self._cache.set(cache_key, data)
                        return data
            except Exception:
                pass

        headers = {"Ocp-Apim-Subscription-Key": self.api_key}
        backoff = 0.7

        for _ in range(4):
            try:
                s = await self._get_session()
                async with s.get(url, headers=headers) as resp:
                    if resp.status in (429, 503, 502, 504):
                        await asyncio.sleep(backoff)
                        backoff *= 1.7
                        continue
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    self._cache.set(cache_key, data)

                    if disk_key:
                        try:
                            os.makedirs(self._disk_cache_dir, exist_ok=True)
                            with open(disk_key, "w", encoding="utf-8") as f:
                                json.dump(data, f)
                        except Exception:
                            pass

                    return data
            except Exception:
                await asyncio.sleep(backoff)
                backoff *= 1.7

        return None

    # -------------------------------------------------
    # TEAM BASELINE (snapshot)
    # -------------------------------------------------

    async def fetch_team_baseline(
        self, team_key: str, season_year: str
    ) -> Optional[Dict[str, Any]]:
        if not self.api_key:
            return None

        key = (team_key or "").upper().strip()
        if not key:
            return None

        url = f"{SPORTSDATA_BASE}/TeamSeasonStats/{season_year}"
        data = await self._request_json(url)
        if not isinstance(data, list):
            return None

        row = next((x for x in data if str(x.get("Key", "")).upper() == key), None)
        if not row:
            return None

        pf = row.get("PointsPerGame")
        pa = row.get("OpponentPointsPerGame")
        if pf is None or pa is None:
            return None

        return {
            "pts_for": float(pf),
            "pts_against": float(pa),
            "confidence": float(self.confidence),
            "source": self.name,
            "fetched_at": int(time.time()),
        }

    # -------------------------------------------------
    # REAL PACE (possessions-based)
    # -------------------------------------------------

    async def fetch_team_pace(
        self, team_key: str, season_year: str
    ) -> Optional[Dict[str, Any]]:
        if not self.api_key:
            return None

        key = (team_key or "").upper().strip()
        if not key:
            return None

        url = f"{SPORTSDATA_BASE}/TeamSeasonStats/{season_year}"
        data = await self._request_json(url)
        if not isinstance(data, list):
            return None

        row = next((x for x in data if str(x.get("Key", "")).upper() == key), None)
        if not row:
            return None

        poss = row.get("Possessions")
        games = row.get("Games")
        if poss is None or games is None:
            return None

        try:
            poss_f = float(poss)
            games_i = int(games)
        except Exception:
            return None

        if games_i <= 0:
            return None

        return {
            "source": self.name,
            "team_key": key,
            "pace": poss_f / games_i,
            "possessions": poss_f,
            "games": games_i,
            "fetched_at": int(time.time()),
        }

    # -------------------------------------------------
    # RECENT GAMES (time-series, UTC)  ✅ NEW
    # -------------------------------------------------

    async def fetch_team_recent_games(
        self, league: str, team_key: str, n_games: int
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Returns per-game series with REAL possessions when possible.

        {
          "ts_utc": int,
          "pts_for": float,
          "pts_against": float,
          "pace": float,
          "home": bool
        }
        """
        if not self.api_key:
            return None

        key = (team_key or "").upper().strip()
        if not key:
            return None

        # Use Games endpoint for completed games
        # Date range: last ~45 days is safe for n<=15
        end_ts = int(time.time())
        start_ts = end_ts - 60 * 24 * 3600
        start_date = time.strftime("%Y-%m-%d", time.gmtime(start_ts))
        end_date = time.strftime("%Y-%m-%d", time.gmtime(end_ts))

        url = f"{SPORTSDATA_BASE}/Games/{start_date}/{end_date}"
        games = await self._request_json(url)
        if not isinstance(games, list):
            return None

        out: List[Dict[str, Any]] = []

        for g in sorted(games, key=lambda x: x.get("DateTime", "")):
            if len(out) >= int(n_games):
                break

            # Only finished games
            if g.get("Status") not in ("Final", "F/OT"):
                continue

            home = g.get("HomeTeam")
            away = g.get("AwayTeam")
            if home != key and away != key:
                continue

            # Parse UTC time
            dt = g.get("DateTime")
            if not isinstance(dt, str):
                continue

            try:
                # Example: 2026-01-03T03:00:00
                t = time.strptime(dt.split(".")[0], "%Y-%m-%dT%H:%M:%S")
                ts_utc = calendar.timegm(t)
            except Exception:
                continue

            if home == key:
                pf = g.get("HomeTeamScore")
                pa = g.get("AwayTeamScore")
                is_home = True
            else:
                pf = g.get("AwayTeamScore")
                pa = g.get("HomeTeamScore")
                is_home = False

            if pf is None or pa is None:
                continue

            poss = g.get("Possessions")
            if poss:
                try:
                    pace = float(poss)
                except Exception:
                    pace = None
            else:
                pace = None

            out.append(
                {
                    "ts_utc": int(ts_utc),
                    "pts_for": float(pf),
                    "pts_against": float(pa),
                    "pace": float(pace) if pace is not None else None,
                    "home": bool(is_home),
                }
            )

        return out if out else None

    # -------------------------------------------------
    # INJURIES
    # -------------------------------------------------

    async def fetch_team_injuries(self, team_key: str) -> Optional[Dict[str, Any]]:
        if not self.api_key:
            return None

        key = (team_key or "").upper().strip()
        if not key:
            return None

        url = f"{SPORTSDATA_BASE}/Players/{key}"
        data = await self._request_json(url)
        if not isinstance(data, list):
            return None

        injuries: List[Dict[str, Any]] = []
        for p in data:
            status = p.get("InjuryStatus")
            notes = p.get("InjuryNotes")
            body = p.get("InjuryBodyPart")
            start = p.get("InjuryStartDate")

            if status or notes or body or start:
                injuries.append(
                    {
                        "player_id": p.get("PlayerID"),
                        "name": f"{p.get('FirstName','')} {p.get('LastName','')}".strip(),
                        "status": status,
                        "body_part": body,
                        "notes": notes,
                        "position": p.get("Position"),
                    }
                )

        return {
            "source": self.name,
            "team_key": key,
            "injuries": injuries,
            "injury_count": len(injuries),
            "fetched_at": int(time.time()),
        }
