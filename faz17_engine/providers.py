# faz17_engine/providers.py
from __future__ import annotations
import os
import time
import json
from typing import Any, Dict, Optional, Tuple
import urllib.request
import urllib.parse

def _now() -> int:
    return int(time.time())

def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None

def _http_get_json(url: str, headers: Dict[str, str], timeout: int = 12) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    try:
        return json.loads(raw)
    except Exception:
        return {"_raw": raw}

# -------------------------
# ODDS API (PRIMARY)
# -------------------------
def fetch_odds_api_totals(
    league: str,
    date_str: str,
    home: str,
    away: str,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """
    Minimal totals_line fetcher.
    Env:
      ODDS_API_KEY (required)
      ODDS_API_URL (optional)  -> if empty uses a placeholder and returns no data
    """
    api_key = (os.getenv("ODDS_API_KEY", "") or "").strip()
    base_url = (os.getenv("ODDS_API_URL", "") or "").strip()

    meta = {"provider": "odds_api", "used": False, "confidence": 0.0, "reason": "", "ts": _now()}

    if not api_key or not base_url:
        meta["reason"] = "missing_odds_api_key_or_url"
        return None, meta

    # URL params
    params = urllib.parse.urlencode({
        "league": league,
        "date": date_str,
        "home": home,
        "away": away,
    })
    url = f"{base_url}?{params}"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        data = _http_get_json(url, headers=headers, timeout=12)
        # Expected minimal fields:
        # totals_line / over_odds / under_odds
        totals_line = _safe_float(data.get("totals_line"))
        if totals_line is None:
            # alternative keys
            totals_line = _safe_float(data.get("total_line") or data.get("line") or data.get("totals"))

        market = {
            "provider": "odds_api",
            "totals_line": totals_line,
            "over_odds": _safe_float(data.get("over_odds")),
            "under_odds": _safe_float(data.get("under_odds")),
            "book": data.get("book"),
            "ts": _now(),
            "raw": data,
        }

        if totals_line is not None:
            meta["used"] = True
            meta["confidence"] = 0.70
            meta["reason"] = "ok"
            return market, meta

        meta["reason"] = "no_totals_line"
        return market, meta
    except Exception as e:
        meta["reason"] = f"odds_api_error:{e}"
        return None, meta

# -------------------------
# API-SPORTS (FALLBACK)
# -------------------------
def fetch_api_sports_totals(
    league: str,
    date_str: str,
    home: str,
    away: str,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """
    Fallback totals_line fetcher.
    Env:
      API_SPORT_KEY (required)
      API_SPORT_URL (optional)
    """
    key = (os.getenv("API_SPORT_KEY", "") or "").strip()
    base_url = (os.getenv("API_SPORT_URL", "") or "").strip()

    meta = {"provider": "api_sports", "used": False, "confidence": 0.0, "reason": "", "ts": _now()}

    if not key or not base_url:
        meta["reason"] = "missing_api_sport_key_or_url"
        return None, meta

    params = urllib.parse.urlencode({
        "league": league,
        "date": date_str,
        "home": home,
        "away": away,
    })
    url = f"{base_url}?{params}"
    headers = {"x-apisports-key": key}

    try:
        data = _http_get_json(url, headers=headers, timeout=12)

        # API-Sports response structures vary; we support a few common patterns
        totals_line = None

        # Pattern A: direct field
        totals_line = _safe_float(data.get("totals_line"))

        # Pattern B: nested response list
        if totals_line is None:
            resp = data.get("response")
            if isinstance(resp, list) and resp:
                first = resp[0]
                if isinstance(first, dict):
                    totals_line = _safe_float(
                        first.get("totals_line") or
                        first.get("line") or
                        (first.get("odds") or {}).get("totals_line")
                    )

        market = {
            "provider": "api_sports",
            "totals_line": totals_line,
            "over_odds": None,
            "under_odds": None,
            "book": None,
            "ts": _now(),
            "raw": data,
        }

        if totals_line is not None:
            meta["used"] = True
            meta["confidence"] = 0.55
            meta["reason"] = "ok"
            return market, meta

        meta["reason"] = "no_totals_line"
        return market, meta
    except Exception as e:
        meta["reason"] = f"api_sports_error:{e}"
        return None, meta

# -------------------------
# Unified provider
# -------------------------
def faz17_fetch_market(
    *,
    league: str,
    date_str: str,
    home: str,
    away: str,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """
    Primary: Odds API
    Fallback: API-Sports
    """
    m1, meta1 = fetch_odds_api_totals(league, date_str, home, away)
    if meta1.get("used"):
        return m1, meta1

    m2, meta2 = fetch_api_sports_totals(league, date_str, home, away)
    if meta2.get("used"):
        return m2, meta2

    # none
    return None, {"provider": None, "used": False, "confidence": 0.0, "reason": "no_market", "ts": _now()}
