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
# BACKWARD-COMPAT PUBLIC API (FAZ-13 IMPORTS THESE)
# =====================================================
@dataclass
class MarketRequest:
    """
    FAZ-13 kodunun değişik versiyonlarında şu signature ile çağrılır:
      MarketRequest(league=req.league, date_str=req.date_str, home=req.home, away=req.away)
    ve bazen:
      fetch_market(MarketRequest(...))

    Bu yüzden tüm olası parametre isimlerini destekliyoruz.
    """
    league: str
    home: str
    away: str

    # FAZ-13 tarafı date_str ile verir
    date_str: Optional[str] = None

    # alias olarak date de var
    date: Optional[str] = None

    regions: str = "us"
    markets: str = "totals"
    odds_format: str = "decimal"
    date_format: str = "iso"

    def __post_init__(self):
        # Eğer date_str varsa bunu date’e ata
        if self.date_str and not self.date:
            self.date = self.date_str
        # Eğer date varsa ve date_str yoksa onu ata
        elif self.date and not self.date_str:
            self.date_str = self.date



# =====================================================
# HELPERS
# =====================================================
def _norm(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9\s\-\.]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _team_match_score(api_home: str, api_away: str, home: str, away: str) -> int:
    """
    Basit fuzzy eşleşme skoru algoritması.
    """
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
    The Odds API v4 'totals' market’inden total line’ı çek.
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
# FAZ-17 ENGINE (FULL PRODUCTION-READY)
# =====================================================
class Faz17Engine:
    """
    - Faz13'in beklediği tüm import ve method’lar var
    - Parametresiz init çalışır
    - Market opsiyonel + asla crash etmez
    - fetch_market, fetch_market_total, enrich_with_market destekli
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        ttl_sec: int = 60,
    ):
        # ENV fallback
        self.api_key = api_key or os.getenv("ODDS_API_KEY")
        self.base_url = base_url or os.getenv("ODDS_BASE", "https://api.the-odds-api.com/v4")
        self.ttl_sec = int(ttl_sec)
        # basit cache
        self._cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

        logger.info(
            f"FAZ17 init | api_key={'YES' if self.api_key else 'NO'} | base_url={self.base_url}"
        )


    # ----------------------------
    # CACHE METHODS
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
    # MAIN FETCH METHOD
    # ----------------------------
    async def fetch_market(self, req: MarketRequest) -> Dict[str, Any]:
        """
        Bu method hemFAZ-13'in beklediği fetch_market için
        hem enrich_with_market pipeline’ı için kullanılır.

        Çıktı formatı:
          {
            "status": "MARKET_OPTIONAL",
            "total": float | None,
            "latency_ms": int | None,
            "reason": Optional[str]
          }
        """

        if not self.api_key:
            return {"status": "MARKET_OPTIONAL", "total": None, "latency_ms": None, "reason": "ODDS_API_KEY_MISSING"}

        league_u = (req.league or "").upper().strip()
        if league_u != "NBA":
            return {"status": "MARKET_OPTIONAL", "total": None, "latency_ms": None, "reason": f"UNSUPPORTED_LEAGUE:{league_u}"}

        cache_key = f"{league_u}:{_norm(req.home)}:{_norm(req.away)}:{req.markets}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached

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
                        out = {
                            "status": "MARKET_OPTIONAL",
                            "total": None,
                            "latency_ms": int((time.time() - t0) * 1000),
                            "reason": f"HTTP_{resp.status}:{txt[:160]}",
                        }
                        self._cache_set(cache_key, out)
                        return out

                    data = await resp.json()
        except Exception as e:
            out = {
                "status": "MARKET_OPTIONAL",
                "total": None,
                "latency_ms": int((time.time() - t0) * 1000),
                "reason": f"FETCH_FAIL:{e}",
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
                "total": None,
                "latency_ms": int((time.time() - t0) * 1000),
                "reason": f"MATCH_NOT_FOUND(score={best_score})",
            }
            self._cache_set(cache_key, out)
            return out

        total_line = _extract_total(best_event)

        out = {
            "status": "MARKET_OPTIONAL",
            "total": float(total_line) if isinstance(total_line, (int, float)) else None,
            "latency_ms": int((time.time() - t0) * 1000),
            "reason": None if total_line is not None else "TOTAL_NOT_FOUND",
        }
        self._cache_set(cache_key, out)
        return out


    # ----------------------------
    # FAZ-13 EXPECTS THIS
    # ----------------------------
    async def fetch_market_total(self, *args, **kwargs) -> Optional[float]:
        """
        backward compatible wrapper:
        signature:
          - fetch_market_total(league, home, away, date_str=?)
          - fetch_market_total(MarketRequest)
          - fetch_market_total(core_like_object)

        returns float or None
        """
        # MarketRequest passed
        if len(args) == 1 and isinstance(args[0], MarketRequest):
            mk = await self.fetch_market(args[0])
            return mk.get("total")

        # core-like object passed
        if len(args) == 1 and not isinstance(args[0], (str, int, float, dict, list, tuple)):  
            obj = args[0]
            req = MarketRequest(
                league=str(_safe_getattr(obj, "league", "NBA")),
                home=str(_safe_getattr(obj, "home", "")),
                away=str(_safe_getattr(obj, "away", "")),
                date_str=_safe_getattr(obj, "date_str", None),
            )
            mk = await self.fetch_market(req)
            return mk.get("total")

        # positional args as legacy
        league = kwargs.get("league")
        home = kwargs.get("home")
        away = kwargs.get("away")
        date_str = kwargs.get("date_str") or kwargs.get("date")

        if len(args) >= 3:
            league = args[0]
            home = args[1]
            away = args[2]
            if len(args) >= 4 and date_str is None:
                date_str = args[3]

        req = MarketRequest(
            league=str(league or "NBA"),
            home=str(home or ""),
            away=str(away or ""),
            date_str=str(date_str) if date_str else None,
        )

        mk = await self.fetch_market(req)
        return mk.get("total")


    # ----------------------------
    # MAIN PIPELINE USE
    # ----------------------------
    async def enrich_with_market(self, core: Any) -> Any:
        req = MarketRequest(
            league=str(_safe_getattr(core, "league", "NBA") or "NBA"),
            home=str(_safe_getattr(core, "home", "") or ""),
            away=str(_safe_getattr(core, "away", "") or ""),
            date_str=_safe_getattr(core, "date_str", None),
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
