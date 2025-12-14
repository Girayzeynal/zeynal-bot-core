# -*- coding: utf-8 -*-
"""
FAZ-17 Market Providers (FINAL – import uyumlu)

Main.py'nin aradığı fonksiyon isimleri:
- faz17_fetch_market
- faz17_fetch_market_safe
"""

from __future__ import annotations

import os
import time
import logging
import requests
from typing import Dict, Any, Optional

log = logging.getLogger("FAZ17")

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "").strip()


def _now() -> int:
    return int(time.time())


def _safe_float(v) -> Optional[float]:
    try:
        return float(v)
    except Exception:
        return None


def _fetch_odds_api_market(league: str, date_str: str, home: str, away: str) -> Dict[str, Any]:
    if not ODDS_API_KEY:
        return {"used": False, "provider": "odds_api", "reason": "missing_odds_api_key"}

    # NBA sabit
    sport_key = "basketball_nba"
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": "h2h,totals",
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }

    log.warning("[FAZ17 PROVIDER] ODDS API REQUEST %s | %s vs %s", league, home, away)

    try:
        r = requests.get(url, params=params, timeout=12)
        if r.status_code != 200:
            return {"used": False, "provider": "odds_api", "reason": f"http_{r.status_code}"}
        data = r.json()
        if not isinstance(data, list) or not data:
            return {"used": False, "provider": "odds_api", "reason": "empty_response"}
    except Exception as e:
        return {"used": False, "provider": "odds_api", "reason": f"exception:{e}"}

    # Maçı bul
    match = None
    for g in data:
        teams = g.get("teams") or []
        if home in teams and away in teams:
            match = g
            break

    if not match:
        return {"used": False, "provider": "odds_api", "reason": "match_not_found"}

    bookmakers = match.get("bookmakers") or []
    if not bookmakers:
        return {"used": False, "provider": "odds_api", "reason": "no_bookmakers"}

    totals_block = None
    h2h_block = None

    for bm in bookmakers:
        for m in bm.get("markets", []):
            if m.get("key") == "totals" and not totals_block:
                outcomes = m.get("outcomes") or []
                if len(outcomes) >= 2:
                    over = outcomes[0]
                    under = outcomes[1]
                    line = _safe_float(over.get("point"))
                    if line is not None:
                        totals_block = {
                            "line": line,
                            "over_price": _safe_float(over.get("price")),
                            "under_price": _safe_float(under.get("price")),
                        }

            if m.get("key") == "h2h" and not h2h_block:
                outcomes = m.get("outcomes") or []
                prices = {o.get("name"): _safe_float(o.get("price")) for o in outcomes}
                h2h_block = {
                    "home_price": prices.get(home),
                    "away_price": prices.get(away),
                }

        if totals_block or h2h_block:
            break

    if not totals_block and not h2h_block:
        return {"used": False, "provider": "odds_api", "reason": "markets_not_found"}

    confidence = None
    if totals_block and totals_block.get("over_price") and totals_block.get("under_price"):
        op = totals_block["over_price"]
        up = totals_block["under_price"]
        if op and up:
            confidence = max(0.05, min(0.25, 1 - abs(op - up)))

    log.warning("[FAZ17 PROVIDER] MARKET OK totals=%s h2h=%s", bool(totals_block), bool(h2h_block))

    return {
        "used": True,
        "provider": "odds_api",
        "totals": totals_block,
        "h2h": h2h_block,
        "confidence": confidence,
        "reason": None,
        "ts": _now(),
    }


# -------------------------------------------------
# Main.py uyum katmanı (ASIL ÖNEMLİ KISIM)
# -------------------------------------------------

def faz17_fetch_market(league: str, date_str: str, home: str, away: str) -> Dict[str, Any]:
    """Main.py bunu import ediyorsa artık import patlamaz."""
    return _fetch_odds_api_market(league, date_str, home, away)


def faz17_fetch_market_safe(
    league: str,
    date_str: str,
    home: str,
    away: str,
    provider_fetch_func=None,   # main.py bazen bunu keyword arg olarak yolluyor
) -> Dict[str, Any]:
    """
    Güvenli wrapper.
    Eğer main.py 'provider_fetch_func' gönderirse onu kullanır,
    yoksa default odds provider'ı kullanır.
    """
    try:
        fn = provider_fetch_func or faz17_fetch_market
        return fn(league=league, date_str=date_str, home=home, away=away)
    except Exception as e:
        log.warning("[FAZ17] fetch_market_safe exception: %s", e)
        return {"used": False, "provider": None, "reason": f"safe_fetch_exception:{e}", "ts": _now()}
