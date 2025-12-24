from typing import Dict, Any, Optional, Tuple

MarketData = Dict[str, Any]

def fetch_market(league: str, date_str: str, home: str, away: str) -> Optional[MarketData]:
    from faz17_engine.providers import fetch_from_odds_api

    market, meta = fetch_from_odds_api(
        league=league, date_str=date_str, home=home, away=away
    )

    if not market or not meta.get("used"):
        return None

    return {
        "line": market.get("line"),
        "provider": meta.get("provider"),
        "used": True,
    } 
