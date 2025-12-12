# faz23_engine/faz23_odds_debug.py
# ==================================================
# FAZ-23 ODDS DEBUG MODULE
# API-Sports + Odds API test helper
# ==================================================

import os
import logging
import requests
from typing import Any, Dict, Optional

log = logging.getLogger("faz23-odds-debug")

API_SPORT_KEY = os.getenv("API_BASK_KEY")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

API_SPORT_BASE = os.getenv(
    "API_BASK_BASE_URL",
    "https://v1.basketball.api-sports.io"
)

ODDS_BASE = os.getenv(
    "ODDS_BASE_URL",
    "https://api.the-odds-api.com/v4"
)

TIMEOUT = (3.0, 8.0)


def debug_fetch_odds(
    league: str,
    date_str: str,
    home: str,
    away: str,
) -> Dict[str, Any]:
    """
    SADECE DEBUG AMAÇLI.
    main.py tarafından çağrılmaz.
    """

    print("\n[FAZ23-ODDS-DEBUG]")
    print("league:", league)
    print("date:", date_str)
    print("home:", home)
    print("away:", away)

    result = {
        "api_sports": None,
        "odds_api": None,
    }

    # ---------------------------
    # API-SPORTS TEST
    # ---------------------------
    if API_SPORT_KEY:
        try:
            r = requests.get(
                f"{API_SPORT_BASE}/games",
                headers={"x-apisports-key": API_SPORT_KEY},
                params={
                    "date": date_str,
                    "league": league,
                },
                timeout=TIMEOUT,
            )
            print("\n[API-SPORTS] status:", r.status_code)
            if r.ok:
                data = r.json()
                print("[API-SPORTS] response keys:", list(data.keys()))
                result["api_sports"] = data
            else:
                print("[API-SPORTS] error body:", r.text)
        except Exception as e:
            print("[API-SPORTS] EXCEPTION:", e)
    else:
        print("[API-SPORTS] API_BASK_KEY YOK")

    # ---------------------------
    # ODDS API TEST
    # ---------------------------
    if ODDS_API_KEY:
        try:
            r = requests.get(
                f"{ODDS_BASE}/sports/basketball_euroleague/odds",
                params={
                    "apiKey": ODDS_API_KEY,
                    "regions": "eu",
                    "markets": "totals",
                },
                timeout=TIMEOUT,
            )
            print("\n[ODDS-API] status:", r.status_code)
            if r.ok:
                data = r.json()
                print("[ODDS-API] matches:", len(data))
                result["odds_api"] = data
            else:
                print("[ODDS-API] error body:", r.text)
        except Exception as e:
            print("[ODDS-API] EXCEPTION:", e)
    else:
        print("[ODDS-API] ODDS_API_KEY YOK")

    print("\n[FAZ23-ODDS-DEBUG END]\n")
    return result
