# faz17_engine.py
import aiohttp
from typing import Optional
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
        s = s or ""
        lower = s.lower()
        for token in ["basketball", "basket", "bk", "bc", "club"]:
            lower = lower.replace(token, "")
        return "".join(ch for ch in lower if ch.isalnum())

    async def enrich_with_market(self, core: Faz13CoreOutput) -> Faz13CoreOutput:
        sport_key = "basketball_euroleague" if "EURO" in core.ctx.league.upper() else "basketball_nba"
        url = f"{self.base}/sports/{sport_key}/odds"
        params = {
            "apiKey": self.key,
            "regions": "eu,us",
            "markets": "totals,spreads",
            "oddsFormat": "decimal"
        }
        s = await self._session()
        try:
            async with s.get(url, params=params) as r:
                data = await r.json()
        except Exception:
            core.market = {"status": "NO_MARKET"}
            return core

        nh, na = self._norm(core.ctx.home), self._norm(core.ctx.away)
        for ev in data:
            h = self._norm(ev.get("home_team", ""))
            a = self._norm(ev.get("away_team", ""))
            if nh and na and ((nh in h and na in a) or (nh in a and na in h)):
                book0 = ev.get("bookmakers", [])[0]
                total = None
                for market in book0.get("markets", []):
                    if market.get("key") == "totals":
                        for oc in market.get("outcomes", []):
                            nm = (oc.get("name") or "").lower()
                            if "over" in nm or "üst" in nm:
                                total = oc.get("point")
                                break
                core.market = {
                    "status": "OK",
                    "sport_key": sport_key,
                    "market_total": total,
                    "book": book0.get("title") or book0.get("key"),
                    "edge_hint": "Line yüksek → ALT eğilimi" if total is not None and total > core.total_band[1] else "Line düşük → UST eğilimi"
                }
                return core

        core.market = {"status": "NO_MARKET"}
        return core
