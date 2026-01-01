from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import aiohttp


@dataclass(frozen=True)
class MarketRequest:
    league: str
    date_str: str  # YYYY-MM-DD
    home: str
    away: str


class Faz17Engine:
    """
    Market engine (The Odds API compatible).
    Env:
      - ODDS_API_KEY
      - ODDS_BASE (default: https://api.the-odds-api.com/v4)
      - ODDS_SPORT_KEY (default for NBA: basketball_nba)
      - ODDS_REGIONS (default: us)
      - ODDS_MARKETS (default: totals)
      - ODDS_BOOKMAKER_PREFER (default: FanDuel)
    """

    def __init__(
        self,
        odds_api_key: Optional[str] = None,
        odds_base: Optional[str] = None,
        *args,
        **kwargs,
    ) -> None:
        """
        main.py geri uyumu:
            Faz17Engine(ODDS_API_KEY, ODDS_BASE)

        - Parametre verilmezse ENV kullanılır
        - Fazladan argümanlar crash etmez
        """

        # main.py’den gelenler (varsa)
        self.odds_api_key = odds_api_key
        self.odds_base = odds_base

        # Gerçek kullanımda ENV öncelikli
        self.api_key = (odds_api_key or "").strip() or (os.getenv("ODDS_API_KEY") or "").strip()
        self.base = (odds_base or "").strip() or (os.getenv("ODDS_BASE") or "https://api.the-odds-api.com/v4").rstrip("/")

        self.sport_key = (os.getenv("ODDS_SPORT_KEY") or "basketball_nba").strip()
        self.regions = (os.getenv("ODDS_REGIONS") or "us").strip()
        self.markets = (os.getenv("ODDS_MARKETS") or "totals").strip()
        self.prefer_bookmaker = (os.getenv("ODDS_BOOKMAKER_PREFER") or "FanDuel").strip()

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

    @staticmethod
    def _norm(s: str) -> str:
        return " ".join((s or "").strip().lower().replace("-", " ").replace("_", " ").split())

    @staticmethod
    def _same_date(iso_ts: str, ymd: str) -> bool:
        # iso_ts like 2026-01-02T03:00:00Z
        return str(iso_ts or "")[:10] == ymd

    @staticmethod
    def _parse_total_from_bookmaker(bm: Dict[str, Any]) -> Optional[float]:
        for mkt in bm.get("markets", []) or []:
            if (mkt.get("key") or "").lower() != "totals":
                continue
            outcomes = mkt.get("outcomes", []) or []
            # outcomes: [{"name":"Over","point":219.5,...},{"name":"Under","point":219.5,...}]
            for o in outcomes:
                pt = o.get("point")
                if pt is not None:
                    return float(pt)
        return None

    async def fetch_market_total(self, req: MarketRequest) -> Optional[Dict[str, Any]]:
        if not self.api_key:
            return None

        url = f"{self.base}/sports/{self.sport_key}/odds"
        params = {
            "apiKey": self.api_key,
            "regions": self.regions,
            "markets": self.markets,
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        }

        backoff = 0.7
        data: Optional[List[Dict[str, Any]]] = None
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
                    break
            except Exception:
                await asyncio.sleep(backoff)
                backoff *= 1.7

        if not isinstance(data, list):
            return None

        home_n = self._norm(req.home)
        away_n = self._norm(req.away)

        candidates: List[Dict[str, Any]] = []
        for g in data:
            ht = self._norm(g.get("home_team", ""))
            at = self._norm(g.get("away_team", ""))
            if not ht or not at:
                continue
            if not self._same_date(str(g.get("commence_time", "")), req.date_str):
                continue
            # match either orientation
            if (ht == home_n and at == away_n) or (ht == away_n and at == home_n):
                candidates.append(g)

        if not candidates:
            return None

        game = candidates[0]
        bookmakers = game.get("bookmakers", []) or []

        # prefer bookmaker if available
        chosen = None
        for bm in bookmakers:
            if str(bm.get("title", "")).strip().lower() == self.prefer_bookmaker.lower():
                chosen = bm
                break
        if chosen is None and bookmakers:
            chosen = bookmakers[0]

        if not chosen:
            return None

        total = self._parse_total_from_bookmaker(chosen)
        if total is None:
            return None

        return {
            "status": "OK",
            "total": float(total),
            "bookmaker": str(chosen.get("title", "")) or self.prefer_bookmaker,
            "fetched_at": int(time.time()),
        }
