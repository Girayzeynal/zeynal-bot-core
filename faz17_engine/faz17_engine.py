# faz17_engine.py
import aiohttp
import json
import time
from typing import Dict, Optional

from faz13_engine import Faz13CoreOutput


class Faz17Engine:
    def __init__(self, odds_api_key: str, odds_base: str):
        self.key = odds_api_key
        self.base = odds_base.rstrip("/")
        self.session: Optional[aiohttp.ClientSession] = None

    async def _session(self):
        if not self.session:
            self.session = aiohttp.ClientSession()
        return self.session

    @staticmethod
    def _norm(s: str) -> str:
        for t in ["basket", "basketball", "bc", "bk", "club"]:
            s = s.lower().replace(t, "")
        return "".join(c for c in s if c.isalnum())

    async def enrich_with_market(self, core: Faz13CoreOutput) -> Faz13CoreOutput:
        sport = "basketball_euroleague"
        url = f"{self.base}/sports/{sport}/odds"
        params = {
            "apiKey": self.key,
            "regions": "eu,us",
            "markets": "totals,spreads",
            "oddsFormat": "decimal"
        }

        s = await self._session()
        async with s.get(url, params=params) as r:
            data = await r.json()

        nh = self._norm(core.ctx.home)
        na = self._norm(core.ctx.away)

        for ev in data:
            h = self._norm(ev["home_team"])
            a = self._norm(ev["away_team"])
            if nh in h and na in a:
                book = ev["bookmakers"][0]
                total = book["markets"][0]["outcomes"][0]["point"]
                core.market = {
                    "status": "OK",
                    "sport_key": sport,
                    "market_total": total,
                    "book": book["title"],
                    "edge_hint": "Line yüksek → ALT eğilimi"
                }
                return core

        core.market = {"status": "NO_MARKET"}
        return core
