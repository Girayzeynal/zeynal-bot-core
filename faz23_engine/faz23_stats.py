# faz23_engine/faz23_stats.py
from __future__ import annotations

import os
import json
import time
import urllib.parse
import urllib.request
from typing import Dict, Any, Optional, Tuple, List

from .faz23_team_map import map_team

def _now() -> int:
    return int(time.time())

def _http_get_json(url: str, headers: Dict[str, str], timeout: int = 12) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    try:
        return json.loads(raw)
    except Exception:
        return {"_raw": raw}

def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None

def _api_sports_headers() -> Dict[str, str]:
    key = (os.getenv("API_SPORT_KEY", "") or "").strip()
    return {"x-apisports-key": key} if key else {}

def _api_sports_base() -> str:
    # Örn: https://v1.basketball.api-sports.io
    return (os.getenv("API_SPORT_URL", "") or "").strip().rstrip("/")

# Fail-safe priors (NOT league avg; just "don’t return None")
_FAILSAFE_TEAM_PRIOR = {
    "NBA": 111.0,
    "EUROLEAGUE": 80.0,
    "ACB": 83.0,
    "BSL": 82.0,
    "VTB": 84.0,
    "BBL": 83.0,
    "LBA": 81.0,
    "LNB": 80.0,
    "ABA": 82.0,
    "A1": 78.0,
    "NBL": 88.0,
    "LKL": 79.0,
    "CBA": 106.0,
    "DEFAULT": 85.0,
}

def _prior_team_avg(league: str) -> float:
    return float(_FAILSAFE_TEAM_PRIOR.get((league or "").upper(), _FAILSAFE_TEAM_PRIOR["DEFAULT"]))

def fetch_team_last_games_avg_points(
    league: str,
    team_name: str,
    side: str,
    n: int = 5
) -> Tuple[float, List[str]]:
    """
    API-Sports üzerinden takımın son N maçtaki attığı sayı ortalamasını döndürür.
    side: "home" veya "away" -> filtrelemek için kullanılır (varsa)
    Dönüş: (avg_points, notes[])
    """
    lg = (league or "").upper()
    base = _api_sports_base()
    headers = _api_sports_headers()
    notes: List[str] = []

    # API yoksa fail-safe
    if not base or not headers:
        notes.append("api_sports_missing_env")
        return _prior_team_avg(lg), notes

    mapped = map_team(lg, team_name, "api_sports")

    # ⚠️ API-Sports endpoint'leri hesap planına göre değişebilir.
    # En genel yaklaşım: games endpoint’i + team filter.
    # Eğer senin API_SPORT_URL zaten bir proxy ise bu yine çalışır.
    # Deneme 1: /games?team=...&last=N
    try:
        params = urllib.parse.urlencode({"team": mapped, "last": str(n)})
        url = f"{base}/games?{params}"
        data = _http_get_json(url, headers=headers, timeout=12)

        resp = data.get("response")
        if isinstance(resp, list) and resp:
            pts: List[float] = []
            for g in resp:
                if not isinstance(g, dict):
                    continue
                # API-Sports basketball scores structure:
                # g["scores"]["home"]["total"], g["scores"]["away"]["total"]
                scores = g.get("scores", {})
                if not isinstance(scores, dict):
                    continue
                home_total = _safe_float(((scores.get("home") or {}) if isinstance(scores.get("home"), dict) else {}).get("total"))
                away_total = _safe_float(((scores.get("away") or {}) if isinstance(scores.get("away"), dict) else {}).get("total"))

                # side filter (best effort)
                # If this team is listed as home in g["teams"]["home"]["name"]
                teams = g.get("teams", {})
                home_name = None
                away_name = None
                if isinstance(teams, dict):
                    hn = teams.get("home")
                    an = teams.get("away")
                    if isinstance(hn, dict):
                        home_name = (hn.get("name") or "")
                    if isinstance(an, dict):
                        away_name = (an.get("name") or "")

                # Determine team points
                team_points = None
                if home_name and str(home_name).lower().strip() == str(mapped).lower().strip():
                    team_points = home_total
                    if side == "away":
                        continue
                elif away_name and str(away_name).lower().strip() == str(mapped).lower().strip():
                    team_points = away_total
                    if side == "home":
                        continue

                if team_points is not None:
                    pts.append(float(team_points))

            if pts:
                avg = sum(pts) / len(pts)
                notes.append(f"api_sports_games_ok:n={len(pts)}")
                return float(round(avg, 2)), notes
    except Exception as e:
        notes.append(f"api_sports_games_err:{e}")

    # fail-safe prior
    notes.append("api_sports_fallback_prior")
    return _prior_team_avg(lg), notes

def fetch_injuries_count(
    league: str,
    team_name: str,
) -> Tuple[int, List[str]]:
    """
    Injury count best-effort.
    Eğer endpoint yoksa 0 döner; None yok.
    """
    lg = (league or "").upper()
    base = _api_sports_base()
    headers = _api_sports_headers()
    notes: List[str] = []

    if not base or not headers:
        notes.append("api_sports_missing_env")
        return 0, notes

    mapped = map_team(lg, team_name, "api_sports")

    # Deneme: /injuries?team=...
    try:
        params = urllib.parse.urlencode({"team": mapped})
        url = f"{base}/injuries?{params}"
        data = _http_get_json(url, headers=headers, timeout=12)
        resp = data.get("response")
        if isinstance(resp, list):
            notes.append("api_sports_injuries_ok")
            return int(len(resp)), notes
    except Exception as e:
        notes.append(f"api_sports_injuries_err:{e}")

    return 0, notes

def build_context_for_match(
    league: str,
    home: str,
    away: str,
    date_str: str,
    last_n: int = 5,
) -> Dict[str, Any]:
    """
    FAZ-13/22 için context üretir.
    None/Unknown yok; fail-safe prior kullanılır.
    """
    home_avg, n1 = fetch_team_last_games_avg_points(league, home, side="home", n=last_n)
    away_avg, n2 = fetch_team_last_games_avg_points(league, away, side="away", n=last_n)

    h_inj, n3 = fetch_injuries_count(league, home)
    a_inj, n4 = fetch_injuries_count(league, away)

    return {
        "team_stats": {
            "home_avg_for": home_avg,
            "away_avg_for": away_avg,
            "source": "api_sports_best_effort",
            "notes": n1 + n2,
        },
        "injuries": {
            "count": int(h_inj + a_inj),
            "home": int(h_inj),
            "away": int(a_inj),
            "notes": n3 + n4,
        },
        "news": {
            "count": 0,
            "items": [],
            "notes": [],
        },
        "meta": {
            "league": (league or "").upper(),
            "date": date_str,
            "ts": _now(),
        }
    } 
