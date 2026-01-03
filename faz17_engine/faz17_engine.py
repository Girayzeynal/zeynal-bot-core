from __future__ import annotations

import os
import re
import time
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

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
    date_str: Optional[str] = None
    date: Optional[str] = None

    regions: str = "us"
    markets: str = "totals"
    odds_format: str = "decimal"
    date_format: str = "iso"

    def __post_init__(self):
        if self.date_str and not self.date:
            self.date = self.date_str
        elif self.date and not self.date_str:
            self.date_str = self.date


# =====================================================
# HELPERS
# =====================================================
def _norm(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9\s\-\.]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _fixture_key(date_str: Optional[str], home: str, away: str) -> str:
    d = (date_str or "").strip()
    if len(d) >= 10:
        d = d[:10]
    else:
        d = ""
    return f"{d}|{_norm(home)}|{_norm(away)}"


def _commence_date(ev: Dict[str, Any]) -> Optional[str]:
    ct = ev.get("commence_time")
    if not ct or not isinstance(ct, str):
        return None
    if len(ct) >= 10 and ct[4] == "-" and ct[7] == "-":
        return ct[:10]
    return None


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


def _date_norm(d: Optional[str]) -> str:
    s = (d or "").strip()
    return s[:10] if len(s) >= 10 else ""


def _date_close(req_date: str, ev_date: str, tolerance_days: int = 1) -> bool:
    try:
        d1 = datetime.strptime(req_date, "%Y-%m-%d").date()
        d2 = datetime.strptime(ev_date, "%Y-%m-%d").date()
        return abs((d1 - d2).days) <= tolerance_days
    except Exception:
        return False


