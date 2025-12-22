# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import time
import requests
from typing import Dict, Any, Optional, Tuple

# =========================
# ENV
# =========================
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "").strip()
ODDS_API_URL = os.getenv("ODDS_API_URL", "https://api.the-odds-api.com/v4").strip()

API_SPORT_KEY = os.getenv("API_SPORT_KEY", "").strip()
API_SPORT_URL = os.getenv("API_SPORT_URL", "https://v1.basketball.api-sports.io").strip()

TIMEOUT = 8


# =========================
# UTILS
# =========================
def implied_prob(odds: float) -> float:
    try:
        o = float(odds)
        if o <= 1.0:
            return 0.0
        return 1.0 / o
    except Exception:
        return 0.0


def clamp01(x: float) -> float:
    try:
        v = float(x)
    except Exception:
        return 0.0
    return max(0.0, min(1.0, v))


def _safe_get(d: Dict[str, Any], *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default


# =========================
# CORE – MARKET FETCH
# =========================
def fetch_market(
    league: str,
    date_str: str,
    home: str,
    away: str,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """
    Market verisini çeker.
    DÖNÜŞ:
    - market_data: dict | None
    - market_meta: dict (debug + status)
    """

    meta = {
        "source": None,
        "status": "EMPTY",
        "error": None,
        "league": league,
        "date": date_str,
    }

    # -------------------------
    # 1) ODDS API
    # -------------------------
    if ODDS_API_KEY:
        try:
            url = f"{ODDS_API_URL}/sports/basketball/odds"
            params = {
                "apiKey": ODDS_API_KEY,
                "regions": "eu,us",
                "markets": "totals",
                "oddsFormat": "decimal",
            }

            r = requests.get(url, params=params, timeout=TIMEOUT)
            if r.status_code == 200:
                data = r.json()
                for g in data:
                    h = _safe_get(g, "home_team")
                    a = _safe_get(g, "away_team")
                    if not h or not a:
                        continue
                    if home.lower() in h.lower() and away.lower() in a.lower():
                        totals = _safe_get(g, "bookmakers", 0, "markets", 0, "outcomes", default=[])
                        over = next((x for x in totals if x.get("name") == "Over"), None)
                        under = next((x for x in totals if x.get("name") == "Under"), None)

                        market = {
                            "totals_line": over.get("point") if over else None,
                            "odds_over": over.get("price") if over else None,
                            "odds_under": under.get("price") if under else None,
                            "raw": g,
                        }

                        meta["source"] = "ODDS_API"
                        meta["status"] = "OK"
                        return market, meta
        except Exception as e:
            meta["error"] = f"ODDS_API_ERROR: {e}"

    # -------------------------
    # 2) API-SPORTS (fallback)
    # -------------------------
    if API_SPORT_KEY:
        try:
            headers = {"x-apisports-key": API_SPORT_KEY}
            url = f"{API_SPORT_URL}/games"
            params = {
                "date": date_str,
                "league": league,
            }

            r = requests.get(url, headers=headers, params=params, timeout=TIMEOUT)
            if r.status_code == 200:
                data = r.json()
                meta["source"] = "API_SPORTS"
                meta["status"] = "OK"
                return {"raw": data}, meta
        except Exception as e:
            meta["error"] = f"API_SPORTS_ERROR: {e}"

    # -------------------------
    # 3) FAIL SAFE
    # -------------------------
    meta["status"] = "NO_MARKET"
    return None, meta


# =========================
# ENRICH – MODEL + MARKET
# =========================
def enrich_with_market(
    model_prob_over: float,
    model_prob_under: Optional[float],
    odds_over: Optional[float],
    odds_under: Optional[float],
) -> Dict[str, float]:

    imp_over = implied_prob(odds_over) if odds_over else 0.0
    imp_under = implied_prob(odds_under) if odds_under else 0.0

    mpo = clamp01(model_prob_over)
    mpu = clamp01(model_prob_under if model_prob_under is not None else 1.0 - mpo)

    return {
        "implied_over": imp_over,
        "implied_under": imp_under,
        "model_prob_over": mpo,
        "model_prob_under": mpu,
        "edge_over": mpo - imp_over,
        "edge_under": mpu - imp_under,
    } 
