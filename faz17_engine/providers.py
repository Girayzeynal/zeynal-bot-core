
# -*- coding: utf-8 -*-
"""
FAZ-17 Market Providers (FINAL – WORKING)

- ODDS API üzerinden NBA / Basketball market verisi çeker
- totals + h2h marketlerini parse eder
- FAZ-17 orchestrator'a GERÇEK veri döner
"""

from __future__ import annotations

import os
import time
import logging
import requests
from typing import Dict, Any, Optional, List

log = logging.getLogger("FAZ17")

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "").strip()

# -------------------------------------------------
# Helpers
# -------------------------------------------------

def _now() -> int:
    return int(time.time())

def _safe_float(v) -> Optional[float]:
    try:
        return float(v)
    except Exception:
        return None

# -------------------------------------------------
# MAIN PROVIDER
# -------------------------------------------------

def fetch_odds_api_market(
    league: str,
    date_str: str,
    home: str,
    away: str,
) -> Dict[str, Any]:
    """
    Returns:
    {
        used: bool,
        provider: "odds_api",
        totals: {
            line: float,
            over_price: float | None,
            under_price: float | None
        } | None,
        h2h: {
            home_price: float | None,
            away_price: float | None
        } | None,
        confidence: float | None,
        reason: str | None
    }
    """

    if not ODDS_API_KEY:
        return {
            "used": False,
            "provider": "odds_api",
            "reason": "missing_odds_api_key",
        }

    # NBA için net ve sabit endpoint
    sport_key = "basketball_nba"
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"

    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": "h2h,totals",
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }

    log.warning(
        "[FAZ17 PROVIDER] ODDS API REQUEST league=%s %s vs %s",
        league, home, away
    )

    try:
        r = requests.get(url, params=params, timeout=12)
        if r.status_code != 200:
            return {
                "used": False,
                "provider": "odds_api",
                "reason": f"http_{r.status_code}",
            }

        data = r.json()
        if not isinstance(data, list) or not data:
            return {
                "used": False,
                "provider": "odds_api",
                "reason": "empty_response",
            }

    except Exception as e:
        return {
            "used": False,
            "provider": "odds_api",
            "reason": f"exception:{e}",
        }

    # -------------------------------------------------
    # MATCH FIND
    # -------------------------------------------------

    match = None
    for g in data:
        teams = g.get("teams") or []
        if home in teams and away in teams:
            match = g
            break

    if not match:
        return {
            "used": False,
            "provider": "odds_api",
            "reason": "match_not_found",
        }

    bookmakers = match.get("bookmakers") or []
    if not bookmakers:
        return {
            "used": False,
            "provider": "odds_api",
            "reason": "no_bookmakers",
        }

    totals_block = None
    h2h_block = None

    # -------------------------------------------------
    # PARSE MARKETS
    # -------------------------------------------------

    for bm in bookmakers:
        for m in bm.get("markets", []):
            if m.get("key") == "totals" and not totals_block:
                outcomes = m.get("outcomes", [])
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
                outcomes = m.get("outcomes", [])
                prices = {o.get("name"): _safe_float(o.get("price")) for o in outcomes}
                h2h_block = {
                    "home_price": prices.get(home),
                    "away_price": prices.get(away),
                }

        if totals_block or h2h_block:
            break

    if not totals_block and not h2h_block:
        return {
            "used": False,
            "provider": "odds_api",
            "reason": "markets_not_found",
        }

    # -------------------------------------------------
    # CONFIDENCE (basit ama GERÇEK)
    # -------------------------------------------------

    confidence = None
    if totals_block and totals_block.get("over_price") and totals_block.get("under_price"):
        # oranlar dengeliyse confidence yükselir
        op = totals_block["over_price"]
        up = totals_block["under_price"]
        if op and up:
            confidence = max(0.05, min(0.25, 1 - abs(op - up)))

    log.warning(
        "[FAZ17 PROVIDER] MARKET OK totals=%s h2h=%s",
        bool(totals_block), bool(h2h_block)
    )

    return {
        "used": True,
        "provider": "odds_api",
        "totals": totals_block,
        "h2h": h2h_block,
        "confidence": confidence,
        "reason": None,
        "ts": _now(),
    }
