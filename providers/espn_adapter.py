# providers/espn_adapter.py

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import aiohttp


ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"


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


def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().replace("-", " ").replace("_", " ").split())


class ESPNAdapter:
    """
    ESPN provider (no API key).
    Provides:
      - team baseline (avgPointsFor/avgPointsAgainst) via /teams/{abbr}
      - injury data via ESPN team injury page (HTML) resolved from /teams directory
    """

    name = "ESPN"
    confidence = 0.60

    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None
        self._cache = _TTLCache(ttl_sec=int(os.getenv("ESPN_CACHE_TTL_SEC", "900")))  # 15m
        self._teams_cache_ttl = int(os.getenv("ESPN_TEAMS_TTL_SEC", "21600"))  # 6h
        self._teams_cache = _TTLCache(ttl_sec=self._teams_cache_ttl)
        self._disk_cache_dir = (os.getenv("FAZ_CACHE_DIR") or "").strip()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session and not self._session.closed:
            return self._session
        timeout = aiohttp.ClientTimeout(total=25)
        self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        cache_key = f"json:{url}:{json.dumps(params, sort_keys=True) if params else ''}"
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

        backoff = 0.6
        for attempt in range(4):
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

    async def _request_text(self, url: str) -> Optional[str]:
        cache_key = f"text:{url}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        disk_key = None
        if self._disk_cache_dir:
            safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", cache_key)[:180]
            disk_key = os.path.join(self._disk_cache_dir, f"{safe}.txt")
            try:
                if os.path.exists(disk_key):
                    if (time.time() - os.path.getmtime(disk_key)) <= self._cache.ttl_sec:
                        with open(disk_key, "r", encoding="utf-8", errors="ignore") as f:
                            txt = f.read()
                        self._cache.set(cache_key, txt)
                        return txt
            except Exception:
                pass

        backoff = 0.6
        for attempt in range(4):
            try:
                s = await self._get_session()
                async with s.get(url) as resp:
                    if resp.status in (429, 503, 502, 504):
                        await asyncio.sleep(backoff)
                        backoff *= 1.7
                        continue
                    if resp.status != 200:
                        return None
                    txt = await resp.text()
                    self._cache.set(cache_key, txt)
                    if disk_key:
                        try:
                            os.makedirs(self._disk_cache_dir, exist_ok=True)
                            with open(disk_key, "w", encoding="utf-8") as f:
                                f.write(txt)
                        except Exception:
                            pass
                    return txt
            except Exception:
                await asyncio.sleep(backoff)
                backoff *= 1.7
        return None

    async def fetch_team_baseline(self, team_abbr: str) -> Optional[Dict[str, Any]]:
        """
        Returns:
          {
            pts_for, pts_against, confidence, source, fetched_at
          }
        """
        abbr = (team_abbr or "").strip().lower()
        if not abbr:
            return None

        js = await self._request_json(f"{ESPN_BASE}/teams/{abbr}")
        if not js:
            return None

        items = js.get("team", {}).get("record", {}).get("items", [])
        stats: Dict[str, Any] = {}
        for it in items:
            for st in it.get("stats", []):
                nm = st.get("name")
                if nm:
                    stats[nm] = st.get("value")

        if "avgPointsFor" not in stats or "avgPointsAgainst" not in stats:
            return None

        return {
            "pts_for": float(stats["avgPointsFor"]),
            "pts_against": float(stats["avgPointsAgainst"]),
            "confidence": float(self.confidence),
            "source": self.name,
            "fetched_at": int(time.time()),
        }

    async def _get_teams_directory(self) -> Optional[Dict[str, Any]]:
        cached = self._teams_cache.get("nba_teams_dir")
        if cached is not None:
            return cached
        js = await self._request_json(f"{ESPN_BASE}/teams")
        if not js:
            return None
        self._teams_cache.set("nba_teams_dir", js)
        return js

    async def resolve_team_injury_url(self, team_abbr: str) -> Optional[str]:
        """
        Returns ESPN injury page URL for the team by reading the teams directory.
        """
        abbr = (team_abbr or "").strip().lower()
        if not abbr:
            return None

        js = await self._get_teams_directory()
        if not js:
            return None

        teams = (
            js.get("sports", [{}])[0]
            .get("leagues", [{}])[0]
            .get("teams", [])
        )

        for t in teams:
            team = (t or {}).get("team") or {}
            if str(team.get("abbreviation", "")).lower() != abbr.upper().lower():
                continue
            links = team.get("links", []) or []
            for lk in links:
                rel = lk.get("rel", []) or []
                href = lk.get("href")
                if href and "injuries" in rel:
                    return href
        return None

    @staticmethod
    def _parse_injuries_html(html_text: str) -> List[Dict[str, Any]]:
        """
        ESPN team injury pages are HTML. We extract a structured list using conservative parsing:
        - This is NOT fabricated data; it’s parsed from the page content.
        """
        if not html_text:
            return []

        # Normalize whitespace
        txt = re.sub(r"\s+", " ", html_text)

        # A conservative pattern around "Status" occurrences is unreliable; instead:
        # We parse rows around "Status" labels if present.
        # We'll extract player names + status keywords if found.
        status_keywords = r"(Out|Day-To-Day|Questionable|Probable|Doubtful)"
        # A heuristic: "Status <keyword>" appears in the page snippet for team injury pages.
        pattern = re.compile(r"([A-Z][A-Za-z\.\-\' ]{2,35})\s+[A-Z]{0,2}\s*Status\s+(" + status_keywords + r")", re.IGNORECASE)

        out: List[Dict[str, Any]] = []
        for m in pattern.finditer(txt):
            name = m.group(1).strip()
            status = m.group(2).strip()
            out.append({"player": name, "status": status})

        # If pattern yields nothing, still treat page as present but unknown format
        return out

    async def fetch_team_injuries(self, team_abbr: str) -> Optional[Dict[str, Any]]:
        """
        Returns:
          {
            "source": "ESPN",
            "team_abbr": "...",
            "injuries": [ {player, status, ...}, ... ],
            "injury_count": int,
            "fetched_at": int
          }
        """
        url = await self.resolve_team_injury_url(team_abbr)
        if not url:
            return None

        html_text = await self._request_text(url)
        if html_text is None:
            return None

        injuries = self._parse_injuries_html(html_text)
        return {
            "source": self.name,
            "team_abbr": team_abbr.upper(),
            "injuries": injuries,
            "injury_count": len(injuries),
            "fetched_at": int(time.time()),
            "url": url,
        }
