# -*- coding: utf-8 -*-
"""
FAZ-17 MARKET FETCHER (Fly.io friendly)

Amaç:
- Dış kaynaklardan (opsiyonel) totals line çekmek
- Kaynak yoksa crash etmek yerine güvenli NO_MARKET_DATA dönmek
- JSONL cache ile fallback

ENV:
- ODDS_API_KEY            (the-odds-api)
- ODDS_BASE_URL           (default: https://api.the-odds-api.com/v4)
- DATA_DIR                (default: /data)
- FAZ17_CACHE_MAX_SCAN    (default: 200)
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("faz17-market")

# requests opsiyonel (requirements'ta yoksa bile import crash olmasın)
try:
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None  # type: ignore


ODDS_API_KEY = os.getenv("ODDS_API_KEY", "").strip()
ODDS_BASE = os.getenv("ODDS_BASE_URL", "https://api.the-odds-api.com/v4").strip()
TIMEOUT: Tuple[float, float] = (3.0, 8.0)


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


def _safe_text(x: Any) -> str:
    try:
        return str(x).strip()
    except Exception:
        return ""


def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip().replace(",", ".")
        return float(s)
    except Exception:
        return None


def _norm_team(s: str) -> str:
    s = _safe_text(s).lower()
    repl = {
        "ç": "c",
        "ğ": "g",
        "ı": "i",
        "ö": "o",
        "ş": "s",
        "ü": "u",
        "á": "a",
        "à": "a",
        "ä": "a",
        "é": "e",
        "è": "e",
        "ë": "e",
        "í": "i",
        "ì": "i",
        "ï": "i",
        "ó": "o",
        "ò": "o",
        "ú": "u",
        "ù": "u",
        "â": "a",
        "ê": "e",
        "î": "i",
        "ô": "o",
        "û": "u",
    }
    for a, b in repl.items():
        s = s.replace(a, b)
    s = s.replace(".", " ").replace("-", " ").replace("_", " ")
    s = " ".join(s.split())
    return s


def _append_cache(obj: Dict[str, Any]) -> None:
    try:
        o = dict(obj)
        o["ts"] = int(time.time())
        with open(MARKET_CACHE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _read_cache_last(
    league: str,
    date_str: str,
    home: str,
    away: str,
    max_scan: int = 200,
) -> Optional[Dict[str, Any]]:
    try:
        if not os.path.exists(MARKET_CACHE_PATH):
            return None

        nh, na = _norm_team(home), _norm_team(away)
        lg = _safe_text(league).lower()

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


def _odds_sport_key(league: str) -> Optional[str]:
    lg = _safe_text(league).lower()
    if "euroleague" in lg:
        return "basketball_euroleague"
    if "nba" in lg:
        return "basketball_nba"
    return None


def _odds_api_total_line(league: str, home: str, away: str) -> Optional[float]:
    if not requests:
        return None
    if not ODDS_API_KEY:
        return None

    sport_key = _odds_sport_key(league)
    if not sport_key:
        return None

    try:
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

        lines.sort()
        return float(lines[len(lines) // 2])
    except Exception:
        return None


def _fuse_sources(items: List[Dict[str, Any]]) -> Tuple[Optional[float], float]:
    """
    Kaynaklardan gelen total'ları confidence ile ağırlıklandırıp tek total üretir.
    Return:
      (total_line | None, confidence 0..1)
    """
    valid: List[Tuple[float, float]] = []
    for it in items:
        t = _safe_float(it.get("total"))
        c = _safe_float(it.get("confidence", 0.55))
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
    return float(total_line), float(confidence)

def faz17_fetch_market(
    *,
    league: str,
    date_str: str,
    home: str,
    away: str,
) -> Dict[str, Any]:
    """
    Stable output keys:
      - ok: bool
      - main_total: float|None
      - total_line: float|None
      - confidence: float (0..1)
      - sources: list[{src,total,confidence}]
      - reason: str
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
    }

    max_scan = int(os.getenv("FAZ17_CACHE_MAX_SCAN", "200") or "200")
    cached = _read_cache_last(league, date_str, home, away, max_scan=max_scan)
    out["cache_hit"] = bool(cached)

    sources: List[Dict[str, Any]] = []

    odds_line = _odds_api_total_line(league, home, away)
    if odds_line is not None:
        sources.append({"src": "the_odds_api", "total": float(odds_line), "confidence": 0.82})

    fused, conf = _fuse_sources(sources)

    if fused is not None:
        out["ok"] = True
        out["main_total"] = float(fused)
        out["total_line"] = float(fused)
        out["confidence"] = float(conf)
        out["sources"] = sources
        out["reason"] = "fused_sources_ok"
        _append_cache(out)
        return out

    # fallback cache
    if cached and isinstance(cached, dict):
        mt = _safe_float(cached.get("main_total")) or _safe_float(cached.get("total_line"))
        if mt is not None:
            out["ok"] = True
            out["main_total"] = float(mt)
            out["total_line"] = float(mt)
            out["confidence"] = float(_safe_float(cached.get("confidence")) or 0.45)
            out["sources"] = cached.get("sources") if isinstance(cached.get("sources"), list) else []
            out["reason"] = "cache_fallback_ok"
            _append_cache(out)
            return out

    out["reason"] = "no_sources_no_cache"
    _append_cache(out)
    return out
