# -*- coding: utf-8 -*-
"""
FAZ-17 Market Providers
Gerçek market verisini çeken katman
"""

from __future__ import annotations

import os
import time
import logging
import requests
from typing import Dict, Optional

log = logging.getLogger("FAZ17.PROVIDER")

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "").strip()
API_SPORT_KEY = os.getenv("API_SPORT_KEY", "").strip()

# --------------------------------------------------
# League → OddsAPI family eşlemesi
# --------------------------------------------------
LEAGUE_FAMILY_MAP = {
    "NBA": "basketball_nba",
    "EUROLEAGUE": "basketball_euroleague",
    "TURKEY": "basketball_turkey",
}

# --------------------------------------------------
def _odds_api_fetch(
    sport_key: str,
) -> Optional[Dict]:
    if not ODDS_API_KEY:
        return None

    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us,eu",
        "markets": "totals",
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }

    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning(f"OddsAPI fetch failed: {e}")
        return None


# --------------------------------------------------
def _extract_total_market(
    raw: list,
    home: str,
    away: str,
) -> Optional[Dict]:
    """
    Odds API çıktısından total (over/under) yakalar
    """
    for event in raw:
        teams = [t.lower() for t in event.get("teams", [])]
        if home.lower() not in teams or away.lower() not in teams:
            continue

        for bookmaker in event.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                if market.get("key") != "totals":
                    continue

                outcomes = market.get("outcomes", [])
                for o in outcomes:
                    if "point" in o:
                        return {
                            "provider": "odds_api",
                            "line": float(o["point"]),
                            "confidence": 0.65,
                        }
    return None


# --------------------------------------------------
def faz17_fetch_market(
    league: str,
    date_str: str,
    home: str,
    away: str,
) -> Optional[Dict]:
    """
    FAZ-17 ana market fetch fonksiyonu
    """
    family = LEAGUE_FAMILY_MAP.get(league.upper())
    if not family:
        log.warning(f"No family mapping for league={league}")
        return None

    log.warning(f"[FAZ17] Fetching market for {league} ({family})")

    raw = _odds_api_fetch(family)
    if not raw:
        return None

    market = _extract_total_market(raw, home, away)
    if not market:
        return None

    market["ts"] = int(time.time())
    return market