# =====================================================
# FAZ-17 ENGINE (PRODUCTION)
# =====================================================
class Faz17Engine:
    """
    Market Engine

    Patch:
      - date mismatch softened (±1 day) when match_score is strong
      - shared session + aclose to avoid aiohttp leaks
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        ttl_sec: int = 60,
        date_tolerance_days: int = 1,
        strong_match_score: int = 8,
    ):
        self.api_key = api_key or os.getenv("ODDS_API_KEY")
        self.base_url = base_url or os.getenv("ODDS_BASE", "https://api.the-odds-api.com/v4")
        self.ttl_sec = int(ttl_sec)
        self.date_tolerance_days = int(date_tolerance_days)
        self.strong_match_score = int(strong_match_score)

        self._cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._session: Optional[aiohttp.ClientSession] = None

        logger.info(
            f"FAZ17 init | api_key={'YES' if self.api_key else 'NO'} | base_url={self.base_url}"
        )

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session and not self._session.closed:
            return self._session
        timeout = aiohttp.ClientTimeout(total=8)
        self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def aclose(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

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
        fixture_key = _fixture_key(req.date_str or req.date, req.home, req.away)

        if not self.api_key:
            return {
                "status": "MARKET_OPTIONAL",
                "total": None,
                "latency_ms": None,
                "reason": "ODDS_API_KEY_MISSING",
                "fixture_key": fixture_key,
                "event_fixture_key": None,
                "match_score": 0,
            }

        league_u = (req.league or "").upper().strip()
        if league_u != "NBA":
            return {
                "status": "MARKET_OPTIONAL",
                "total": None,
                "latency_ms": None,
                "reason": f"UNSUPPORTED_LEAGUE:{league_u}",
                "fixture_key": fixture_key,
                "event_fixture_key": None,
                "match_score": 0,
            }

        # cache key includes fixture_key (date + teams)
        cache_key = f"{league_u}:{fixture_key}:{req.markets}"
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
            session = await self._get_session()
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    txt = await resp.text()
                    out = {
                        "status": "MARKET_OPTIONAL",
                        "total": None,
                        "latency_ms": int((time.time() - t0) * 1000),
                        "reason": f"HTTP_{resp.status}:{txt[:160]}",
                        "fixture_key": fixture_key,
                        "event_fixture_key": None,
                        "match_score": 0,
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
                "fixture_key": fixture_key,
                "event_fixture_key": None,
                "match_score": 0,
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
                "fixture_key": fixture_key,
                "event_fixture_key": None,
                "match_score": int(best_score),
            }
            self._cache_set(cache_key, out)
            return out

        ev_date = _commence_date(best_event)
        event_fixture_key = _fixture_key(
            ev_date,
            best_event.get("home_team", "") or "",
            best_event.get("away_team", "") or "",
        )

        req_date = _date_norm(req.date_str or req.date)

        # ✅ DATE POLICY:
        # - If strong match score, allow ±tolerance days
        # - Otherwise keep strict
        if req_date and ev_date and req_date != ev_date:
            if best_score >= self.strong_match_score and _date_close(req_date, ev_date, self.date_tolerance_days):
                # accept date shift
                pass
            else:
                out = {
                    "status": "MARKET_MISMATCH",
                    "total": None,
                    "latency_ms": int((time.time() - t0) * 1000),
                    "reason": f"DATE_MISMATCH(req={req_date}, ev={ev_date})",
                    "fixture_key": fixture_key,
                    "event_fixture_key": event_fixture_key,
                    "match_score": int(best_score),
                }
                self._cache_set(cache_key, out)
                return out

        total_line = _extract_total(best_event)
        if total_line is None:
            out = {
                "status": "MARKET_OPTIONAL",
                "total": None,
                "latency_ms": int((time.time() - t0) * 1000),
                "reason": "TOTAL_NOT_FOUND",
                "fixture_key": fixture_key,
                "event_fixture_key": event_fixture_key,
                "match_score": int(best_score),
            }
            self._cache_set(cache_key, out)
            return out

        # annotate status
        status = "MARKET_OK"
        if req_date and ev_date and req_date != ev_date:
            status = "MARKET_OK_DATE_SHIFT"

        out = {
            "status": status,
            "total": float(total_line),
            "latency_ms": int((time.time() - t0) * 1000),
            "reason": None,
            "fixture_key": fixture_key,
            "event_fixture_key": event_fixture_key,
            "match_score": int(best_score),
        }
        self._cache_set(cache_key, out)
        return out

    # ----------------------------
    # FAZ-13 EXPECTS THIS
    # ----------------------------
    async def fetch_market_total(self, *args, **kwargs) -> Optional[float]:
        if len(args) == 1 and isinstance(args[0], MarketRequest):
            mk = await self.fetch_market(args[0])
            return mk.get("total")

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
        ctx = _safe_getattr(core, "ctx", None)
        league = _safe_getattr(ctx, "league", None) or _safe_getattr(core, "league", "NBA")
        home = _safe_getattr(ctx, "home", None) or _safe_getattr(core, "home", "")
        away = _safe_getattr(ctx, "away", None) or _safe_getattr(core, "away", "")
        date_str = (
            _safe_getattr(ctx, "date", None)
            or _safe_getattr(core, "date_str", None)
            or _safe_getattr(core, "date", None)
        )

        req = MarketRequest(
            league=str(league or "NBA"),
            home=str(home or ""),
            away=str(away or ""),
            date_str=str(date_str) if date_str else None,
        )

        mk = await self.fetch_market(req)

        try:
            if isinstance(mk, dict) and "total" in mk:
                core.market = mk
            else:
                core.market = {"status": "MARKET_OPTIONAL", "total": None, "reason": "BAD_MARKET_PAYLOAD"}
        except Exception:
            pass

        try:
            meta = _safe_getattr(core, "meta", {}) or {}
            if isinstance(meta, dict):
                meta["market_total"] = mk.get("total")
                meta["market_status"] = mk.get("status")
                meta["market_latency_ms"] = mk.get("latency_ms")
                meta["market_reason"] = mk.get("reason")
                meta["market_fixture_key"] = mk.get("fixture_key")
                meta["market_event_fixture_key"] = mk.get("event_fixture_key")
                meta["market_match_score"] = mk.get("match_score")
                core.meta = meta
        except Exception:
            pass

        return core 
