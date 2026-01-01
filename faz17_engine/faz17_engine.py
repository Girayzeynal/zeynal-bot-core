from __future__ import annotations

import re
import time
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import aiohttp

logger = logging.getLogger("faz17")


def _norm(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9\s\-\.]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _team_match_score(api_home: str, api_away: str, home: str, away: str) -> int:
    """
    Hızlı fuzzy eşleşme skoru.
    """
    ah, aa = _norm(api_home), _norm(api_away)
    h, a = _norm(home), _norm(away)

    score = 0
    if ah == h:
        score += 5
    elif h in ah or ah in h:
        score += 3

    if aa == a:
        score += 5
    elif a in aa or aa in a:
        score += 3

    ht = set(h.split())
    at = set(a.split())
    aht = set(ah.split())
    aat = set(aa.split())

    score += min(2, len(ht & aht))
    score += min(2, len(at & aat))
    return score


def _extract_total_from_event(event: Dict[str, Any]) -> Optional[float]:
    """
    The Odds API totals line okumaya çalışır.
    Bulamazsa None.
    """
    bookmakers = event.get("bookmakers") or []
    for b in bookmakers:
        markets = b.get("markets") or []
        for m in markets:
            if (m.get("key") or "").lower() != "totals":
                continue
            outcomes = m.get("outcomes") or []
            for o in outcomes:
                if "point" in o and isinstance(o["point"], (int, float)):
                    return float(o["point"])
    return None


@dataclass
class Faz17Engine:
    """
    Market entegrasyonu OPSİYONEL:
    - API key yoksa: crash yok
    - enrich_with_market her zaman var, her zaman safe
    """
    api_key: Optional[str]
    base_url: str

    async def enrich_with_market(self, core: Any) -> Any:
        """
        core.market içine:
          - status: MARKET_OPTIONAL
          - total: (varsa)
          - reason: (yoksa niye yok)
        """
        # market alanını garanti et
        try:
            if not hasattr(core, "market") or not isinstance(getattr(core, "market", None), dict):
                core.market = {}
        except Exception:
            pass

        if not self.api_key:
            try:
                core.market = {"status": "MARKET_OPTIONAL", "reason": "ODDS_API_KEY_MISSING"}
            except Exception:
                pass
            return core

        league = getattr(core, "league", None) or getattr(core, "league_name", None) or "NBA"
        league_u = str(league).upper().strip()

        # The Odds API sport key
        sport_key = "basketball_nba" if league_u == "NBA" else None
        if not sport_key:
            core.market = {"status": "MARKET_OPTIONAL", "reason": f"UNSUPPORTED_LEAGUE_FOR_MARKET: {league_u}"}
            return core

        home = getattr(core, "home", None) or ""
        away = getattr(core, "away", None) or ""

        url = f"{self.base_url.rstrip('/')}/sports/{sport_key}/odds/"
        params = {
            "apiKey": self.api_key,
            "regions": "us",
            "markets": "totals",
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        }

        t0 = time.time()
        try:
            timeout = aiohttp.ClientTimeout(total=8)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        txt = await resp.text()
                        core.market = {"status": "MARKET_OPTIONAL", "reason": f"ODDS_HTTP_{resp.status}: {txt[:160]}"}
                        return core
                    data = await resp.json()
        except Exception as e:
            core.market = {"status": "MARKET_OPTIONAL", "reason": f"ODDS_FETCH_FAIL: {e}"}
            return core

        # en iyi match
        best: Tuple[int, Optional[Dict[str, Any]]] = (0, None)
        if isinstance(data, list):
            for ev in data:
                api_home = ev.get("home_team") or ""
                api_away = ev.get("away_team") or ""
                sc = _team_match_score(api_home, api_away, home, away)
                if sc > best[0]:
                    best = (sc, ev)

        if best[1] is None or best[0] < 4:
            core.market = {"status": "MARKET_OPTIONAL", "reason": f"MARKET_MATCH_NOT_FOUND (score={best[0]})"}
            return core

        line = _extract_total_from_event(best[1])
        if line is None:
            core.market = {"status": "MARKET_OPTIONAL", "reason": "TOTAL_LINE_NOT_FOUND"}
            return core

        core.market = {
            "status": "MARKET_OPTIONAL",
            "total": float(line),
            "latency_ms": int((time.time() - t0) * 1000),
        }
        return core 
