from __future__ import annotations

import re
import time
import math
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, List, Tuple

import aiohttp

logger = logging.getLogger("faz17")


# =====================================================
# PUBLIC API — FAZ-13 EXPECTS THESE
# =====================================================
@dataclass
class MarketRequest:
    league: str
    home: str
    away: str
    date: Optional[str] = None
    is_live: bool = False


@dataclass
class MarketResult:
    status: str
    total: Optional[float] = None
    spread_home: Optional[float] = None
    spread_away: Optional[float] = None
    confidence_boost: float = 0.0
    latency_ms: Optional[int] = None
    reason: Optional[str] = None


# =====================================================
# INTERNAL CACHE (TTL)
# =====================================================
@dataclass
class _CacheEntry:
    ts: float
    value: Any


class _TTLCache:
    def __init__(self, ttl_sec: int = 60):
        self.ttl = ttl_sec
        self.data: Dict[str, _CacheEntry] = {}

    def get(self, key: str) -> Optional[Any]:
        ent = self.data.get(key)
        if not ent:
            return None
        if time.time() - ent.ts > self.ttl:
            self.data.pop(key, None)
            return None
        return ent.value

    def set(self, key: str, value: Any) -> None:
        self.data[key] = _CacheEntry(time.time(), value)


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


def _extract_markets(event: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    """
    Returns (total_line, home_spread)
    """
    total = None
    spread = None

    for b in event.get("bookmakers", []):
        for m in b.get("markets", []):
            key = (m.get("key") or "").lower()

            if key == "totals":
                for o in m.get("outcomes", []):
                    if isinstance(o.get("point"), (int, float)):
                        total = float(o["point"])

            if key == "spreads":
                for o in m.get("outcomes", []):
                    if o.get("name", "").lower() in ("home", "home team"):
                        if isinstance(o.get("point"), (int, float)):
                            spread = float(o["point"])

    return total, spread


def _confidence_from_market(total: Optional[float], spread: Optional[float]) -> float:
    """
    Market varsa FAZ-22 confidence’ına küçük katkı yapar.
    """
    boost = 0.0
    if total is not None:
        boost += 0.04
    if spread is not None:
        boost += 0.03
    return boost


# =====================================================
# FAZ-17 ENGINE (REAL)
# =====================================================
@dataclass
class Faz17Engine:
    api_key: Optional[str]
    base_url: str
    cache_ttl: int = 60

    _cache: _TTLCache = field(init=False)

    def __post_init__(self):
        self._cache = _TTLCache(self.cache_ttl)

    # -------------------------------------------------
    # CORE ENTRY
    # -------------------------------------------------
    async def enrich_with_market(self, core: Any) -> Any:
        """
        FAZ-13 → FAZ-17 entegrasyon noktası.
        Core objesini MUTATE eder.
        Asla crash etmez.
        """

        if not hasattr(core, "market") or not isinstance(core.market, dict):
            core.market = {}

        req = MarketRequest(
            league=getattr(core, "league", "NBA"),
            home=getattr(core, "home", ""),
            away=getattr(core, "away", ""),
            date=getattr(core, "date_str", None),
            is_live=getattr(core, "is_live", False),
        )

        result = await self._fetch_market(req)

        core.market = {
            "status": result.status,
            "total": result.total,
            "spread_home": result.spread_home,
            "spread_away": result.spread_away,
            "latency_ms": result.latency_ms,
            "reason": result.reason,
        }

        # FAZ-22 için confidence katkısı
        meta = getattr(core, "meta", {})
        if isinstance(meta, dict):
            meta["market_confidence_boost"] = result.confidence_boost
            core.meta = meta

        return core

    # -------------------------------------------------
    # INTERNAL FETCH
    # -------------------------------------------------
    async def _fetch_market(self, req: MarketRequest) -> MarketResult:
        if not self.api_key:
            return MarketResult(
                status="MARKET_OPTIONAL",
                reason="ODDS_API_KEY_MISSING",
            )

        if req.league.upper() != "NBA":
            return MarketResult(
                status="MARKET_OPTIONAL",
                reason=f"UNSUPPORTED_LEAGUE:{req.league}",
            )

        cache_key = f"{req.league}:{req.home}:{req.away}"
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        url = f"{self.base_url.rstrip('/')}/sports/basketball_nba/odds/"
        params = {
            "apiKey": self.api_key,
            "regions": "us",
            "markets": "totals,spreads",
            "oddsFormat": "decimal",
        }

        t0 = time.time()

        try:
            timeout = aiohttp.ClientTimeout(total=8)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        return MarketResult(
                            status="MARKET_OPTIONAL",
                            reason=f"HTTP_{resp.status}",
                        )
                    data = await resp.json()
        except Exception as e:
            return MarketResult(
                status="MARKET_OPTIONAL",
                reason=f"FETCH_FAIL:{e}",
            )

        best: Tuple[int, Optional[Dict[str, Any]]] = (0, None)
        for ev in data if isinstance(data, list) else []:
            sc = _team_score(
                ev.get("home_team", ""),
                ev.get("away_team", ""),
                req.home,
                req.away,
            )
            if sc > best[0]:
                best = (sc, ev)

        if not best[1] or best[0] < 4:
            return MarketResult(
                status="MARKET_OPTIONAL",
                reason="MATCH_NOT_FOUND",
            )

        total, spread = _extract_markets(best[1])

        boost = _confidence_from_market(total, spread)

        res = MarketResult(
            status="MARKET_OPTIONAL",
            total=total,
            spread_home=spread,
            spread_away=-spread if spread is not None else None,
            confidence_boost=boost,
            latency_ms=int((time.time() - t0) * 1000),
        )

        self._cache.set(cache_key, res)
        return res
