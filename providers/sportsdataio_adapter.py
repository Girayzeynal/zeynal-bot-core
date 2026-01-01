# providers/sportsdataio_adapter.py

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import aiohttp


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


class SportsDataIOAdapter:
    """
    SportsDataIO provider.
    Secret:
      - SPORTSDATA_API_KEY
    Uses v3 NBA Scores API:
      - TeamSeasonStats/{season}
      - Players/{team}  (players by team; includes injury fields when available)
    """

    name = "SPORTSDATAIO"
    confidence = 0.85

    def __init__(self) -> None:
        self.key = os.getenv("SPORTSDATA_API_KEY", "").strip()
        self._cache = _TTLCache(ttl_sec=int(os.getenv("SPORTSDATA_CACHE_TTL_SEC", "900")))  # 15m
        self._disk_cache_dir = (os.getenv("FAZ_CACHE_DIR") or "").strip()
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session and not self._session.closed:
            return self._session
        timeout = aiohttp.ClientTimeout(total=25)
        self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request_json(self, url: str) -> Optional[Any]:
        if not self.key:
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

        headers = {"Ocp-Apim-Subscription-Key": self.key}

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

    async def fetch_team_baseline(self, team_key: str, season_year: str) -> Optional[Dict[str, Any]]:
        """
        Returns season baseline (PPG / Opp PPG) for team_key (e.g., BKN, HOU, LAC).
        """
        if not self.key:
            return None

        tk = (team_key or "").upper().strip()
        if not tk:
            return None

        url = f"https://api.sportsdata.io/v3/nba/scores/json/TeamSeasonStats/{season_year}"
        data = await self._request_json(url)
        if not isinstance(data, list):
            return None

        row = next((x for x in data if str(x.get("Key", "")).upper() == tk), None)
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
            "team_key": tk,
        }

    async def fetch_team_players(self, team_key: str) -> Optional[List[Dict[str, Any]]]:
        """
        Players by Team endpoint (commonly available in SportsDataIO NBA v3 scores feed):
          /scores/json/Players/{team}
        """
        if not self.key:
            return None

        tk = (team_key or "").upper().strip()
        if not tk:
            return None

        url = f"https://api.sportsdata.io/v3/nba/scores/json/Players/{tk}"
        data = await self._request_json(url)
        if isinstance(data, list):
            return data
        return None

    async def fetch_team_injuries(self, team_key: str) -> Optional[Dict[str, Any]]:
        """
        Injury extraction from Players/{team} feed:
        We filter players with InjuryStatus present (or InjuryStartDate/InjuryNotes).
        """
        players = await self.fetch_team_players(team_key)
        if players is None:
            return None

        injuries: List[Dict[str, Any]] = []
        for p in players:
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
                        "start_date": start,
                        "notes": notes,
                        "position": p.get("Position"),
                    }
                )

        return {
            "source": self.name,
            "team_key": (team_key or "").upper().strip(),
            "injuries": injuries,
            "injury_count": len(injuries),
            "fetched_at": int(time.time()),
        }
