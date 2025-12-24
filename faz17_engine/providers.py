from __future__ import annotations
import os, json, urllib.request, urllib.parse
from typing import Any, Dict, Optional, Tuple

DEFAULT_TIMEOUT = 12

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "").strip()
API_SPORT_KEY = os.getenv("API_SPORT_KEY", "").strip()

ODDS_API_BASE = os.getenv("ODDS_API_URL", "https://api.the-odds-api.com").rstrip("/")
API_SPORT_BASE = os.getenv("API_SPORT_URL", "https://v1.basketball.api-sports.io").rstrip("/")

def _http_get_json(url: str, headers=None, timeout: int = DEFAULT_TIMEOUT):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))

def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())

def _safe_float(x):
    try:
        return float(x)
    except Exception:
        return None

def fetch_from_odds_api(*, league: str, date_str: str, home: str, away: str) -> Tuple[Optional[Dict[str,Any]], Dict[str,Any]]:
    if not ODDS_API_KEY:
        return None, {"provider":"odds_api","used":False,"confidence":0.0,"reason":"missing_key"}

    league_map = {"NBA":"basketball_nba","EUROLEAGUE":"basketball_euroleague"}
    sport_key = league_map.get(league.upper())
    if not sport_key:
        return None, {"provider":"odds_api","used":False,"confidence":0.0,"reason":"unsupported_league"}

    url = f"{ODDS_API_BASE}/v4/sports/{sport_key}/odds?apiKey={ODDS_API_KEY}&regions=us&markets=totals"
    data = _http_get_json(url)

    hn, an = _norm(home), _norm(away)
    for ev in data:
        if {_norm(ev.get("home_team")), _norm(ev.get("away_team"))} == {hn, an}:
            for bm in ev.get("bookmakers", []):
                for m in bm.get("markets", []):
                    if m.get("key") == "totals":
                        pts = [_safe_float(o.get("point")) for o in m.get("outcomes", [])]
                        pts = [p for p in pts if p is not None]
                        if pts:
                            pts.sort()
                            return (
                                {"line": pts[len(pts)//2], "provider":"odds_api"},
                                {"provider":"odds_api","used":True,"confidence":0.85,"reason":"ok"}
                            )
    return None, {"provider":"odds_api","used":False,"confidence":0.0,"reason":"not_found"}
