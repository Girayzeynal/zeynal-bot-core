from __future__ import annotations

import asyncio
import calendar
import time
from typing import Any, Dict, List, Optional

import aiohttp


ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"


class ESPNAdapter:
    """
    ESPN ADAPTER — PRODUCTION GRADE (FREE)

    - team_name / abbr -> team_id resolve (cache'li)
    - schedule fetch ONLY team_id ile
    - sadece COMPLETED maçlar
    - retry + backoff
    - TeamBaselineBootstrapper sözleşmesine %100 uyum
    """

    def __init__(self, session: Optional[aiohttp.ClientSession] = None) -> None:
        self._session = session
        self._owns_session = session is None
        self._teams_cache: Optional[List[Dict[str, Any]]] = None
        self._teams_cache_ts: float = 0.0
        self._teams_ttl = 6 * 3600  # 6 saat

    # -------------------------------------------------
    # SESSION
    # -------------------------------------------------
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session and not self._session.closed:
            return self._session
        timeout = aiohttp.ClientTimeout(total=20)
        self._session = aiohttp.ClientSession(timeout=timeout)
        self._owns_session = True
        return self._session

    async def aclose(self) -> None:
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    # -------------------------------------------------
    # HTTP (retry + backoff)
    # -------------------------------------------------
    async def _get_json(self, url: str) -> Optional[Dict[str, Any]]:
        backoff = 0.6
        for _ in range(3):
            try:
                s = await self._get_session()
                async with s.get(url) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    if resp.status in (429, 500, 502, 503):
                        await asyncio.sleep(backoff)
                        backoff *= 1.6
                        continue
                    return None
            except Exception:
                await asyncio.sleep(backoff)
                backoff *= 1.6
        return None

    # -------------------------------------------------
    # TEAM DIRECTORY (cache'li)
    # -------------------------------------------------
    async def _load_teams(self) -> Optional[List[Dict[str, Any]]]:
        now = time.time()
        if self._teams_cache and (now - self._teams_cache_ts) < self._teams_ttl:
            return self._teams_cache

        js = await self._get_json(f"{ESPN_BASE}/teams")
        if not js:
            return None

        try:
            teams = (
                js.get("sports", [{}])[0]
                .get("leagues", [{}])[0]
                .get("teams", [])
            )
            self._teams_cache = teams
            self._teams_cache_ts = now
            return teams
        except Exception:
            return None

    # -------------------------------------------------
    # RESOLVE TEAM -> ID / ABBR
    # -------------------------------------------------
    async def resolve_team(self, team_input: str) -> Optional[Dict[str, str]]:
        if not team_input:
            return None

        key = team_input.strip().lower()
        teams = await self._load_teams()
        if not teams:
            return None

        for t in teams:
            team = t.get("team", {})
            tid = team.get("id")
            abbr = str(team.get("abbreviation", "")).upper()
            name = str(team.get("displayName", "")).lower()
            short = str(team.get("shortDisplayName", "")).lower()

            if (
                key == abbr.lower()
                or key == name
                or key == short
                or key in name
            ):
                if tid:
                    return {
                        "id": str(tid),
                        "abbr": abbr,
                        "name": team.get("displayName"),
                    }

        return None

    # Bootstrapper uyumu için
    async def resolve_team_abbr(self, league: str, team_input: str) -> Optional[str]:
        ref = await self.resolve_team(team_input)
        return ref["abbr"] if ref else None

    # -------------------------------------------------
    # FETCH RECENT GAMES (PROD SAFE)
    # -------------------------------------------------
    async def fetch_team_recent_games(
        self, league: str, team: str, n_games: int
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Dönen format TeamBaselineBootstrapper ile uyumlu:
        {
            ts_utc, pts_for, pts_against, pace, home
        }
        """

        ref = await self.resolve_team(team)
        if not ref:
            return None

        team_id = ref["id"]
        url = f"{ESPN_BASE}/teams/{team_id}/schedule"

        js = await self._get_json(url)
        if not js:
            return None

        events = js.get("events")
        if not isinstance(events, list):
            return None

        # ---- ÖN ANALİZ DOĞRUSU ----
        # Tarihe bakmadan, sadece COMPLETED maçları topla,
        # en son oynanan N maçı al.
        completed: List[Dict[str, Any]] = []
        for ev in events:
            comps = ev.get("competitions") or []
            if not comps:
                continue
            comp = comps[0]
            if comp.get("status", {}).get("type", {}).get("state") != "completed":
                continue
            completed.append(ev)

        if not completed:
            return None

        completed = completed[-int(n_games):]

        out: List[Dict[str, Any]] = []
        for ev in completed:
            comps = ev.get("competitions") or []
            if not comps:
                continue

            comp = comps[0]
            competitors = comp.get("competitors") or []
            if len(competitors) != 2:
                continue

            team_row = None
            opp_row = None
            for c in competitors:
                ab = c.get("team", {}).get("abbreviation", "").upper()
                if ab == ref["abbr"]:
                    team_row = c
                else:
                    opp_row = c

            if not team_row or not opp_row:
                continue

            try:
                pf = float(team_row.get("score"))
                pa = float(opp_row.get("score"))
            except Exception:
                continue

            # ---- TARİH PARSE (saniyeli / saniyesiz) ----
            ts_raw = ev.get("date")
            try:
                ts = ts_raw.replace("Z", "")
                try:
                    t = time.strptime(ts, "%Y-%m-%dT%H:%M:%S")
                except ValueError:
                    t = time.strptime(ts, "%Y-%m-%dT%H:%M")
                ts_utc = int(calendar.timegm(t))
            except Exception:
                continue
            # --------------------------------------------

            total = pf + pa
            pace = max(94.0, min(106.0, 99.5 + (total - 220.0) * 0.06))

            out.append({
                "ts_utc": ts_utc,
                "pts_for": pf,
                "pts_against": pa,
                "pace": pace,
                "home": team_row.get("homeAway") == "home",
            })

        return out if out else None 
