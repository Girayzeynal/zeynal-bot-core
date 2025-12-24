# faz17_engine/faz17_market_fetcher.py
from __future__ import annotations
from typing import Any, Dict, Optional, Tuple
from faz17_engine.providers import fetch_from_odds_api, fetch_from_api_sports

MarketData = Dict[str, Any]
MarketMeta = Dict[str, Any]

def fetch_market(league: str, date_str: str, home: str, away: str) -> Tuple[Optional[MarketData], Optional[MarketMeta]]:
    # Öncelik: The Odds API
    market, meta = fetch_from_odds_api(league=league, date_str=date_str, home=home, away=away)
    if meta.get("used"):
        return market, meta
    # Fallback: API‑SPORTS
    market2, meta2 = fetch_from_api_sports(league=league, date_str=date_str, home=home, away=away)
    if meta2.get("used"):
        return market2, meta2
    # Hiç veri yoksa
    return None, (meta2 or meta or {"provider":"none","used":False,"confidence":0.0,"reason":"no_market"})
