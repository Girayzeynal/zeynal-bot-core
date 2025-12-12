# faz23_engine/faz23_odds_debug.py
# ================================================================
# FAZ-23 ODDS DEBUG MODULE
# Amaç: Odds API neden veri dönmüyor? -> kanıt üretir
# ================================================================

import os
import json
import logging
import requests
from datetime import datetime, timezone, timedelta
from typing import Any, Dict

log = logging.getLogger("faz23-odds-debug")

ODDS_API_KEY = os.getenv("ODDS_API_KEY")
ODDS_BASE_URL = os.getenv("ODDS_BASE_URL", "https://api.the-odds-api.com/v4")

HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT_READ", "8.0"))

# ---------------------------------------------------
# SPORT KEY MAP (kritik nokta)
# ---------------------------------------------------
SPORT_KEY_MAP = {
    "NBA": "basketball_nba",
    "EUROLEAGUE": "basketball_euroleague",
}

# ---------------------------------------------------
def _utc_range_for_date(date_str: str) -> Dict[str, str]:
    """
    Odds API UTC ister. Günü daraltıyoruz.
    """
    day = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start = day - timedelta(hours=6)
    end = day + timedelta(hours=30)
    return {
        "commenceTimeFrom": start.isoformat(),
        "commenceTimeTo": end.isoformat(),
    }

# ---------------------------------------------------
def debug_fetch_odds(
    league: str,
    date_str: str,
    home: str,
    away: str,
) -> Dict[str, Any]:
    """
    Sadece debug eder. Tahmin yapmaz.
    """
    print("\n================ FAZ23 ODDS DEBUG =================")

    if not ODDS_API_KEY:
        print("❌ ODDS_API_KEY yok")
        return {}

    sport_key = SPORT_KEY_MAP.get(league)
    if not sport_key:
        print(f"❌ League map yok: {league}")
        return {}

    time_filter = _utc_range_for_date(date_str)

    url = f"{ODDS_BASE_URL}/sports/{sport_key}/odds"

    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us,eu",
        "markets": "totals",
        "oddsFormat": "decimal",
        **time_filter,
    }

    print("▶ URL:", url)
    print("▶ PARAMS:", json.dumps(params, indent=2))
    print("▶ HOME / AWAY:", home, "-", away)

    try:
        r = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
    except Exception as e:
        print("❌ REQUEST ERROR:", e)
        return {}

    print("▶ HTTP STATUS:", r.status_code)

    if r.status_code != 200:
        print("❌ RESPONSE TEXT:", r.text[:500])
        return {}

    try:
        data = r.json()
    except Exception:
        print("❌ JSON parse edilemedi")
        return {}

    print(f"▶ TOPLAM EVENT SAYISI: {len(data)}")

    matched = []
    for ev in data:
        h = ev.get("home_team", "").lower()
        a = ev.get("away_team", "").lower()
        if home.lower() in h and away.lower() in a:
            matched.append(ev)

    print(f"▶ MATCHED EVENT SAYISI: {len(matched)}")

    if not matched:
        print("❌ MAÇ EŞLEŞMEDİ")
        print("▶ İlk 3 event örneği:")
        for ev in data[:3]:
            print("-", ev.get("home_team"), "vs", ev.get("away_team"))
        return {}

    ev = matched[0]
    print("✅ MATCH BULUNDU:", ev.get("home_team"), "-", ev.get("away_team"))

    books = ev.get("bookmakers", [])
    print("▶ BOOKMAKER SAYISI:", len(books))

    totals_found = 0
    for b in books:
        for m in b.get("markets", []):
            if m.get("key") == "totals":
                totals_found += 1
                print("✔ TOTALS MARKET:",
                      "bookmaker=", b.get("key"),
                      "outcomes=", m.get("outcomes"))

    if totals_found == 0:
        print("❌ TOTALS MARKET YOK")

    print("================ DEBUG END =================\n")
    return ev
