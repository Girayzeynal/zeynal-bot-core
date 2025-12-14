# -*- coding: utf-8 -*-
"""
FAZ-17 Market Fetcher (SAFE)

- API-SPORT + ODDS-API üzerinden market verisi çeker
- Hata durumunda sessizce None döner
- FAZ-13 / FAZ-22 zincirini KIRMAZ
"""

from __future__ import annotations

import os
import logging
from typing import Any, Dict, Optional

import requests

log = logging.getLogger("FAZ17")

# ============================================================
# DEBUG ENV CHECK (SADECE FAZ-17 İÇİN)
# ============================================================

def _debug_env():
    log.warning(
        "[FAZ17 ENV] API_SPORT_KEY=%s | ODDS_API_KEY=%s",
        bool(os.getenv("API_SPORT_KEY")),
        bool(os.getenv("ODDS_API_KEY")),
    )

# ============================================================
# SAFE MARKET FETCH
# ============================================================

def faz17_fetch_market_safe(
    league: str,
    date_str: str,
    home: str,
    away: str,
) -> Optional[Dict[str, Any]]:
    """
    Market verisini güvenli şekilde çekmeye çalışır.
    Başarısız olursa None döner (pipeline kırılmaz).
    """

    # 🔴 DEBUG BAŞLANGIÇ NOKTASI
    _debug_env()
    log.warning(
        "[FAZ17] fetch_market_safe CALLED | %s | %s vs %s | %s",
        league,
        home,
        away,
        date_str,
    )

    odds_key = os.getenv("ODDS_API_KEY")
    api_sport_key = os.getenv("API_SPORT_KEY")

    if not odds_key and not api_sport_key:
        log.warning("[FAZ17] No API keys available → skip market")
        return None

    try:
        # ----------------------------------------------------
        # ODDS-API (PRIMARY – NBA için)
        # ----------------------------------------------------
        if odds_key and league.upper() == "NBA":
            url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
            params = {
                "apiKey": odds_key,
                "regions": "us",
                "markets": "totals,h2h",
                "oddsFormat": "decimal",
            }

            r = requests.get(url, params=params, timeout=10)
            log.warning("[FAZ17] ODDS_API status=%s", r.status_code)

            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and data:
                    return {
                        "provider": "ODDS_API",
                        "raw": data[:2],  # sample
                    }

        # ----------------------------------------------------
        # API-SPORT (FALLBACK)
        # ----------------------------------------------------
        if api_sport_key:
            url = "https://v1.basketball.api-sports.io/games"
            headers = {"x-apisports-key": api_sport_key}
            params = {"season": date_str[:4]}

            r = requests.get(url, headers=headers, params=params, timeout=10)
            log.warning("[FAZ17] API_SPORT status=%s", r.status_code)

            if r.status_code == 200:
                data = r.json()
                if data.get("response"):
                    return {
                        "provider": "API_SPORT",
                        "raw": data["response"][:2],
                    }

    except Exception as e:
        log.exception("[FAZ17] Market fetch error: %s", e)

    log.warning("[FAZ17] No market data resolved")
    return None
