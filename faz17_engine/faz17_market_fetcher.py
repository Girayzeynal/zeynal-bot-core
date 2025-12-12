# faz17_engine/faz17_market_fetcher.py
# ================================================================
# FAZ-17 MARKET FETCHER v1.0
# - API-Sports (basketball) + The-Odds-API (optional)
# - Fly.io 512MB friendly
# - Safe cache (jsonl) + safe mkdir fallback
# ================================================================
from __future__ import annotations

import os
import json
import time
import logging
from typing import Any, Dict, Optional, Tuple

import requests

log = logging.getLogger("faz17-market")

# ---------------------------------------------------
# ENV
# ---------------------------------------------------
API_SPORT_KEY = os.getenv("API_BASK_KEY") or os.getenv("API_SPORTS_KEY") or ""
ODDS_API_KEY = os.getenv("ODDS_API_KEY") or ""

API_SPORT_BASE = os.getenv("API_BASK_BASE_URL", "https://v1.basketball.api-sports.io")
ODDS_BASE = os.getenv("ODDS_BASE_URL", "https://api.the-odds-api.com/v4")

TIMEOUT: Tuple[float, float] = (3.0, 8.0)

# ---------------------------------------------------
# Safe DATA_DIR (Fly volume vs UserLAnd)
# ---------------------------------------------------
def _pick_data_dir() -> str:
    # primary (Fly)
    primary = os.getenv("DATA_DIR", "/data")
    try:
        os.makedirs(primary, exist_ok=True)
        test = os.path.join(primary, ".w")
        with open(test, "w", encoding="utf-8") as f:
            f.write("1")
        try:
            os.remove(test)
        except Exception:
            pass
        return primary
    except Exception:
        # fallback (UserLAnd / local)
        fallback = os.path.join(os.getcwd(), "data")
        try:
            os.makedirs(fallback, exist_ok=True)
        except Exception:
            pass
        return fallback

DATA_DIR = _pick_data_dir()
FAZ17_DIR = os.path.join(DATA_DIR, "faz17")
try:
    os.makedirs(FAZ17_DIR, exist_ok=True)
except Exception:
    pass

MARKET_CACHE_PATH = os.path.join(FAZ17_DIR, "market_cache.jsonl")

# ---------------------------------------------------
# Helpers
# ---------------------------------------------------
def _safe_text(x: Any) -> str:
    try:
        return str(x).strip()
    except Exception:
        return ""

def _norm_team(s: str) -> str:
    s = _safe_text(s).lower()
    # Türkçe/aksanları kaba normalize et (minimal, safe)
    repl = {
        "ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u",
        "á": "a", "à": "a", "ä": "a",
        "é": "e", "è": "e", "ë": "e",
        "í": "i", "ì": "i", "ï": "i",
        "ó": "o", "ò": "o", "ï": "i",
        "ú": "u", "ù": "u",
        "â": "a", "ê": "e", "î": "i", "ô": "o", "û": "u",
    }
    for a, b in repl.items():
        s = s.replace(a, b)
    s = s.replace(".", " ").replace("-", " ").replace("_", " ")
    s = " ".join(s.split())
    return s

def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        if isinstance(x, (int, float)):
            return float(x)
        xs = str(x).strip().replace(",", ".")
        return float(xs)
    except Exception:
        return None

