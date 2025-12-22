 # ================================================================
# FAZ-17 MARKET — Odds API PRIMARY / API-Sports FALLBACK
# None yok; üst katman fallback uygular.
# ================================================================
from __future__ import annotations
import os, json, time, urllib.parse, urllib.request
from typing import Any, Dict, Optional, Tuple

def _now(): return int(time.time())

def _safe_float(x: Any) -> Optional[float]:
    try: return float(x)
    except Exception: return None

def _http_get_json(url: str, headers: Dict[str, str], timeout: int = 12) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", errors="ignore")
    try: return json.loads(raw)
    exceptexcept: return {"_raw": raw}

def _odds_url_with_key(base_url: str, api_key: str) -> str:
    if "apiKey=" in base_url or "apikey=" in base_url: return base_url
    joiner = "&" if "?" in base_url else "?"
    return f"{base_url}{joiner}apiKey={urllib.parse.quote(api_key)}"

def fetch_market_line_odds_api(league: str, date_str: str, home: str, away: str):
    key = (os.getenv("ODDS_API_KEY","") or "").strip()
    url = (os.getenv("ODDS_API_URL","") or "").strip()
    meta = {"provider":"odds_api","used":False,"reason":"","ts":_now()}
    if not key or not url:
        meta["reason"]="missing_odds_key_or_url"; return None, meta
    try:
        data = _http_get_json(_odds_url_with_key(url, key), headers={}, timeout=12)
        line = _safe_float(data.get("totals_line"))
        if line is None and isinstance(data, list) and data:
            first = data[0]; 
            if isinstance(first, dict):
                line = _safe_float(first.get("totals_line") or first.get("total_line") or first.get("line"))
        if line is None:
            meta["reason"]="no_line_in_odds"; return None, meta
        meta["used"]=True; meta["reason"]="ok"; 
        return float(line), meta
    except Exception as e:
        meta["reason"]=f"odds_err:{e}"; return None, meta

def fetch_market_line_api_sports(league: str, date_str: str, home: str, away: str):
    key = (os.getenv("API_SPORT_KEY","") or "").strip()
    base = (os.getenv("API_SPORT_URL","") or "").strip().rstrip("/")
    meta = {"provider":"api_sports","used":False,"reason":"","ts":_now()}
    if not key or not base:
        meta["reason"]="missing_api_sport_key_or_url"; return None, meta
    try:
        headers={"x-apisports-key": key}
        params = urllib.parse.urlencode({"league":league,"date":date_str,"home":home,"away":away})
        url = f"{base}?{params}" if "?" not in base else base
        data = _http_get_json(url, headers=headers, timeout=12)
        line = _safe_float(data.get("totals_line"))
        if line is None:
            resp = data.get("response")
            if isinstance(resp, list) and resp:
                first = resp[0]
                if isinstance(first, dict):
                    line = _safe_float(first.get("totals_line") or first.get("line"))
        if line is None:
            meta["reason"]="no_line_in_api_sports"; return None, meta
        meta["used"]=True; meta["reason"]="ok"; 
        return float(line), meta
    except Exception as e:
        meta["reason"]=f"api_sports_err:{e}"; return None, meta

def fetch_market(league: str, date_str: str, home: str, away: str):
    l1, m1 = fetch_market_line_odds_api(league, date_str, home, away)
    if l1 is not None:
        return {"provider":"odds_api","totals_line":l1,"ts":_now()}, {"market":{"used":True,"provider":"odds_api","reason":"ok"}}
    l2, m2 = fetch_market_line_api_sports(league, date_str, home, away)
    if l2 is not None:
        return {"provider":"api_sports","totals_line":l2,"ts":_now()}, {"market":{"used":True,"provider":"api_sports","reason":"ok"}}
    return {"provider":None,"totals_line":None,"ts":_now(),"meta":{"odds":m1,"api_sports":m2}}, {"market":{"used":False,"provider":None,"reason":"no_market_line"}}
