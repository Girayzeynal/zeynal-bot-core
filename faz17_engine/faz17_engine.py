from __future__ import annotations

import os
import re
import time
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import aiohttp

logger = logging.getLogger("faz17")


# =====================================================
# FAZ-13 BACKWARD COMPAT TYPES
# =====================================================
@dataclass
class MarketRequest:
    league: str
    home: str
    away: str
    date: Optional[str] = None
    regions: str = "us"
    markets: str = "totals"
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

    score += min(2, len(set(h.split()) & set(ah.split())))
    score += min(2, len(set(a.split()) & set(aa.split())))
    return score


def _extract_total(event: Dict[str, Any]) -> Optional[float]:
    """
    The Odds API v4 totals line extract.
    """
    for b in (event.get("bookmakers") or []):
        for m in (b.get("markets") or []):
            if (m.get("key") or "").lower() != "totals":
                continue
            for o in (m.get("outcomes") or []):
                pt = o.get("point")
                if isinstance(pt, (int, float)):
                    return float(pt)
    return None


def _safe_getattr(obj: Any, name: str, default=None):
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


# =====================================================
# ENGINE — FULL CONTRACT (FAZ-13 + MAIN)
# =====================================================
class Faz17Engine:
    """
    ✅ Faz13 expects: fetch_market_total(...)
    ✅ Some code expects: fetch_market(MarketRequest)
    ✅ Main expects: enrich_with_market(core)
    ✅ Parametresiz init çalışır (FAZ-13 __init__ içinde Faz17Engine() var)
    ✅ Market yoksa crash yok -> MARKET_OPTIONAL
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        ttl_sec: int = 60,
    ):
        self.api_key = api_key or os.getenv("ODDS_API_KEY")
        self.base_url = base_url or os.getenv("ODDS_BASE", "https://api.the-odds-api.com/v4")
        self.ttl_sec = int(ttl_sec)
        self._cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

        logger.info(
            f"FAZ17 init | api_key={'YES' if self.api_key else 'NO'} | base_url={self.base_url}"
        )

    # ----------------------------
    # CACHE
    # ----------------------------
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

    # ----------------------------
    # CORE FETCH (dict)
    # ----------------------------
    async def fetch_market(self, req: MarketRequest) -> Dict[str, Any]:
        """
        Unified market fetch.
        Returns dict with keys:
          status, total, latency_ms, reason
        """
        if not self.api_key:
            return {"status": "MARKET_OPTIONAL", "reason": "ODDS_API_KEY_MISSING", "total": None}

        league_u = (req.league or "").upper().strip()
        if league_u != "NBA":
            return {"status": "MARKET_OPTIONAL", "reason": f"UNSUPPORTED_LEAGUE:{league_u}", "total": None}

        cache_key = f"{league_u}:{_norm(req.home)}:{_norm(req.away)}:{req.markets}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        url = f"{self.base_url.rstrip('/')}/sports/basketball_nba/odds/"
        params = {
            "apiKey": self.api_key,
            "regions": req.regions,
            "markets": req.markets,          # default: totals
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
                        out = {
                            "status": "MARKET_OPTIONAL",
                            "reason": f"HTTP_{resp.status}:{txt[:160]}",
                            "total": None,
                            "latency_ms": int((time.time() - t0) * 1000),
                        }
                        self._cache_set(cache_key, out)
                        return out
                    data = await resp.json()
        except Exception as e:
            out = {
                "status": "MARKET_OPTIONAL",
                "reason": f"FETCH_FAIL:{e}",
                "total": None,
                "latency_ms": int((time.time() - t0) * 1000),
            }
            self._cache_set(cache_key, out)
            return out

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
            out = {
                "status": "MARKET_OPTIONAL",
                "reason": f"MATCH_NOT_FOUND(score={best_score})",
                "total": None,
                "latency_ms": int((time.time() - t0) * 1000),
            }
            self._cache_set(cache_key, out)
            return out

        total = _extract_total(best_event)

        out = {
            "status": "MARKET_OPTIONAL",
            "reason": None if total is not None else "TOTAL_NOT_FOUND",
            "total": float(total) if isinstance(total, (int, float)) else None,
            "latency_ms": int((time.time() - t0) * 1000),
        }
        self._cache_set(cache_key, out)
        return out

    # ----------------------------
    # FAZ-13 EXPECTS THIS (TOTAL ONLY)
    # ----------------------------
    async def fetch_market_total(self, *args, **kwargs) -> Optional[float]:
        """
        FAZ-13 compatibility layer.
        Accepts flexible signatures:
          - fetch_market_total(league, home, away, date_str=?)
          - fetch_market_total(MarketRequest)
          - fetch_market_total(core_like_object)
        Returns:
          total line as float or None.
        """
        # Case 1: MarketRequest passed
        if len(args) == 1 and isinstance(args[0], MarketRequest):
            mk = await self.fetch_market(args[0])
            return mk.get("total")

        # Case 2: core-like object passed
        if len(args) == 1 and not isinstance(args[0], (str, int, float, dict, list, tuple)):
            obj = args[0]
            req = MarketRequest(
                league=str(_safe_getattr(obj, "league", "NBA")),
                home=str(_safe_getattr(obj, "home", "")),
                away=str(_safe_getattr(obj, "away", "")),
                date=_safe_getattr(obj, "date_str", None),
            )
            mk = await self.fetch_market(req)
            return mk.get("total")

        # Case 3: positional league/home/away
        league = kwargs.get("league")
        home = kwargs.get("home")
        away = kwargs.get("away")
        date = kwargs.get("date") or kwargs.get("date_str")

        if len(args) >= 3:
            league = args[0]
            home = args[1]
            away = args[2]
            if len(args) >= 4 and date is None:
                date = args[3]

        req = MarketRequest(
            league=str(league or "NBA"),
            home=str(home or ""),
            away=str(away or ""),
            date=str(date) if date else None,
        )
        mk = await self.fetch_market(req)
        return mk.get("total")

    # ----------------------------
    # MAIN PIPELINE EXPECTS THIS (MUTATES CORE)
    # ----------------------------
    async def enrich_with_market(self, core: Any) -> Any:
        req = MarketRequest(
            league=str(_safe_getattr(core, "league", "NBA") or "NBA"),
            home=str(_safe_getattr(core, "home", "") or ""),
            away=str(_safe_getattr(core, "away", "") or ""),
            date=_safe_getattr(core, "date_str", None),
        )
        mk = await self.fetch_market(req)

        try:
            core.market = mk
        except Exception:
            meta = _safe_getattr(core, "meta", {}) or {}
            if isinstance(meta, dict):
                meta["market"] = mk
                try:
                    core.meta = meta
                except Exception:
                    pass

        return core 