def _append_cache(obj: Dict[str, Any]) -> None:
    try:
        with open(MARKET_CACHE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    except Exception:
        pass

def _api_sports_headers() -> Dict[str, str]:
    return {"x-apisports-key": API_SPORT_KEY} if API_SPORT_KEY else {}

# ---------------------------------------------------
# League mapping (extend as needed)
# ---------------------------------------------------
def _odds_sport_key(league: str) -> Optional[str]:
    lg = _safe_text(league).lower()
    # The-Odds-API spor anahtarları değişebilir; bu “best-effort mapping”.
    if "euroleague" in lg:
        return "basketball_euroleague"
    if "nba" in lg:
        return "basketball_nba"
    return None

# ---------------------------------------------------
# API-Sports: get games list, match teams, extract scores
# ---------------------------------------------------
def _api_sports_find_game_id(league: str, date_str: str, home: str, away: str) -> Optional[int]:
    if not API_SPORT_KEY:
        return None
    try:
        # Not: API-Sports “league” paramı çoğu zaman numeric ID ister.
        # Senin projede league string’ini başka yerde map’liyor olabilirsin.
        # Burada string gelirse gene de deneriz.
        params = {"date": date_str, "league": league}
        r = requests.get(
            f"{API_SPORT_BASE}/games",
            headers=_api_sports_headers(),
            params=params,
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return None
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        resp = data.get("response") or []
        nh = _norm_team(home)
        na = _norm_team(away)
        for g in resp:
            try:
                teams = g.get("teams") or {}
                hname = _norm_team((teams.get("home") or {}).get("name"))
                aname = _norm_team((teams.get("away") or {}).get("name"))
                if hname and aname and ((hname == nh and aname == na) or (hname == na and aname == nh)):
                    gid = g.get("id")
                    if isinstance(gid, int):
                        return gid
            except Exception:
                continue
        return None
    except Exception:
        return None

def _api_sports_live_total(game_id: int) -> Optional[float]:
    if not API_SPORT_KEY or not game_id:
        return None
    try:
        r = requests.get(
            f"{API_SPORT_BASE}/games",
            headers=_api_sports_headers(),
            params={"id": game_id},
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return None
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        resp = (data.get("response") or [])
        if not resp:
            return None
        g = resp[0]
        scores = g.get("scores") or {}
        h = _safe_float((scores.get("home") or {}).get("total"))
        a = _safe_float((scores.get("away") or {}).get("total"))
        if h is None or a is None:
            return None
        return float(h + a)
    except Exception:
        return None

# ---------------------------------------------------
# The-Odds-API: totals (best effort)
# ---------------------------------------------------
def _odds_api_total_line(league: str, home: str, away: str) -> Optional[float]:
    if not ODDS_API_KEY:
        return None
    sport_key = _odds_sport_key(league)
    if not sport_key:
        return None

    try:
        # markets=totals ile total çizgisi bulunabilir.
        # region/oddsFormat ayarları da var ama burada minimal.
        r = requests.get(
            f"{ODDS_BASE}/sports/{sport_key}/odds",
            params={
                "apiKey": ODDS_API_KEY,
                "markets": "totals",
                "regions": "eu",
                "oddsFormat": "decimal",
            },
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return None

        arr = r.json() if r.headers.get("content-type", "").startswith("application/json") else []
        nh = _norm_team(home)
        na = _norm_team(away)

        # events listesi içinde match bul
        for ev in arr:
            try:
                home_team = _norm_team(ev.get("home_team"))
                away_team = _norm_team(ev.get("away_team"))
                if not home_team or not away_team:
                    continue
                if not ((home_team == nh and away_team == na) or (home_team == na and away_team == nh)):
                    continue

                # bookmakers -> markets -> outcomes -> point
                bks = ev.get("bookmakers") or []
                for bk in bks:
                    markets = bk.get("markets") or []
                    for m in markets:
                        if (m.get("key") or "") != "totals":
                            continue
                        outs = m.get("outcomes") or []
                        for o in outs:
                            pt = _safe_float(o.get("point"))
                            if pt is not None and pt > 0:
                                return float(pt)
            except Exception:
                continue
        return None
    except Exception:
        return None

# ---------------------------------------------------
# Public API: fetch market snapshot
# ---------------------------------------------------
def faz17_fetch_market(
    league: str,
    date_str: str,
    home: str,
    away: str,
    want_live: bool = False,
) -> Dict[str, Any]:
    """
    Returns:
      {
        "ok": bool,
        "league": str,
        "date": str,
        "home": str,
        "away": str,
        "total_line": float|None,     # prematch total line
        "live_total": float|None,     # live current total score
        "src": { "api_sports": bool, "odds_api": bool },
        "ts": int
      }
    """
    ts = int(time.time())
    out: Dict[str, Any] = {
        "ok": False,
        "league": league,
        "date": date_str,
        "home": home,
        "away": away,
        "total_line": None,
        "live_total": None,
        "src": {"api_sports": False, "odds_api": False},
        "ts": ts,
    }

    # 1) prematch total line (Odds API)
    total_line = _odds_api_total_line(league, home, away)
    if total_line is not None:
        out["total_line"] = total_line
        out["src"]["odds_api"] = True

    # 2) live total (API-Sports)
    if want_live:
        gid = _api_sports_find_game_id(league, date_str, home, away)
        if gid:
            lt = _api_sports_live_total(gid)
            if lt is not None:
                out["live_total"] = lt
                out["src"]["api_sports"] = True

    out["ok"] = bool(out["total_line"] is not None or out["live_total"] is not None)

    # cache (best effort)
    _append_cache(out)
    return out

__all__ = ["faz17_fetch_market"]
