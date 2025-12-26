"""
faz17_engine.py
================

This module defines ``Faz17Engine``, responsible for enriching predictions
produced by Faz13Engine with real‑time betting market data.  Unlike the
original implementation, this version consults the league profile registry
to pick an appropriate sport key for The Odds API.  It uses asynchronous
HTTP via ``aiohttp`` and performs fuzzy matching on team names to select
the correct event.  When market data cannot be retrieved, ``core.market``
is marked as ``{"status": "NO_MARKET"}``.
"""

import aiohttp
from typing import Optional

from faz13_engine import Faz13CoreOutput
from league_profiles import get_league_profile


class Faz17Engine:
    """Market enrichment engine using The Odds API."""

    def __init__(self, odds_api_key: str, odds_base: str) -> None:
        self.key = odds_api_key
        self.base = odds_base.rstrip("/")
        self.session: Optional[aiohttp.ClientSession] = None

    async def _session(self) -> aiohttp.ClientSession:
        """Return a shared aiohttp session (created on demand)."""
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    @staticmethod
    def _norm(s: str) -> str:
        """Normalize a team name by removing generic words and non‑alphanumerics."""
        s = s or ""
        lower = s.lower()
        for token in ["basketball", "basket", "bk", "bc", "club"]:
            lower = lower.replace(token, "")
        return "".join(ch for ch in lower if ch.isalnum())

    async def enrich_with_market(self, core: Faz13CoreOutput) -> Faz13CoreOutput:
        """Populate ``core.market`` with totals data from The Odds API, if available."""
        # Resolve the sport key from league metadata.  Defaults to NBA if unknown.
        profile = get_league_profile(core.ctx.league or "")
        sport_key = profile.api_sport_key or "basketball_nba"

        url = f"{self.base}/sports/{sport_key}/odds"
        params = {
            "apiKey": self.key,
            "regions": "eu,us",
            "markets": "totals,spreads",
            "oddsFormat": "decimal",
        }
        session = await self._session()
        try:
            async with session.get(url, params=params) as resp:
                data = await resp.json()
        except Exception:
            # If network request fails, just return core unchanged with no market info.
            core.market = {"status": "NO_MARKET"}
            return core

        # Normalize target team names once
        nh, na = self._norm(core.ctx.home), self._norm(core.ctx.away)
        for event in data:
            # Fuzzy match the event by comparing normalized names
            h = self._norm(event.get("home_team", ""))
            a = self._norm(event.get("away_team", ""))
            if nh and na and ((nh in h and na in a) or (nh in a and na in h)):
                bookmakers = event.get("bookmakers") or []
                book0 = bookmakers[0] if bookmakers else {}
                total = None
                for market in book0.get("markets", []):
                    if market.get("key") == "totals":
                        for oc in market.get("outcomes", []):
                            nm = (oc.get("name") or "").lower()
                            # consider Over/Üst outcomes only
                            if "over" in nm or "üst" in nm:
                                total = oc.get("point")
                                break
                # Compute an edge hint relative to the predicted band
                edge_hint = "Line yakın → net edge yok"
                if total is not None and isinstance(core.total_band, (list, tuple)) and len(core.total_band) == 2:
                    lo, hi = core.total_band
                    if total > hi + 2:
                        edge_hint = "Line yüksek → ALT eğilimi"
                    elif total < lo - 2:
                        edge_hint = "Line düşük → ÜST eğilimi"
                core.market = {
                    "status": "OK",
                    "sport_key": sport_key,
                    "market_total": total,
                    "book": book0.get("title") or book0.get("key") if book0 else None,
                    "edge_hint": edge_hint,
                }
                return core

        # No matching event found or totals missing
        core.market = {"status": "NO_MARKET"}
        return core
