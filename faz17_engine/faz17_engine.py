import aiohttp
import os
import logging
from typing import Optional
from faz13_engine import Faz13CoreOutput

log = logging.getLogger("zeynal-bot-core")

class Faz17Engine:
    def __init__(self, odds_api_key: str, odds_base: str) -> None:
        self.key = odds_api_key
        self.base = odds_base.rstrip("/")
        self.regions = os.getenv("ODDS_REGIONS", "us,eu") # EU eklendi
        self.markets = "totals" # Odaklanmış market
        self.odds_format = "decimal"
        self.session: Optional[aiohttp.ClientSession] = None

    async def _session(self) -> aiohttp.ClientSession:
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    @staticmethod
    def _norm(s: str) -> set:
        """Kelime kümesi döndürür. Bu sayede 'Trail Blazers' ile 'Portland' eşleşebilir."""
        if not s: return set()
        s = s.lower()
        # Gereksiz ekleri temizle
        for token in ("basketball", "basket", "club", "team", "bc", "bk"):
            s = s.replace(token, "")
        # Sadece harf ve rakamları tut, kelimelere böl
        import re
        words = re.findall(r'\w+', s)
        return set(words)

    async def enrich_with_market(self, core: Faz13CoreOutput) -> Faz13CoreOutput:
        league_upper = (core.ctx.league or "").upper()
        
        # Dinamik Sport Key (Geliştirildi)
        sport_key = "basketball_nba"
        if "EURO" in league_upper: sport_key = "basketball_euroleague"
        elif "TURK" in league_upper or "BSL" in league_upper: sport_key = "basketball_turkey_bsl"
        elif "SPAIN" in league_upper or "ACB" in league_upper: sport_key = "basketball_spain_liga_acb"

        url = f"{self.base}/sports/{sport_key}/odds"
        params = {
            "apiKey": self.key,
            "regions": self.regions,
            "markets": self.markets,
            "oddsFormat": self.odds_format,
        }

        session = await self._session()
        try:
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status != 200: raise Exception(f"API Error: {resp.status}")
                data = await resp.json()
        except Exception as e:
            log.error(f"Market fetch failed: {e}")
            core.market = {"status": "NO_MARKET", "reason": "API_CONNECTION_ERROR"}
            return core

        # Normalizasyon: Kelime kümeleri oluştur (Örn: {'portland', 'trail', 'blazers'})
        nh_set, na_set = self._norm(core.ctx.home), self._norm(core.ctx.away)

        for event in data:
            h_api = self._norm(event.get("home_team", ""))
            a_api = self._norm(event.get("away_team", ""))

            # Kesişim kontrolü (En az bir kelime eşleşmeli: 'Lakers' vs 'LA Lakers')
            home_match = bool(nh_set & h_api)
            away_match = bool(na_set & a_api)
            
            # Ters eşleşme kontrolü
            home_rev_match = bool(nh_set & a_api)
            away_rev_match = bool(na_set & h_api)

            if (home_match and away_match) or (home_rev_match and away_rev_match):
                selected_total = None
                book_name = "N/A"

                for bookmaker in event.get("bookmakers", []):
                    for market in bookmaker.get("markets", []):
                        if market.get("key") == "totals":
                            for outcome in market.get("outcomes", []):
                                name = (outcome.get("name") or "").lower()
                                if "over" in name or "üst" in name:
                                    selected_total = outcome.get("point")
                                    book_name = bookmaker.get("title")
                                    break
                    if selected_total: break

                if selected_total:
                    # FAZ-13 Bandı ile karşılaştırma
                    lo, hi = core.total_band if hasattr(core, 'total_band') else (0,0)
                    
                    edge = "NÖTR"
                    if selected_total > hi + 1.5: edge = "Line Yüksek ➡ ALT"
                    elif selected_total < lo - 1.5: edge = "Line Düşük ➡ ÜST"

                    core.market = {
                        "status": "OK",
                        "total": selected_total,
                        "bookmaker": book_name,
                        "edge": edge
                    }
                    # Faz-16 ve Faz-22 için gerekli veriyi de ekleyelim
                    setattr(core, "market_total", selected_total)
                    return core

        core.market = {"status": "NO_MARKET", "reason": "MATCH_NOT_FOUND"}
        return core
 
