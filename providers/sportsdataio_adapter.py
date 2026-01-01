from __future__ import annotations

import asyncio
import json
import os
import re
import time
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

    Responsibilities:
      - Team season baseline (PointsPerGame / OpponentPointsPerGame)
      - Injury data via Players/{team} endpoint
      - Caching + retry + backoff

    This adapter:
      - NEVER fabricates data
      - NEVER computes edge / risk
      - ONLY returns raw provider data
    """

    name = "SPORTSDATAIO"
    confidence = 0.85  # provider reliability weight

    def __init__(self) -> None:
        self.api_key = (os.getenv("SPORTSDATA_API_KEY") or "").strip()
        self._session: Optional[aiohttp.ClientSession] = None

        self._cache = _TTLCache(
            ttl_sec=int(os.getenv("SPORTSDATA_CACHE_TTL_SEC", "900"))  # 15 min
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
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

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
    # TEAM BASELINE
    # -------------------------------------------------

    async def fetch_team_baseline(self, team_key: str, season_year: str) -> Optional[Dict[str, Any]]:
        """
        Returns (or None):
          {
            "pts_for": float,
            "pts_against": float,
            "confidence": float (0..1),
            "source": "SPORTSDATAIO",
            "fetched_at": int
          }
        """
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
    # INJURIES
    # -------------------------------------------------

    async def fetch_team_injuries(self, team_key: str) -> Optional[Dict[str, Any]]:
        """
        Returns (or None):
          {
            "source": "SPORTSDATAIO",
            "team_key": "BKN",
            "injuries": [ {player_id, name, status, body_part, notes, position}, ... ],
            "injury_count": int,
            "fetched_at": int
          }
        """
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
