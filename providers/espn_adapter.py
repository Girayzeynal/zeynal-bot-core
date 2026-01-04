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

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"


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
# HELPERS
# =====================================================

def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().replace("-", " ").replace("_", " ").split())


def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


# =====================================================
# ESPN ADAPTER
# =====================================================

class ESPNAdapter:
    """
    ESPN provider adapter (NO API KEY).

    Rol:
    - Son maçlar (time-series, UTC)
    - Takım adı → kısaltma resolver
    - Analiz / karar YAPMAZ
    """

    name = "ESPN"
    confidence = 0.60

    def __init__(self, session: Optional[aiohttp.ClientSession] = None) -> None:
        self._session: Optional[aiohttp.ClientSession] = session
        self._owns_session: bool = session is None

        self._cache = _TTLCache(
            ttl_sec=int(os.getenv("ESPN_CACHE_TTL_SEC", "900"))
        )
        self._teams_cache = _TTLCache(
            ttl_sec=int(os.getenv("ESPN_TEAMS_TTL_SEC", "21600"))
        )

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

    async def close(self) -> None:
        await self.aclose()

    async def _request_json(
        self, url: str, params: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        cache_key = f"json:{url}:{json.dumps(params, sort_keys=True) if params else ''}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        backoff = 0.6
        for _ in range(4):
            try:
                s = await self._get_session()
                async with s.get(url, params=params) as resp:
                    if resp.status in (429, 503, 502, 504):
                        await asyncio.sleep(backoff)
                        backoff *= 1.7
                        continue
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    self._cache.set(cache_key, data)
                    return data
            except Exception:
                await asyncio.sleep(backoff)
                backoff *= 1.7

        return None

    # -------------------------------------------------
    # TEAM NAME → ABBR (bootstrapper kullanır)
    # -------------------------------------------------

    async def resolve_team_abbr(self, league: str, team_name: str) -> Optional[str]:
        key = _norm(team_name)
        if not key:
            return None

        cached = self._teams_cache.get("nba_team_dir")
        if cached is None:
            js = await self._request_json(f"{ESPN_BASE}/teams")
            if not js:
                return None
            cached = js
            self._teams_cache.set("nba_team_dir", cached)

        teams = (
            cached.get("sports", [{}])[0]
            .get("leagues", [{}])[0]
            .get("teams", [])
        )

        for t in teams:
            team = (t or {}).get("team") or {}
            abbr = str(team.get("abbreviation", "")).upper()
            if not abbr:
                continue

            candidates = [
                team.get("displayName"),
                team.get("shortDisplayName"),
                team.get("name"),
                team.get("location"),
                abbr,
            ]

            for c in candidates:
                if _norm(str(c)) == key:
                    return abbr

        return None

    # -------------------------------------------------
    # RECENT GAMES (UTC, CANONICAL)
    # -------------------------------------------------

    async def fetch_team_recent_games(
        self, league: str, team_abbr: str, n_games: int
    ) -> Optional[List[Dict[str, Any]]]:

        abbr = (team_abbr or "").strip().lower()
        if not abbr:
            return None

        js = await self._request_json(f"{ESPN_BASE}/teams/{abbr}/schedule")
        if not js:
            return None

        events = js.get("events")
        if not isinstance(events, list):
            return None

        out: List[Dict[str, Any]] = []

        for ev in reversed(events):
            if len(out) >= int(n_games):
                break

            comps = ev.get("competitions")
            if not comps:
                continue

            competitors = comps[0].get("competitors")
            if not competitors or len(competitors) < 2:
                continue

            team_row = None
            opp_row = None
            for c in competitors:
                ab = str(((c.get("team") or {}).get("abbreviation") or "")).lower()
                if ab == abbr:
                    team_row = c
                else:
                    opp_row = c

            if not team_row or not opp_row:
                continue

            pf = _safe_float(team_row.get("score"))
            pa = _safe_float(opp_row.get("score"))
            if pf is None or pa is None:
                continue

            is_home = str(team_row.get("homeAway") or "").lower() == "home"

            ts = ev.get("date")
            if not isinstance(ts, str):
                continue

            try:
                # ESPN date → UTC epoch (DOĞRU YOL)
                t = time.strptime(ts.replace("Z", ""), "%Y-%m-%dT%H:%M")
                ts_utc = int(calendar.timegm(t))
            except Exception:
                continue

            total = pf + pa
            pace_proxy = 99.5 + (total - 220.0) * 0.06
            pace_proxy = max(94.0, min(106.0, pace_proxy))

            out.append(
                {
                    "ts_utc": ts_utc,
                    "pts_for": pf,
                    "pts_against": pa,
                    "pace": pace_proxy,
                    "home": is_home,
                }
            )

        return out if out else None 
