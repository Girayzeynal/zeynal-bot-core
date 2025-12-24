# faz17_engine/providers.py
from __future__ import annotations
import os, json, urllib.request, urllib.parse
from typing import Any, Dict, Optional, Tuple

DEFAULT_TIMEOUT = 12
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "").strip()
API_SPORT_KEY = os.getenv("API_SPORT_KEY", "").strip()
ODDS_API_BASE = os.getenv("ODDS_API_URL", "https://api.the-odds-api.com").rstrip("/")
API_SPORT_BASE = os.getenv("API_SPORT_URL", "https://v1.basketball.api-sports.io").rstrip("/")

def _http_get_json(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))

def _safe_float(x: Any) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except Exception:
        return None

def _normalize_team(s: str) -> str:
    return " ".join((s or "").strip().lower().split())

def _pick_totals_from_odds_api(event: Dict[str, Any]) -> Optional[float]:
    try:
        for bm in (event.get("bookmakers") or []):
            for m in (bm.get("markets") or []):
                if m.get("key") in ("totals", "alternate_totals"):
                    pts = [_safe_float(o.get("point")) for o in (m.get("outcomes") or [])]
                    pts = [p for p in pts if p is not None]
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
        return None, {"provider":"odds_api","used":False,"confidence":0.0,"reason":f"unsupported_league:{league}"}
    params = {"apiKey":ODDS_API_KEY,"regions":"us","markets":"totals","oddsFormat":"decimal"}
    url = f"{ODDS_API_BASE}/v4/sports/{sport_key}/odds?{urllib.parse.urlencode(params)}"
    try:
        data = _http_get_json(url)
    except Exception as e:
        return None, {"provider":"odds_api","used":False,"confidence":0.0,"reason":f"http_error:{e}"}
    home_norm, away_norm = _normalize_team(home), _normalize_team(away)
    event = next((ev for ev in data if ( _normalize_team(ev.get("home_team","")) , _normalize_team(ev.get("away_team","")) ) in [(home_norm,away_norm),(away_norm,home_norm)]), None)
    if not event:
        return None, {"provider":"odds_api","used":False,"confidence":0.0,"reason":"event_not_found"}
    line = _pick_totals_from_odds_api(event)
    return (
        {"totals_line":line,"provider":"odds_api","raw":event},
        {"provider":"odds_api","used":line is not None,"confidence":0.85 if line else 0.0,"reason":"ok" if line else "no_totals_market"}
    )

def fetch_from_api_sports(*, league: str, date_str: str, home: str, away: str) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    if not API_SPORT_KEY:
        return None, {"provider":"api_sports","used":False,"confidence":0.0,"reason":"missing_API_SPORT_KEY"}
    headers = {"x-apisports-key": API_SPORT_KEY}
    try:
        games = _http_get_json(f"{API_SPORT_BASE}/games?date={urllib.parse.quote(date_str)}", headers=headers)
    except Exception as e:
        return None, {"provider":"api_sports","used":False,"confidence":0.0,"reason":f"http_error:{e}"}
    home_norm, away_norm = _normalize_team(home), _normalize_team(away)
    game_id = None
    for g in games.get("response", []):
        teams = g.get("teams") or {}
        h_name = _normalize_team( (teams.get("home") or {}).get("name","") )
        a_name = _normalize_team( (teams.get("away") or {}).get("name","") )
        if {h_name,a_name} == {home_norm,away_norm}:
            game_id = g.get("id")
            break
    if not game_id:
        return None, {"provider":"api_sports","used":False,"confidence":0.0,"reason":"game_not_found"}
    try:
        odds = _http_get_json(f"{API_SPORT_BASE}/odds?game={game_id}", headers=headers)
    except Exception as e:
        return None, {"provider":"api_sports","used":False,"confidence":0.0,"reason":f"odds_http_error:{e}"}
    line = None
    try:
        for item in odds.get("response", []):
            for bm in item.get("bookmakers", []):
                for bet in bm.get("bets", []):
                    name = (bet.get("name","")).lower()
                    if "over/under" in name or "total" in name:
                        pts=[]
                        for val in bet.get("values", []):
                            for token in val.get("value","").replace(",",".").split():
                                f = _safe_float(token)
                                if f is not None:
                                    pts.append(f)
                        if pts:
                            pts.sort()
                            line = pts[len(pts)//2]
                            raise StopIteration
    except StopIteration:
        pass
    return (
        {"totals_line":line,"provider":"api_sports","raw":odds},
        {"provider":"api_sports","used":line is not None,"confidence":0.75 if line else 0.0,"reason":"ok" if line else "no_totals_found"}
    ) 
