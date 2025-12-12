# faz23_engine/faz23_odds_debug.py
# ============================================================
# FAZ-23 STEP-2 : ODDS API DEBUG & TRACE
# Amaç: NO_MARKET_DATA sebebini NET görmek
# ============================================================

import os
import logging
import requests
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List

log = logging.getLogger("faz23-odds-debug")

ODDS_API_KEY = os.getenv("ODDS_API_KEY")
ODDS_BASE_URL = os.getenv("ODDS_BASE_URL", "https://api.the-odds-api.com/v4")

DEFAULT_REGIONS = os.getenv("ODDS_REGIONS", "eu,us")
DEFAULT_MARKETS = os.getenv("ODDS_MARKETS", "totals")
DEFAULT_ODDS_FORMAT = os.getenv("ODDS_FORMAT", "decimal")
DEFAULT_DATE_FORMAT = os.getenv("ODDS_DATE_FORMAT", "iso")

HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT_READ", "8.0"))

# ------------------------------------------------------------
# LEAGUE → ODDS SPORT_KEY MAP (KRİTİK)
# ------------------------------------------------------------
SPORT_KEY_MAP = {
    "NBA": "basketball_nba",
    "EUROLEAGUE": "basketball_euroleague",
}

# ------------------------------------------------------------
def debug_fetch_odds(
    league: str,
    date_str: str,
    home: str,
    away: str,
) -> Dict[str, Any]:
    """
    Sadece DEBUG amaçlı.
    Tahmin yapmaz, veri çeker, LOG basar.
    """

    log.warning("========== FAZ23 STEP2 ODDS DEBUG ==========")
    log.warning("INPUT | league=%s | date=%s | home=%s | away=%s",
                league, date_str, home, away)

    if not ODDS_API_KEY:
        log.error("ODDS_API_KEY YOK → %100 NO_MARKET_DATA")
        return {"ok": False, "reason": "NO_API_KEY"}

    sport_key = SPORT_KEY_MAP.get(league.upper())
    if not sport_key:
        log.error("SPORT_KEY YOK → league maplenmemiş: %s", league)
        return {"ok": False, "reason": "NO_SPORT_KEY"}

    # Tarih aralığı (çok kritik)
    try:
        match_date = datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        log.error("DATE PARSE HATALI: %s (YYYY-MM-DD olmalı)", date_str)
        return {"ok": False, "reason": "BAD_DATE"}

    commence_from = match_date.replace(tzinfo=timezone.utc)
    commence_to = commence_from + timedelta(days=1)

    url = f"{ODDS_BASE_URL}/sports/{sport_key}/odds"

    params = {
        "apiKey": ODDS_API_KEY,
        "regions": DEFAULT_REGIONS,
        "markets": DEFAULT_MARKETS,
        "oddsFormat": DEFAULT_ODDS_FORMAT,
        "dateFormat": DEFAULT_DATE_FORMAT,
        "commenceTimeFrom": commence_from.isoformat(),
        "commenceTimeTo": commence_to.isoformat(),
    }

    # 🔍 REQUEST LOG
    log.warning("REQUEST URL: %s", url)
    log.warning("PARAMS: %s", params)

    try:
        r = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
    except Exception as e:
        log.error("HTTP ERROR: %s", e)
        return {"ok": False, "reason": "HTTP_ERROR"}

    log.warning("HTTP STATUS: %s", r.status_code)

    if r.status_code != 200:
        log.error("ODDS API NON-200 RESPONSE")
        log.error("BODY: %s", r.text[:500])
        return {"ok": False, "reason": "BAD_STATUS"}

    try:
        data = r.json()
    except Exception:
        log.error("JSON PARSE FAILED")
        log.error("RAW: %s", r.text[:500])
        return {"ok": False, "reason": "BAD_JSON"}

    log.warning("EVENT COUNT: %d", len(data))

    # --------------------------------------------------------
    # EVENT DETAY LOG
    # --------------------------------------------------------
    matched_events: List[Dict[str, Any]] = []

    for ev in data:
        ev_home = ev.get("home_team")
        ev_away = ev.get("away_team")
        ev_time = ev.get("commence_time")

        log.warning(
            "EVENT | %s vs %s | time=%s",
            ev_home, ev_away, ev_time
        )

        if not ev_home or not ev_away:
            continue

        if home.lower() in ev_home.lower() and away.lower() in ev_away.lower():
            matched_events.append(ev)

    log.warning("MATCHED EVENTS: %d", len(matched_events))

    if not matched_events:
        log.error("SONUÇ: NO_MARKET_DATA (EVENT VAR AMA MAÇ EŞLEŞMEDİ)")
        return {
            "ok": False,
            "reason": "NO_MATCHED_EVENT",
            "event_count": len(data),
        }

    # Market kontrolü
    markets_found = 0
    for ev in matched_events:
        for bm in ev.get("bookmakers", []):
            for m in bm.get("markets", []):
                if m.get("key") == "totals":
                    markets_found += 1

    log.warning("TOTAL MARKETS FOUND: %d", markets_found)

    if markets_found == 0:
        log.error("SONUÇ: EVENT VAR AMA TOTALS MARKET YOK")
        return {
            "ok": False,
            "reason": "NO_TOTALS_MARKET",
            "matched_events": len(matched_events),
        }

    log.warning("SONUÇ: ODDS DATA OK ✅")
    return {
        "ok": True,
        "events": len(matched_events),
        "totals_markets": markets_found,
    }
