"""Read-only ESPN date-scoped scoreboard baseline candidate.

Fail closed on any missing date, malformed response, or conflicting game ID.
No fabricated pace; the baseline schema requires a pace field, so this
adapter deliberately does not return baseline rows until real pace exists.
Use fetch_verified_games for historical score records and diagnostics.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import aiohttp

from providers.espn_completed_event import parse_completed_nba_event

BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"


class ESPNScoreboardHistory:
    def __init__(self, session: Optional[aiohttp.ClientSession] = None):
        self._session = session
        self._owns_session = session is None

    async def aclose(self):
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    async def _fetch_day(self, day: str) -> Optional[List[Dict[str, Any]]]:
        try:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=15))
                self._owns_session = True
            async with self._session.get(BASE, params={"dates": day}) as response:
                if response.status != 200:
                    return None
                payload = await response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
                return None
            return payload["events"]
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError):
            return None

    async def fetch_verified_games(
        self, team_id: str, *, as_of_utc: datetime,
        days: int = 21, minimum: int = 6,
    ) -> Optional[List[Dict[str, Any]]]:
        """Return verified final games before as_of_utc, or None on any uncertainty.

        team_id must be the ESPN numeric team ID, not an NBA.com team ID.
        The date window includes an extra UTC day to accommodate ESPN's
        scoreboard date boundaries; the timestamp cutoff remains authoritative.
        """
        if (not isinstance(team_id, str) or not team_id.isascii()
                or not team_id.isdigit() or not team_id
                or not isinstance(as_of_utc, datetime) or as_of_utc.tzinfo is None
                or type(days) is not int or not 1 <= days <= 45
                or type(minimum) is not int or not 1 <= minimum <= 30):
            return None
        cutoff = as_of_utc.astimezone(timezone.utc)
        rows: Dict[str, Dict[str, Any]] = {}
        conflicts: set[str] = set()
        # Never request the fixture date itself. A day-boundary overlap
        # covers UTC-vs-US-local scoreboard bucketing.
        for offset in range(1, days + 2):
            day = (cutoff.date() - timedelta(days=offset)).strftime("%Y%m%d")
            events = await self._fetch_day(day)
            if events is None:
                return None
            for raw in events:
                parsed = parse_completed_nba_event(raw, cutoff)
                if parsed is None or parsed["start_ts_utc"] >= cutoff.timestamp():
                    continue
                if team_id not in (parsed["home_team_id"], parsed["away_team_id"]):
                    continue
                key = parsed["provider_fixture_id"]
                if key in conflicts:
                    continue
                if key in rows and rows[key] != parsed:
                    conflicts.add(key)
                    rows.pop(key, None)
                else:
                    rows[key] = parsed
        selected = sorted(rows.values(), key=lambda r: (
            r["start_ts_utc"], r["provider_fixture_id"]))
        return selected if len(selected) >= minimum else None
