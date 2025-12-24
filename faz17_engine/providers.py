from __future__ import annotations
import os, json, urllib.request, urllib.parse
from typing import Any, Dict, Optional, Tuple

DEFAULT_TIMEOUT = 12

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "").strip()
ODDS_API_BASE = os.getenv("ODDS_API_URL", "https://api.the-odds-api.com").rstrip("/")

def _http_get_json(url: str, headers=None, timeout: int = DEFAULT_TIMEOUT):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))

def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())

def _safe_float(x: Any) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except Exception:
        return None

def _pick_totals_line(ev: Dict[str, Any]) -> Optional[float]:
    try:
        for bm in ev.get("bookmakers", []) or []:
            for m in bm.get("markets", []) or []:
                if m.get("key") == "totals":
                    pts = []
                    for o in m.get("outcomes", []) or []:
                        p = _safe_float(o.get("point"))
                        if p is not None:
                            pts.append(p)
                    if pts:
                        pts.sort()
                        return pts[len(pts)//2]
        return None
    except Exception:
        return None

def fetch_from_odds_api(*, league: str, date_str: str, home: str, away: str) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    if not ODDS_API_KEY:
        return None, {"provider":"odds_api","used":False,"confidence":0.0,"reason":"missing_ODDS_API_KEY"}

    league_map = {"NBA":"basketball_nba","EUROLEAGUE":"basketball_euroleague"}
    sport_key = league_map.get(league.upper())
    if not sport_key:
        return None, {"provider":"odds_api","used":False,"confidence":0.0,"reason":"unsupported_league"}

    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": "totals",
        "oddsFormat": "decimal",
    }
    url = f"{ODDS_API_BASE}/v4/sports/{sport_key}/odds?{urllib.parse.urlencode(params)}"

    try:
        data = _http_get_json(url)
    except Exception as e:
        return None, {"provider":"odds_api","used":False,"confidence":0.0,"reason":f"http_error:{e}"}

    hn, an = _norm(home), _norm(away)
    event = None
    for ev in data if isinstance(data, list) else []:
        if {_norm(ev.get("home_team")), _norm(ev.get("away_team"))} == {hn, an}:
            event = ev
            break

    if not event:
        return None, {"provider":"odds_api","used":False,"confidence":0.0,"reason":"event_not_found"}

    line = _pick_totals_line(event)
    used = line is not None

    market = {"totals_line": line, "provider": "odds_api", "raw": event}
    meta = {"provider":"odds_api","used":used,"confidence":0.85 if used else 0.0,"reason":"ok" if used else "no_totals_market"}
    return market, meta 
