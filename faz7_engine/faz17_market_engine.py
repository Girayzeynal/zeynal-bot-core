# engines/faz17_market_engine.py
from __future__ import annotations

from typing import Dict, Any, Optional
from config.league_profiles import LEAGUE_PROFILES


class Faz17MarketEngine:
    def __init__(self, odds_client: "OddsClient"):
        self.odds = odds_client

    def resolve_sport_key(self, league_profile: str) -> Optional[str]:
        lp = LEAGUE_PROFILES.get(league_profile.upper())
        return lp.api_sport_key if lp else None

    def enrich_with_market(self, base: Dict[str, Any]) -> Dict[str, Any]:
        league_profile = (base.get("league_profile") or "").upper()
        sport_key = self.resolve_sport_key(league_profile)

        if not sport_key:
            base["market"] = {
                "status": "NO_SPORT_KEY",
                "sport_key": None,
                "note": f"{league_profile} için TheOddsAPI sport_key yok; provider=api_basketball/manual gerek.",
            }
            return base

        m = self.odds.fetch_totals(sport_key=sport_key, home=base["home"], away=base["away"])
        if not m:
            base["market"] = {"status": "NO_DATA", "sport_key": sport_key}
            return base

        market_total = float(m["total"])
        base["market"] = {
            "status": "OK",
            "sport_key": sport_key,
            "market_total": market_total,
            "book": m.get("book", "UNKNOWN"),
        }

        # Edge hint: band center vs market line
        mu = base.get("baseline", {}).get("mu_total")
        if isinstance(mu, (int, float)):
            diff = market_total - float(mu)
            if diff >= 3.0:
                hint = "Line yüksek → ALT eğilimi"
            elif diff <= -3.0:
                hint = "Line düşük → ÜST eğilimi"
            else:
                hint = "Line yakın → net edge yok"
        else:
            hint = "Team baseline yok → market-only (edge sınırlı)"

        base["market"]["edge_hint"] = hint
        return base


class OddsClient:
    def fetch_totals(self, sport_key: str, home: str, away: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError
