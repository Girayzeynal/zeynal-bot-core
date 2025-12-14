# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import time
import logging
from typing import Any, Dict, Optional

log = logging.getLogger("zeynal-core")

try:
    import requests
except Exception as e:
    requests = None  # type: ignore
    _REQ_IMPORT_ERR = e
else:
    _REQ_IMPORT_ERR = None


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on", "y")


def _get_odds_api_key() -> Optional[str]:
    k = os.getenv("ODDS_API_KEY") or os.getenv("API_SPORT_KEY")  # sende ikisi de geçiyor
    if not k:
        return None
    k = k.strip()
    return k or None


def _odds_api_fetch(league: str, date_str: str, home: str, away: str) -> Dict[str, Any]:
    """
    Burada "Odds API" formatı sende nasıl kullanılıyorsa onu hedefliyoruz.
    requests yoksa net hata veriyoruz ama main çökmeyecek (safe wrapper yakalayacak).
    """
    if requests is None:
        raise RuntimeError(f"requests import failed: {_REQ_IMPORT_ERR}")

    # Bu URL/endpoint senin projede farklı olabilir.
    # Burada mantık: API çağır -> raw json dön.
    base = os.getenv("ODDS_API_BASE", "https://api.the-odds-api.com")
    sport_key = os.getenv("ODDS_API_SPORT", "basketball_nba")
    regions = os.getenv("ODDS_API_REGIONS", "us")
    markets = os.getenv("ODDS_API_MARKETS", "totals,h2h")
    odds_format = os.getenv("ODDS_API_ODDS_FORMAT", "decimal")

    api_key = _get_odds_api_key()
    if not api_key:
        raise RuntimeError("ODDS_API_KEY / API_SPORT_KEY missing")

    url = f"{base}/v4/sports/{sport_key}/odds"
    params = {
        "apiKey": api_key,
        "regions": regions,
        "markets": markets,
        "oddsFormat": odds_format,
        # date filtreleri sende farklı olabilir; core mantık çalışsın diye raw dönüyoruz
    }

    r = requests.get(url, params=params, timeout=12)
    r.raise_for_status()
    data = r.json()

    return {
        "provider": "odds_api",
        "ts": int(time.time()),
        "query": {"league": league, "date": date_str, "home": home, "away": away},
        "raw": data,
    }


def faz17_fetch_market(league: str, date_str: str, home: str, away: str) -> Dict[str, Any]:
    """
    Main.py'nin provider olarak çağıracağı fonksiyon BU.
    Safe wrapper (faz17_fetch_market_safe) bunu çağıracak.
    """
    use_odds = _env_bool("FAZ17_USE_ODDS_API", True) or bool(_get_odds_api_key())
    if use_odds:
        return _odds_api_fetch(league, date_str, home, away)

    # Eğer odds kapalıysa, en azından "used:false" döndür (main bunu debug'a basar)
    return {
        "provider": None,
        "ts": int(time.time()),
        "query": {"league": league, "date": date_str, "home": home, "away": away},
        "raw": None,
        "note": "no provider enabled",
    }


__all__ = ["faz17_fetch_market"]
