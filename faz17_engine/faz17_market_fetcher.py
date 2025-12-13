# faz17_engine/faz17_market_fetcher.py
# ================================================================
# FAZ-17 MARKET FETCHER v2.0 (FINAL PATCH)
# - API-Sports (basketball) + The-Odds-API (optional)
# - Multi-source fusion + confidence + reason codes
# - Fly.io 512MB friendly
# - Safe cache (jsonl)
# ================================================================

from __future__ import annotations

import os
import json
import time
import logging
from typing import Any, Dict, Optional, Tuple, List

import requests

log = logging.getLogger("faz17-market")

API_SPORT_KEY = os.getenv("API_BASK_KEY") or os.getenv("API_SPORTS_KEY") or ""
ODDS_API_KEY = os.getenv("ODDS_API_KEY") or ""

API_SPORT_BASE = os.getenv("API_BASK_BASE_URL", "https://v1.basketball.api-sports.io")
ODDS_BASE = os.getenv("ODDS_BASE_URL", "https://api.the-odds-api.com/v4")

TIMEOUT: Tuple[float, float] = (3.0, 8.0)

# ---------------------------------------------------
# Safe DATA_DIR
# ---------------------------------------------------
def _pick_data_dir() -> str:
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
    repl = {
        "ç": "c","ğ": "g","ı": "i","ö": "o","ş": "s","ü": "u",
        "á": "a","à": "a","ä": "a","é": "e","è": "e","ë": "e",
        "í": "i","ì": "i","ï": "i","ó": "o","ò": "o","ú": "u","ù": "u",
        "â": "a","ê": "e","î": "i","ô": "o","û": "u",
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
        obj = dict(obj)
        obj["ts"] = int(time.time())
        with open(MARKET_CACHE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    except Exception:
        pass

def _read_cache_last(league: str, date_str: str, home: str, away: str, max_scan: int = 200) -> Optional[Dict[str, Any]]:
    try:
        if not os.path.exists(MARKET_CACHE_PATH):
            return None
        nh, na = _norm_team(home), _norm_team(away)
        lg = _safe_text(league).lower()
        # sondan geriye doğru tarama (jsonl)
        with open(MARKET_CACHE_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in reversed(lines[-max_scan:]):
            try:
                obj = json.loads(line)
                if _safe_text(obj.get("date_str")) != _safe_text(date_str):
                    continue
                if _safe_text(obj.get("league")).lower() != lg:
                    continue
                if _norm_team(obj.get("home", "")) == nh and _norm_team(obj.get("away", "")) == na:
                    return obj
            except Exception:
                continue
        return None
    except Exception:
        return None

def _api_sports_headers() -> Dict[str, str]:
    return {"x-apisports-key": API_SPORT_KEY} if API_SPORT_KEY else {}

# ---------------------------------------------------
# Odds key mapping
# ---------------------------------------------------
def _odds_sport_key(league: str) -> Optional[str]:
    lg = _safe_text(league).lower()
    if "euroleague" in lg:
        return "basketball_euroleague"
    if "nba" in lg:
        return "basketball_nba"
    return None

# ---------------------------------------------------
# API-Sports
# ---------------------------------------------------
def _api_sports_find_game_id(league: str, date_str: str, home: str, away: str) -> Optional[int]:
    if not API_SPORT_KEY:
        return None
    try:
        params = {"date": date_str, "league": league}
        r = requests.get(f"{API_SPORT_BASE}/games", headers=_api_sports_headers(), params=params, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        data = r.json()
        resp = data.get("response") or []
        nh, na = _norm_team(home), _norm_team(away)
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
        data = r.json()
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
# The-Odds-API totals
# ---------------------------------------------------
def _odds_api_total_line(league: str, home: str, away: str) -> Optional[float]:
    if not ODDS_API_KEY:
        return None
    sport_key = _odds_sport_key(league)
    if not sport_key:
        return None

    try:
        # events endpoint
        r = requests.get(
            f"{ODDS_BASE}/sports/{sport_key}/events",
            params={"apiKey": ODDS_API_KEY},
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return None
        events = r.json() if isinstance(r.json(), list) else []
        nh, na = _norm_team(home), _norm_team(away)

        event_id = None
        for ev in events:
            try:
                hh = _norm_team(ev.get("home_team", ""))
                aa = _norm_team(ev.get("away_team", ""))
                if hh and aa and ((hh == nh and aa == na) or (hh == na and aa == nh)):
                    event_id = ev.get("id")
                    break
            except Exception:
                continue
        if not event_id:
            return None

        # odds for this event
        r2 = requests.get(
            f"{ODDS_BASE}/sports/{sport_key}/events/{event_id}/odds",
            params={
                "apiKey": ODDS_API_KEY,
                "regions": "us,eu",
                "markets": "totals",
                "oddsFormat": "decimal",
            },
            timeout=TIMEOUT,
        )
        if r2.status_code != 200:
            return None
        data = r2.json() if isinstance(r2.json(), dict) else {}

        # parse totals line
        bookmakers = data.get("bookmakers") or []
        lines: List[float] = []
        for b in bookmakers:
            for m in (b.get("markets") or []):
                if (m.get("key") or "") != "totals":
                    continue
                for o in (m.get("outcomes") or []):
                    pt = _safe_float(o.get("point"))
                    if pt is not None:
                        lines.append(float(pt))

        if not lines:
            return None

        # median-like: sort and pick middle
        lines.sort()
        mid = lines[len(lines)//2]
        return float(mid)

    except Exception:
        return None

# ---------------------------------------------------
# Fusion
# ---------------------------------------------------
def _fuse_sources(items: List[Dict[str, Any]]) -> Tuple[Optional[float], float]:
    """
    Returns: (total_line, confidence)
    confidence = average of used confidences (0..1)
    """
    valid = []
    for it in items:
        t = _safe_float(it.get("total"))
        c = _safe_float(it.get("confidence"))
        if t is None:
            continue
        if c is None:
            c = 0.55
        c = max(0.0, min(1.0, float(c)))
        valid.append((float(t), float(c)))

    if not valid:
        return None, 0.0

    wsum = sum(t * c for t, c in valid)
    csum = sum(c for _, c in valid)
    if csum <= 0:
        return None, 0.0

    total_line = round(wsum / csum, 1)
    confidence = round(csum / len(valid), 2)
    return total_line, confidence

# ---------------------------------------------------
# PUBLIC API
# ---------------------------------------------------
def faz17_fetch_market(
    *,
    league: str,
    date_str: str,
    home: str,
    away: str,
    want_live: bool = False,
) -> Dict[str, Any]:
    """
    Stable output keys (FAZ-13 expects these):
    - ok: bool
    - main_total: float|None   (alias of total_line)
    - total_line: float|None
    - confidence: float (0..1)
    - sources: [{src,total,confidence}, ...]
    - reason: str
    - live_total: float|None (if want_live)
    """
    out: Dict[str, Any] = {
        "league": league,
        "date_str": date_str,
        "home": home,
        "away": away,
        "ok": False,
        "main_total": None,
        "total_line": None,
        "confidence": 0.0,
        "sources": [],
        "reason": "init",
        "live_total": None,
    }

    # 0) cache warm fallback
    cached = _read_cache_last(league, date_str, home, away)
    if cached and isinstance(cached, dict):
        # cache’i sadece fallback olarak kullan (api yoksa)
        out["cache_hit"] = True
    else:
        out["cache_hit"] = False

    sources: List[Dict[str, Any]] = []

    # 1) Odds API totals
    odds_line = _odds_api_total_line(league, home, away)
    if odds_line is not None:
        sources.append({"src": "the_odds_api", "total": float(odds_line), "confidence": 0.82})

    # 2) (opsiyonel) API-sports live total (want_live)
    if want_live:
        gid = _api_sports_find_game_id(league, date_str, home, away)
        if gid:
            lt = _api_sports_live_total(gid)
            if lt is not None:
                out["live_total"] = float(lt)

    # 3) Fusion
    fused, conf = _fuse_sources(sources)
    if fused is not None:
        out["ok"] = True
        out["total_line"] = float(fused)
        out["main_total"] = float(fused)  # ✅ orchestrator uyumu
        out["confidence"] = float(conf)
        out["sources"] = sources
        out["reason"] = "fused_sources_ok"
        _append_cache(out)
        return out

    # 4) Fallback: cache (api yoksa)
    if cached and isinstance(cached, dict):
        # cache’ten total_line / main_total çek
        mt = _safe_float(cached.get("main_total")) or _safe_float(cached.get("total_line"))
        if mt is not None:
            out["ok"] = True
            out["total_line"] = float(mt)
            out["main_total"] = float(mt)
            out["confidence"] = float(_safe_float(cached.get("confidence")) or 0.45)
            out["sources"] = (cached.get("sources") if isinstance(cached.get("sources"), list) else [])
            out["reason"] = "cache_fallback_ok"
            _append_cache(out)
            return out

    out["reason"] = "no_sources_no_cache"
    _append_cache(out)
    return out 
