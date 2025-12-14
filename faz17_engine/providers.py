# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import time
import logging
from typing import Any, Dict, Optional, Tuple

import requests

log = logging.getLogger("zeynal-core")

ODDS_API_KEY = (os.getenv("ODDS_API_KEY", "") or "").strip()


# -------------------------
# OddsAPI: sport key cache
# -------------------------
_ODDS_SPORTS_CACHE: Dict[str, Any] = {"ts": 0, "data": []}


def _odds_list_sports(ttl_sec: int = 6 * 3600):
    now = time.time()
    if _ODDS_SPORTS_CACHE["data"] and (now - _ODDS_SPORTS_CACHE["ts"] < ttl_sec):
        return _ODDS_SPORTS_CACHE["data"]

    if not ODDS_API_KEY:
        return []

    url = "https://api.the-odds-api.com/v4/sports"
    r = requests.get(url, params={"apiKey": ODDS_API_KEY}, timeout=10)
    r.raise_for_status()
    data = r.json()

    _ODDS_SPORTS_CACHE["ts"] = now
    _ODDS_SPORTS_CACHE["data"] = data
    return data


def _pick_sport_key_for_family(family: str) -> Optional[str]:
    family = (family or "").lower().strip()
    sports_list = _odds_list_sports()

    candidates = []
    for s in sports_list:
        key = (s.get("key") or "").lower()
        title = (s.get("title") or "").lower()
        group = (s.get("group") or "").lower()

        score = 0
        if "basketball" in group or "basketball" in title:
            score += 2
        if family and (family in title or family in key):
            score += 3

        if score > 0 and s.get("key"):
            candidates.append((score, s["key"]))

    candidates.sort(reverse=True, key=lambda x: x[0])
    return candidates[0][1] if candidates else None


# -------------------------
# Provider: raw market fetch
# -------------------------
def faz17_fetch_market(
    league: str,
    date_str: str,
    home: str,
    away: str,
    timeout: int = 10,
) -> Dict[str, Any]:
    """
    Raw market fetch (provider).
    Şu an ODDS API kullanıyor.
    """
    if not ODDS_API_KEY:
        return {"used": False, "error": "ODDS_API_KEY missing", "src": {}}

    sport_key = _pick_sport_key_for_family(league)
    if not sport_key:
        return {"used": False, "error": f"No ODDS sport key for family={league}", "src": {}}

    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us,eu",
        "markets": "h2h,totals",
        "dateFormat": "iso",
    }

    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    data = r.json()

    return {
        "used": True,
        "provider": "odds_api",
        "sport_key": sport_key,
        "odds": data,
    }


# -------------------------
# Safe wrapper: never crash
# -------------------------
def faz17_fetch_market_safe(
    league: str,
    date_str: str,
    home: str,
    away: str,
    provider_fetch_func=None,
    timeout: int = 10,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """
    Returns:
      market_data (dict or None),
      market_meta (always dict)
    """
    meta: Dict[str, Any] = {
        "used": False,
        "reason": "not_called",
        "provider": None,
        "ts": int(time.time()),
    }

    try:
        fetcher = provider_fetch_func or faz17_fetch_market
        out = fetcher(league=league, date_str=date_str, home=home, away=away, timeout=timeout)

        if isinstance(out, dict) and out.get("used"):
            meta.update({"used": True, "reason": "ok", "provider": out.get("provider") or out.get("sport_key")})
            return out, meta

        meta.update({"used": False, "reason": out.get("error") if isinstance(out, dict) else "provider_returned_non_dict"})
        return None, meta

    except Exception as e:
        meta.update({"used": False, "reason": f"exception: {e}"})
        return None, meta
