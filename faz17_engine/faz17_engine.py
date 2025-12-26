"""
faz17_engine – Enrich a core prediction with betting market data.

This engine queries The Odds API to fetch totals and spreads for a
given basketball matchup.  It attempts to identify the correct
sport key based on the league and uses team names to match events
returned by the API.  When a market line is found, the core output
is adjusted: the over/under direction may flip if the line lies
outside the predicted band, and a market summary is attached.  If
no matching market is found, the core output is returned unmodified
with a status indicator.

The Odds API v4 is expected.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from faz13_engine import Faz13CoreOutput


class _TTLCache:
    """In‑memory TTL cache for storing recent HTTP responses."""

    def __init__(self, ttl_sec: float = 20.0) -> None:
        self.ttl = ttl_sec
        self._data: Dict[str, Tuple[float, Any]] = {}

    def get(self, key: str) -> Any:
        hit = self._data.get(key)
        if not hit:
            return None
        ts, val = hit
        if time.time() - ts > self.ttl:
            self._data.pop(key, None)
            return None
        return val

    def set(self, key: str, value: Any) -> None:
        self._data[key] = (time.time(), value)


class Faz17Engine:
    """Market adjustment layer using The Odds API."""

    def __init__(self, odds_api_key: str, odds_base: str) -> None:
        self.key = odds_api_key
        self.base = odds_base.rstrip("/")
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache = _TTLCache(ttl_sec=30.0)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session and not self.session.closed:
            return self.session
        timeout = aiohttp.ClientTimeout(total=16, connect=8)
        self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session

    async def aclose(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()

    async def _get(self, path: str, params: Dict[str, Any]) -> Any:
        """Perform an HTTP GET with caching and retry."""
        key = f"{path}?{json.dumps(params, sort_keys=True)}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        url = f"{self.base}{path}"
        s = await self._get_session()
        last_err: Optional[Exception] = None
        for attempt in range(4):
            try:
                async with s.get(url, params=params) as resp:
                    text = await resp.text()
                    if resp.status >= 500:
                        raise RuntimeError(f"Odds API {resp.status}: {text[:200]}")
                    data = json.loads(text) if text else {}
                    self.cache.set(key, data)
                    return data
            except Exception as e:
                last_err = e
                await asyncio.sleep(0.3 * (2 ** attempt))
        raise RuntimeError(f"Odds API request failed: {last_err!s}")

    @staticmethod
    def _guess_sport_keys(league: str) -> List[str]:
        """Return a list of probable sport keys for the league."""
        l = (league or "").lower()
        keys: List[str] = []
        if "nba" in l:
            keys.append("basketball_nba")
        if "euro" in l:
            keys.append("basketball_euroleague")
            keys.append("basketball_eurocup")
        if any(x in l for x in ["tbs", "tbl", "turk", "turkye", "tür"]):
            keys.append("basketball_turkey_super_league")
        if any(x in l for x in ["acb", "spain"]):
            keys.append("basketball_spain_acb")
        if any(x in l for x in ["lega", "italy"]):
            keys.append("basketball_italy_lega_basket_a")
        if any(x in l for x in ["greece", "a1"]):
            keys.append("basketball_greece_a1")
        # Generic fallbacks
        keys += [
            "basketball_nba",
            "basketball_euroleague",
            "basketball_eurocup",
        ]
        # Remove duplicates while preserving order
        seen = set()
        ordered: List[str] = []
        for k in keys:
            if k not in seen:
                ordered.append(k)
                seen.add(k)
        return ordered

    @staticmethod
    def _norm(s: str) -> str:
        """Normalize a team name for fuzzy matching.

        Many bookmaker feeds include club descriptors such as “BC”, “BK”,
        “basket”, or “basketball”. To improve matching between API‑Sports
        team names and Odds API team names, we remove common basketball‑related
        tokens before stripping non‑alphanumeric characters.
        """
        if not s:
            return ""
        s_lower = str(s).lower()
        for token in ["basketball", "basket", "bk", "bc", "club"]:
            s_lower = s_lower.replace(token, "")
        return "".join(ch for ch in s_lower if ch.isalnum())

    @classmethod
    def _find_event(
        cls, events: Any, home: str, away: str
    ) -> Optional[Dict[str, Any]]:
        """Find an event in a list of events matching home and away names."""
        if not isinstance(events, list):
            return None
        nh = cls._norm(home)
        na = cls._norm(away)
        for ev in events:
            try:
                h = cls._norm(ev.get("home_team", ""))
                a = cls._norm(ev.get("away_team", ""))
                if nh and na:
                    if (nh in h or h in nh) and (na in a or a in na):
                        return ev
                    if (nh in a or a in nh) and (na in h or h in na):
                        return ev
            except Exception:
                continue
        return None

    @staticmethod
    def _extract_market(ev: Dict[str, Any]) -> Dict[str, Any]:
        """Extract the total line and home spread from an event record."""
        out: Dict[str, Any] = {}
        books = ev.get("bookmakers") or []
        if not books:
            return out
        book0 = books[0]
        out["book"] = book0.get("title") or book0.get("key")
        for m in book0.get("markets") or []:
            mk = m.get("key")
            if mk == "totals":
                for oc in m.get("outcomes") or []:
                    name = (oc.get("name") or "").lower()
                    if "over" in name or "üst" in name or "total" in name:
                        out["total_line"] = oc.get("point")
                        break
            elif mk == "spreads":
                for oc in m.get("outcomes") or []:
                    if "point" in oc:
                        out.setdefault("home_spread", oc.get("point"))
                        break
        return out

    @staticmethod
    def _edge_hint(band: Tuple[int, int], line: Any) -> str:
        """Return a human readable edge hint comparing a band to a line."""
        if not isinstance(line, (int, float)):
            return "N/A"
        lo, hi = band
        if line < lo:
            return "Line düşük → UST eğilimi"
        if line > hi:
            return "Line yüksek → ALT eğilimi"
        return "Band içinde → Edge zayıf"

    async def enrich_with_market(
        self, core: Faz13CoreOutput
    ) -> Faz13CoreOutput:
        """Enrich a Faz13CoreOutput with betting market data."""
        league = core.ctx.league or ""
        sport_keys = self._guess_sport_keys(league)
        best_market: Dict[str, Any] = {}
        found_key: Optional[str] = None
        for sk in sport_keys:
            try:
                # Query multiple regions at once to broaden the search. Some leagues
                # (e.g., Euroleague) may only have markets listed in US regions.
                data = await self._get(
                    f"/sports/{sk}/odds",
                    {
                        "regions": "eu,us",
                        "markets": "totals,spreads",
                        "oddsFormat": "decimal",
                        "apiKey": self.key,
                    },
                )
                events = data
                match = self._find_event(events, core.ctx.home, core.ctx.away)
                if match:
                    mkt = self._extract_market(match)
                    if mkt:
                        best_market = mkt
                        found_key = sk
                        break
            except Exception:
                continue
        if not best_market:
            core.market = {
                "status": "NO_MARKET",
                "note": "Market verisi bulunamadı veya eşleşme çözülemedi.",
            }
            return core
        line = best_market.get("total_line")
        new_ou = core.ou_direction
        lo, hi = core.total_band
        if isinstance(line, (int, float)):
            if line <= lo - 2:
                new_ou = "UST"
            elif line >= hi + 2:
                new_ou = "ALT"
        core.ou_direction = new_ou
        core.market = {
            "status": "OK",
            "sport_key": found_key,
            "market_total": line,
            "market_home_spread": best_market.get("home_spread"),
            "book": best_market.get("book"),
            "edge_hint": self._edge_hint(core.total_band, line),
        }
        return core 
