# faz17_engine/faz17_market.py
from __future__ import annotations
import os
import json
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

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

def fetch_market_line_odds_api(league: str, date_str: str, home: str, away: str) -> Tuple[Optional[float], Dict[str, Any]]:
    key = (os.getenv("ODDS_API_KEY", "") or "").strip()
    url = (os.getenv("ODDS_API_URL", "") or "").strip()
    meta = {"provider": "odds_api", "used": False, "reason": "", "ts": _now()}

    if not key or not url:
        meta["reason"] = "missing_odds_key_or_url"
        return None, meta

    # Mode: if URL already contains apiKey, don't add; else append apiKey=...
    u = url
    if "apiKey=" not in u and "apikey=" not in u:
        joiner = "&" if "?" in u else "?"
        u = f"{u}{joiner}apiKey={urllib.parse.quote(key)}"

    try:
        data = _http_get_json(u, headers={}, timeout=12)
        # Case 1: custom endpoint returns totals_line directly
        line = _safe_float(data.get("totals_line"))

        # Case 2: list response (try simple scan)
        if line is None and isinstance(data, list) and data:
            # try first element
            first = data[0]
            if isinstance(first, dict):
                line = _safe_float(first.get("totals_line") or first.get("total_line") or first.get("line"))

        if line is None:
            meta["reason"] = "no_line_in_odds_response"
            return None, meta

        meta["used"] = True
        meta["reason"] = "ok"
        return float(line), meta
    except Exception as e:
        meta["reason"] = f"odds_api_error:{e}"
        return None, meta

def fetch_market_line_api_sports(league: str, date_str: str, home: str, away: str) -> Tuple[Optional[float], Dict[str, Any]]:
    key = (os.getenv("API_SPORT_KEY", "") or "").strip()
    base = (os.getenv("API_SPORT_URL", "") or "").strip()
    meta = {"provider": "api_sports", "used": False, "reason": "", "ts": _now()}

    if not key or not base:
        meta["reason"] = "missing_api_sport_key_or_url"
        return None, meta

    # Minimal: status endpoint won't give line; we assume your API_SPORT_URL points to your odds endpoint or proxy.
    # If you have a dedicated odds endpoint, set API_SPORT_URL to it.
    try:
        headers = {"x-apisports-key": key}
        params = urllib.parse.urlencode({"league": league, "date": date_str, "home": home, "away": away})
        url = f"{base}?{params}" if "?" not in base else base
        data = _http_get_json(url, headers=headers, timeout=12)
        line = _safe_float(data.get("totals_line"))

        if line is None:
            # try nested response
            resp = data.get("response")
            if isinstance(resp, list) and resp:
                first = resp[0]
                if isinstance(first, dict):
                    line = _safe_float(first.get("totals_line") or first.get("line"))

        if line is None:
            meta["reason"] = "no_line_in_api_sports"
            return None, meta

        meta["used"] = True
        meta["reason"] = "ok"
        return float(line), meta
    except Exception as e:
        meta["reason"] = f"api_sports_error:{e}"
        return None, meta

def fetch_market(
    league: str,
    date_str: str,
    home: str,
    away: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    ZORUNLU market line üretir:
      Odds API -> line
      olmazsa API-Sports -> line
      olmazsa line=None (ama üst katman fallback uygular)
    """
    line1, meta1 = fetch_market_line_odds_api(league, date_str, home, away)
    if line1 is not None:
        return {"provider": "odds_api", "totals_line": line1, "ts": _now()}, {"market": {"used": True, "provider":"odds_api", "reason":"ok"}}

    line2, meta2 = fetch_market_line_api_sports(league, date_str, home, away)
    if line2 is not None:
        return {"provider": "api_sports", "totals_line": line2, "ts": _now()}, {"market": {"used": True, "provider":"api_sports", "reason":"ok"}}

    # no line -> let FAZ-13 fallback (but we keep reason)
    return {"provider": None, "totals_line": None, "ts": _now(), "meta": {"odds": meta1, "api_sports": meta2}}, {"market": {"used": False, "provider": None, "reason": "no_market_line"}} 
