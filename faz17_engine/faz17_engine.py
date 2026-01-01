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
# FAZ-13 BACKWARD COMPAT
# =====================================================
@dataclass
class MarketRequest:
    league: str
    home: str
    away: str
    date: Optional[str] = None


# =====================================================
# HELPERS
# =====================================================
def _norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _team_score(api_home: str, api_away: str, home: str, away: str) -> int:
    ah, aa = _norm(api_home), _norm(api_away)
    h, a = _norm(home), _norm(away)

    score = 0
    if ah == h or h in ah or ah in h:
        score += 4
    if aa == a or a in aa or aa in a:
        score += 4

    score += min(2, len(set(h.split()) & set(ah.split())))
    score += min(2, len(set(a.split()) & set(aa.split())))
    return score


def _extract_total(event: Dict[str, Any]) -> Optional[float]:
    for b in event.get("bookmakers", []) or []:
        for m in b.get("markets", []) or []:
            if (m.get("key") or "").lower() != "totals":
                continue
            for o in m.get("outcomes", []) or []:
                if isinstance(o.get("point"), (int, float)):
                    return float(o["point"])
    return None


# =====================================================
# ENGINE (FINAL, COMPATIBLE)
# =====================================================
class Faz17Engine:
    """
    ✅ Parametresiz init destekler
    ✅ FAZ-13 uyumlu
    ✅ Market opsiyonel
    ✅ Asla crash etmez
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        ttl_sec: int = 60,
    ):
        # ENV fallback (KRİTİK)
        self.api_key = api_key or os.getenv("ODDS_API_KEY")
        self.base_url = base_url or os.getenv(
            "ODDS_BASE", "https://api.the-odds-api.com/v4"
        )
        self.ttl_sec = ttl_sec
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
        if time.time() - ts > self.ttl_sec:
            self._cache.pop(key, None)
            return None
        return val

    def _cache_set(self, key: str, val: Dict[str, Any]) -> None:
        self._cache[key] = (time.time(), val)

    # ----------------------------
    # FAZ-13 MAY CALL THIS
    # ----------------------------
    async def fetch_market(self, req: MarketRequest) -> Dict[str, Any]:
        if not self.api_key:
            return {"status": "MARKET_OPTIONAL", "reason": "ODDS_API_KEY_MISSING"}

        if req.league.upper() != "NBA":
            return {"status": "MARKET_OPTIONAL", "reason": "UNSUPPORTED_LEAGUE"}

        cache_key = f"{req.league}:{_norm(req.home)}:{_norm(req.away)}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        url = f"{self.base_url.rstrip('/')}/sports/basketball_nba/odds/"
        params = {
            "apiKey": self.api_key,
            "regions": "us",
            "markets": "totals",
            "oddsFormat": "decimal",
        }

        try:
            timeout = aiohttp.ClientTimeout(total=8)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        out = {
                            "status": "MARKET_OPTIONAL",
                            "reason": f"HTTP_{resp.status}",
                        }
                        self._cache_set(cache_key, out)
                        return out
                    data = await resp.json()
        except Exception as e:
            out = {"status": "MARKET_OPTIONAL", "reason": f"FETCH_FAIL:{e}"}
            self._cache_set(cache_key, out)
            return out

        best_score = 0
        best_event = None
        for ev in data if isinstance(data, list) else []:
            sc = _team_score(
                ev.get("home_team", ""),
                ev.get("away_team", ""),
                req.home,
                req.away,
            )
            if sc > best_score:
                best_score = sc
                best_event = ev

        if not best_event or best_score < 4:
            out = {"status": "MARKET_OPTIONAL", "reason": "MATCH_NOT_FOUND"}
            self._cache_set(cache_key, out)
            return out

        total = _extract_total(best_event)

        out = {
            "status": "MARKET_OPTIONAL",
            "total": total,
            "latency_ms": int(time.time() * 1000),
        }
        self._cache_set(cache_key, out)
        return out

    # ----------------------------
    # MAIN PIPELINE CALLS THIS
    # ----------------------------
    async def enrich_with_market(self, core: Any) -> Any:
        req = MarketRequest(
            league=getattr(core, "league", "NBA"),
            home=getattr(core, "home", ""),
            away=getattr(core, "away", ""),
            date=getattr(core, "date_str", None),
        )

        mk = await self.fetch_market(req)

        try:
            core.market = mk
        except Exception:
            meta = getattr(core, "meta", {})
            if isinstance(meta, dict):
                meta["market"] = mk
                core.meta = meta

        return core 
