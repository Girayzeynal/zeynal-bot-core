# -*- coding: utf-8 -*-
"""
FAZ-17 Market Fetcher (Safe + Fallback)
- provider_fetch_func opsiyonel: main.py injection yapsa bile patlamaz
- providers.py yoksa bile The Odds API fallback ile çalışır
- Fly.io / 512MB uyumlu (hafif cache, kısa timeout)
"""

from __future__ import annotations

import os
import time
import logging
from typing import Any, Dict, Optional, Tuple, Callable, List

import requests

log = logging.getLogger("zeynal-core")

ODDS_API_KEY = (os.getenv("ODDS_API_KEY", "") or "").strip()
API_SPORT_KEY = (os.getenv("API_SPORT_KEY", "") or "").strip()

# ------------------------------------------------
# Debug env (senin istediğin)
# ------------------------------------------------
def _debug_env() -> None:
    log.warning(
        "[FAZ17 ENV] API_SPORT_KEY=%s ODDS_API_KEY=%s",
        bool(API_SPORT_KEY),
        bool(ODDS_API_KEY),
    )


# ------------------------------------------------
# ODDS: sports list cache
# ------------------------------------------------
_ODDS_SPORTS_CACHE: Dict[str, Any] = {"ts": 0, "data": []}

def _odds_list_sports(ttl_sec: int = 6 * 3600) -> List[Dict[str, Any]]:
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
    family = (family or "").lower()
    sports_list = _odds_list_sports()
    candidates: List[Tuple[int, str]] = []

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
            candidates.append((score, str(s["key"])))

    candidates.sort(reverse=True, key=lambda x: x[0])
    return candidates[0][1] if candidates else None


# ------------------------------------------------
# Fallback provider (ODDS API)
# ------------------------------------------------
def _fallback_odds_provider(league: str, date_str: str, home: str, away: str) -> Dict[str, Any]:
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
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    return {"used": True, "odds": r.json(), "src": {"provider": sport_key, "mode": "fallback_odds"}}


# ------------------------------------------------
# SAFE FETCH (main.py injection uyumlu)
# ------------------------------------------------
ProviderFunc = Callable[..., Any]

def faz17_fetch_market_safe(
    *,
    league: str,
    date_str: str,
    home: str,
    away: str,
    provider_fetch_func: Optional[ProviderFunc] = None,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """
    Returns:
      (market_data_or_none, market_meta_dict)

    Notlar:
    - provider_fetch_func verilirse onu dener.
    - verilmezse providers.py içinden bulmaya çalışır.
    - o da yoksa The Odds API fallback ile devam eder.
    - Asla exception fırlatıp botu susturmaz.
    """
    _debug_env()
    log.warning("[FAZ17] fetch_market_safe CALLED")

    meta: Dict[str, Any] = {"used": False, "reason": "not_called", "provider": None, "ts": int(time.time())}

    # 1) external provider injection
    if provider_fetch_func is not None:
        try:
            out = provider_fetch_func(league=league, date_str=date_str, home=home, away=away)
            if isinstance(out, dict):
                meta.update({"used": bool(out.get("used", True)), "reason": "provider_ok", "provider": "injected"})
                return out, meta
            meta.update({"used": False, "reason": "provider_bad_type", "provider": "injected"})
            return None, meta
        except Exception as e:
            meta.update({"used": False, "reason": f"provider_exception: {e}", "provider": "injected"})
            # fallback devam

    # 2) try import local providers.py
    try:
        from .providers import faz17_fetch_market as _prov  # type: ignore
        try:
            out = _prov(league=league, date_str=date_str, home=home, away=away)  # type: ignore
            if isinstance(out, dict):
                meta.update({"used": bool(out.get("used", True)), "reason": "providers_ok", "provider": "providers.py"})
                return out, meta
            meta.update({"used": False, "reason": "providers_bad_type", "provider": "providers.py"})
        except Exception as e:
            meta.update({"used": False, "reason": f"providers_exception: {e}", "provider": "providers.py"})
    except Exception as e:
        meta.update({"used": False, "reason": f"providers_import_fail: {e}", "provider": "providers.py"})

    # 3) fallback odds
    try:
        out = _fallback_odds_provider(league=league, date_str=date_str, home=home, away=away)
        if isinstance(out, dict) and out.get("used"):
            meta.update({"used": True, "reason": "fallback_odds_ok", "provider": out.get("src", {}).get("provider")})
            return out, meta
        meta.update({"used": False, "reason": out.get("error") or "fallback_odds_failed", "provider": None})
        return out if isinstance(out, dict) else None, meta
    except Exception as e:
        meta.update({"used": False, "reason": f"fallback_odds_exception: {e}", "provider": None})
        return None, meta
