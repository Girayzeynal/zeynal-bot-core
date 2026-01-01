from __future__ import annotations

import re
import time
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List

import aiohttp

logger = logging.getLogger("faz17")


# =====================================================
# BACKWARD-COMPAT PUBLIC API (FAZ-13 IMPORTS THESE)
# =====================================================
@dataclass
class MarketRequest:
    league: str
    home: str
    away: str
    date: Optional[str] = None
    regions: str = "us"
    markets: str = "totals,spreads"
    odds_format: str = "decimal"
    date_format: str = "iso"


# =====================================================
# HELPERS
# =====================================================
def _norm(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9\s\-\.]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _team_match_score(api_home: str, api_away: str, home: str, away: str) -> int:
    ah, aa = _norm(api_home), _norm(api_away)
    h, a = _norm(home), _norm(away)

    score = 0
    if ah == h:
        score += 6
    elif h in ah or ah in h:
        score += 4

    if aa == a:
        score += 6
    elif a in aa or aa in a:
        score += 4

    # token overlap
    score += min(2, len(set(h.split()) & set(ah.split())))
    score += min(2, len(set(a.split()) & set(aa.split())))
    return score


def _extract_total(event: Dict[str, Any]) -> Optional[float]:
    for b in event.get("bookmakers", []) or []:
        for m in b.get("markets", []) or []:
            if (m.get("key") or "").lower() != "totals":
                continue
            for o in m.get("outcomes", []) or []:
                pt = o.get("point")
                if isinstance(pt, (int, float)):
                    return float(pt)
    return None


def _extract_home_spread(event: Dict[str, Any]) -> Optional[float]:
    """
    The Odds API spreads outcomes bazen team name ile gelir.
    Biz 'home_team' adına göre spread’i yakalamaya çalışıyoruz.
    """
    home_team = event.get("home_team") or ""
    home_team_n = _norm(home_team)

    for b in event.get("bookmakers", []) or []:
        for m in b.get("markets", []) or []:
            if (m.get("key") or "").lower() != "spreads":
                continue
            for o in m.get("outcomes", []) or []:
                name = _norm(o.get("name") or "")
                pt = o.get("point")
                if not isinstance(pt, (int, float)):
                    continue
                # name home team ile eşleşiyorsa bu "home spread"
                if name == home_team_n or home_team_n in name or name in home_team_n:
                    return float(pt)
    return None


def _safe_getattr(obj: Any, name: str, default=None):
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


# =====================================================
# ENGINE (FAZ-13 SAFE)
# =====================================================
class Faz17Engine:
    """
    - FAZ-13 ile import/çağrı uyumlu
    - Market opsiyonel
    - Asla crash etmez (fail-soft)
    """

    def __init__(self, api_key: Optional[str], base_url: str, ttl_sec: int = 60):
        self.api_key = api_key
        self.base_url = base_url
        self.ttl_sec = int(ttl_sec)
        self._cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

    # ---------- Cache ----------
    def _cache_get(self, key: str) -> Optional[Dict[str, Any]]:
        ent = self._cache.get(key)
        if not ent:
            return None
        ts, val = ent
        if (time.time() - ts) > self.ttl_sec:
            self._cache.pop(key, None)
            return None
        return val

    def _cache_set(self, key: str, val: Dict[str, Any]) -> None:
        self._cache[key] = (time.time(), val)

    # ---------- Public: FAZ-13 may call this ----------
    async def fetch_market(self, req: MarketRequest) -> Dict[str, Any]:
        """
        FAZ-13 bazı sürümlerde direkt fetch_market(req) çağırabilir.
        Dönüş formatı: dict
        """
        if not self.api_key:
            return {"status": "MARKET_OPTIONAL", "reason": "ODDS_API_KEY_MISSING"}

        league_u = (req.league or "").upper().strip()
        if league_u != "NBA":
            return {"status": "MARKET_OPTIONAL", "reason": f"UNSUPPORTED_LEAGUE:{league_u}"}

        cache_key = f"{league_u}:{_norm(req.home)}:{_norm(req.away)}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        # The Odds API v4
        url = f"{self.base_url.rstrip('/')}/sports/basketball_nba/odds/"
        params = {
            "apiKey": self.api_key,
            "regions": req.regions,
            "markets": req.markets,
            "oddsFormat": req.odds_format,
            "dateFormat": req.date_format,
        }

        t0 = time.time()
        try:
            timeout = aiohttp.ClientTimeout(total=8)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        txt = await resp.text()
                        out = {"status": "MARKET_OPTIONAL", "reason": f"HTTP_{resp.status}:{txt[:160]}"}
                        self._cache_set(cache_key, out)
                        return out
                    data = await resp.json()
        except Exception as e:
            out = {"status": "MARKET_OPTIONAL", "reason": f"FETCH_FAIL:{e}"}
            self._cache_set(cache_key, out)
            return out

        # best match
        best_score = 0
        best_event = None
        if isinstance(data, list):
            for ev in data:
                sc = _team_match_score(
                    ev.get("home_team", "") or "",
                    ev.get("away_team", "") or "",
                    req.home,
                    req.away,
                )
                if sc > best_score:
                    best_score = sc
                    best_event = ev

        if not best_event or best_score < 4:
            out = {"status": "MARKET_OPTIONAL", "reason": f"MATCH_NOT_FOUND(score={best_score})"}
            self._cache_set(cache_key, out)
            return out

        total = _extract_total(best_event)
        spread_home = _extract_home_spread(best_event)

        out = {
            "status": "MARKET_OPTIONAL",
            "total": float(total) if isinstance(total, (int, float)) else None,
            "spread_home": float(spread_home) if isinstance(spread_home, (int, float)) else None,
            "spread_away": (-float(spread_home) if isinstance(spread_home, (int, float)) else None),
            "latency_ms": int((time.time() - t0) * 1000),
            "reason": None if (total is not None or spread_home is not None) else "LINE_NOT_FOUND",
        }
        self._cache_set(cache_key, out)
        return out

    # ---------- Public: main.py calls this ----------
    async def enrich_with_market(self, core: Any) -> Any:
        """
        Core objesini mutate eder. Asla crash etmez.
        """
        league = _safe_getattr(core, "league", "NBA") or "NBA"
        home = _safe_getattr(core, "home", "") or ""
        away = _safe_getattr(core, "away", "") or ""
        date_str = _safe_getattr(core, "date_str", None)

        req = MarketRequest(league=str(league), home=str(home), away=str(away), date=date_str)
        mk = await self.fetch_market(req)

        # core.market yerleştir
        try:
            core.market = mk
        except Exception:
            # core set edilemiyorsa meta içine göm
            meta = _safe_getattr(core, "meta", {}) or {}
            if isinstance(meta, dict):
                meta["market"] = mk
                try:
                    core.meta = meta
                except Exception:
                    pass

        return core
