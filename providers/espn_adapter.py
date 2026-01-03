from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"


# =====================================================
# CACHE
# =====================================================

@dataclass
class _CacheEntry:
    ts: float
    value: Any


class _TTLCache:
    def __init__(self, ttl_sec: int) -> None:
        self.ttl_sec = int(ttl_sec)
        self._data: Dict[str, _CacheEntry] = {}

    def get(self, key: str) -> Any:
        ent = self._data.get(key)
        if not ent:
            return None
        if (time.time() - ent.ts) > self.ttl_sec:
            self._data.pop(key, None)
            return None
        return ent.value

    def set(self, key: str, value: Any) -> None:
        self._data[key] = _CacheEntry(time.time(), value)


# =====================================================
# HELPERS
# =====================================================

def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().replace("-", " ").replace("_", " ").split())


def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def _parse_espn_ts_utc(ev: Dict[str, Any]) -> Optional[int]:
    """
    ESPN events usually include:
      - date: ISO string with timezone, e.g. "2026-01-03T03:00Z" or "...-0500"
    We parse it into epoch seconds (UTC).
    """
    # ESPN often has `date` at event top-level
    s = ev.get("date")
    if not isinstance(s, str) or not s:
        return None

    # Fast-path: ISO like 2026-01-03T03:00Z
    try:
        # Handle Z
        if s.endswith("Z"):
            # yyyy-mm-ddThh:mmZ (or hh:mm:ssZ)
            # Use time.strptime without external deps
            # Normalize seconds
            if len(s) == 17:  # YYYY-MM-DDTHH:MMZ
                s2 = s[:-1] + ":00Z"
            else:
                s2 = s
            # Convert to epoch by manual parsing
            # Fallback to fromisoformat not safe for Z in py<3.11 in some envs
            # We'll do regex parse:
        pass
    except Exception:
        pass

    # Regex parse: YYYY-MM-DDTHH:MM(:SS)?(Z|±HH:MM|±HHMM)
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?(Z|([+-]\d{2}):?(\d{2}))?$", s)
    if not m:
        return None

    Y = int(m.group(1))
    Mo = int(m.group(2))
    D = int(m.group(3))
    h = int(m.group(4))
    mi = int(m.group(5))
    se = int(m.group(6) or "0")
    tz = m.group(7) or "Z"

    # Build naive epoch assuming UTC then adjust if offset present
    try:
        import calendar
        base = calendar.timegm((Y, Mo, D, h, mi, se))
    except Exception:
        return None

    if tz == "Z" or tz is None:
        return int(base)

    # offset present
    # m.group(8)=±HH(:)?MM, m.group(9)=sign+HH, m.group(10)=MM
    sign_hh = m.group(8)
    sign = 1
    if sign_hh and sign_hh.startswith("-"):
        sign = -1
    # HH and MM
    hh_off = int((m.group(9) or "0").replace("+", "").replace("-", ""))
    mm_off = int(m.group(10) or "0")
    offset_sec = sign * (hh_off * 3600 + mm_off * 60)

    # If string is local time with offset, to get UTC epoch:
    # UTC = local - offset
    return int(base - offset_sec)


def _extract_competitors(ev: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """
    Returns (home_abbr, away_abbr) from an ESPN event.
    """
    comps = (
        (ev.get("competitions") or [{}])[0].get("competitors")
        if isinstance(ev.get("competitions"), list)
        else None
    )
    if not isinstance(comps, list):
        return None, None

    home_abbr = None
    away_abbr = None
    for c in comps:
        try:
            ha = str((c.get("homeAway") or "")).lower()
            abbr = str(((c.get("team") or {}).get("abbreviation") or "")).upper()
            if not abbr:
                continue
            if ha == "home":
                home_abbr = abbr
            elif ha == "away":
                away_abbr = abbr
        except Exception:
            continue
    return home_abbr, away_abbr


def _extract_scores_for_team(ev: Dict[str, Any], team_abbr: str) -> Optional[Tuple[float, float, bool]]:
    """
    Returns (pts_for, pts_against, is_home) for team_abbr in event, if possible.
    """
    comps = ev.get("competitions")
    if not isinstance(comps, list) or not comps:
        return None
    competitors = comps[0].get("competitors")
    if not isinstance(competitors, list) or len(competitors) < 2:
        return None

    team_abbr_u = (team_abbr or "").upper().strip()
    if not team_abbr_u:
        return None

    # find team row and opponent row
    team_row = None
    opp_row = None
    for c in competitors:
        abbr = str(((c.get("team") or {}).get("abbreviation") or "")).upper()
        if abbr == team_abbr_u:
            team_row = c
        else:
            opp_row = c

    if not team_row or not opp_row:
        return None

    pf = _safe_float(team_row.get("score"))
    pa = _safe_float(opp_row.get("score"))
    if pf is None or pa is None:
        return None

    ha = str(team_row.get("homeAway") or "").lower()
    is_home = ha == "home"
    return float(pf), float(pa), bool(is_home)


def _pace_proxy_from_totals(total_pts: float) -> float:
    """
    ESPN does not reliably provide possessions per game in the free endpoints.
    We provide a conservative pace proxy to keep the pipeline numerically stable.

    IMPORTANT:
    - This is NOT a fabricated pace claim; it's a neutral proxy.
    - If SportsDataIO provides possessions, that provider should override this.
    """
    # clamp around typical NBA pace band
    # total points tends to correlate with pace; keep weak slope
    p = 99.5 + (total_pts - 220.0) * 0.06
    if p < 94.0:
        p = 94.0
    if p > 106.0:
        p = 106.0
    return float(p)


# =====================================================
# ESPN ADAPTER
# =====================================================

class ESPNAdapter:
    """
    ESPN provider adapter (NO API KEY).

    Responsibilities:
      - Team baseline (avgPointsFor / avgPointsAgainst)
      - Recent game time-series (UTC) for analytics pipeline
      - Injury information (parsed from ESPN injury pages)
      - Caching + retry + backoff

    This adapter:
      - NEVER computes edge / risk
      - ONLY returns raw provider data or safely-derived proxies
    """

    name = "ESPN"
    confidence = 0.60

    def __init__(self, session: Optional[aiohttp.ClientSession] = None) -> None:
        # Optional shared session to avoid leaks & excessive sockets
        self._session: Optional[aiohttp.ClientSession] = session
        self._owns_session: bool = session is None

        self._cache = _TTLCache(ttl_sec=int(os.getenv("ESPN_CACHE_TTL_SEC", "900")))
        self._teams_cache = _TTLCache(ttl_sec=int(os.getenv("ESPN_TEAMS_TTL_SEC", "21600")))

        self._disk_cache_dir = (os.getenv("FAZ_CACHE_DIR") or "").strip()

    # -------------------------------------------------
    # HTTP
    # -------------------------------------------------

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session and not self._session.closed:
            return self._session
        timeout = aiohttp.ClientTimeout(total=25)
        self._session = aiohttp.ClientSession(timeout=timeout)
        self._owns_session = True
        return self._session

    async def aclose(self) -> None:
        """
        Standardized close for engines. Safe to call multiple times.
        """
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    # Backward compatible alias
    async def close(self) -> None:
        await self.aclose()

    async def _request_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        cache_key = f"json:{url}:{json.dumps(params, sort_keys=True) if params else ''}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        disk_key = None
        if self._disk_cache_dir:
            safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", cache_key)[:180]
            disk_key = os.path.join(self._disk_cache_dir, f"{safe}.json")

            try:
                if os.path.exists(disk_key):
                    if (time.time() - os.path.getmtime(disk_key)) <= self._cache.ttl_sec:
                        with open(disk_key, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        self._cache.set(cache_key, data)
                        return data
            except Exception:
                pass

        backoff = 0.6
        for _ in range(4):
            try:
                s = await self._get_session()
                async with s.get(url, params=params) as resp:
                    if resp.status in (429, 503, 502, 504):
                        await asyncio.sleep(backoff)
                        backoff *= 1.7
                        continue
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    self._cache.set(cache_key, data)

                    if disk_key:
                        try:
                            os.makedirs(self._disk_cache_dir, exist_ok=True)
                            with open(disk_key, "w", encoding="utf-8") as f:
                                json.dump(data, f)
                        except Exception:
                            pass

                    return data
            except Exception:
                await asyncio.sleep(backoff)
                backoff *= 1.7

        return None

    async def _request_text(self, url: str) -> Optional[str]:
        cache_key = f"text:{url}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        disk_key = None
        if self._disk_cache_dir:
            safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", cache_key)[:180]
            disk_key = os.path.join(self._disk_cache_dir, f"{safe}.txt")

            try:
                if os.path.exists(disk_key):
                    if (time.time() - os.path.getmtime(disk_key)) <= self._cache.ttl_sec:
                        with open(disk_key, "r", encoding="utf-8", errors="ignore") as f:
                            txt = f.read()
                        self._cache.set(cache_key, txt)
                        return txt
            except Exception:
                pass

        backoff = 0.6
        for _ in range(4):
            try:
                s = await self._get_session()
                async with s.get(url) as resp:
                    if resp.status in (429, 503, 502, 504):
                        await asyncio.sleep(backoff)
                        backoff *= 1.7
                        continue
                    if resp.status != 200:
                        return None
                    txt = await resp.text()
                    self._cache.set(cache_key, txt)

                    if disk_key:
                        try:
                            os.makedirs(self._disk_cache_dir, exist_ok=True)
                            with open(disk_key, "w", encoding="utf-8") as f:
                                f.write(txt)
                        except Exception:
                            pass

                    return txt
            except Exception:
                await asyncio.sleep(backoff)
                backoff *= 1.7

        return None

    # -------------------------------------------------
    # TEAM BASELINE (snapshot)
    # -------------------------------------------------

    async def fetch_team_baseline(self, team_abbr: str) -> Optional[Dict[str, Any]]:
        """
        Returns (or None):
          {
            "pts_for": float,
            "pts_against": float,
            "confidence": float (0..1),
            "source": "ESPN",
            "fetched_at": int
          }
        """
        abbr = (team_abbr or "").strip().lower()
        if not abbr:
            return None

        js = await self._request_json(f"{ESPN_BASE}/teams/{abbr}")
        if not js:
            return None

        items = js.get("team", {}).get("record", {}).get("items", [])
        stats: Dict[str, Any] = {}
        for it in items:
            for st in it.get("stats", []):
                nm = st.get("name")
                if nm:
                    stats[nm] = st.get("value")

        if "avgPointsFor" not in stats or "avgPointsAgainst" not in stats:
            return None

        return {
            "pts_for": float(stats["avgPointsFor"]),
            "pts_against": float(stats["avgPointsAgainst"]),
            "confidence": float(self.confidence),
            "source": self.name,
            "fetched_at": int(time.time()),
        }

    # -------------------------------------------------
    # RECENT GAMES (time-series, UTC)  ✅ NEW
    # -------------------------------------------------

    async def fetch_team_recent_games(
        self, league: str, team_abbr: str, n_games: int
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Adapter method required by TeamStatsAdapter contract.

        Returns list of per-game dicts in UTC:
        {
          "ts_utc": int,
          "pts_for": float,
          "pts_against": float,
          "pace": float,     # proxy if possessions not available
          "home": bool
        }

        Notes:
        - league is accepted for interface compatibility (ESPN endpoint is NBA-specific here).
        - We filter completed games only.
        """
        abbr = (team_abbr or "").strip().lower()
        if not abbr:
            return None

        # ESPN teams/<abbr>/schedule gives recent events with scores.
        js = await self._request_json(f"{ESPN_BASE}/teams/{abbr}/schedule")
        if not js:
            return None

        events = js.get("events")
        if not isinstance(events, list) or not events:
            return None

        out: List[Dict[str, Any]] = []

        # Iterate reverse chronological, collect finished games that include scores
        # ESPN "status" fields vary, so we use presence of numeric scores as completion signal.
        for ev in reversed(events):
            if len(out) >= int(n_games):
                break

            ts = _parse_espn_ts_utc(ev)
            if ts is None:
                continue

            # Ensure we can extract scores for this team
            score_tuple = _extract_scores_for_team(ev, abbr.upper())
            if not score_tuple:
                continue

            pf, pa, is_home = score_tuple
            total = float(pf + pa)

            out.append(
                {
                    "ts_utc": int(ts),
                    "pts_for": float(pf),
                    "pts_against": float(pa),
                    "pace": _pace_proxy_from_totals(total),
                    "home": bool(is_home),
                }
            )

        # Return newest->oldest or oldest->newest?
        # Store.append_game sorts by ts, so ordering not critical.
        return out if out else None

    # -------------------------------------------------
    # INJURIES
    # -------------------------------------------------

    async def _get_teams_directory(self) -> Optional[Dict[str, Any]]:
        cached = self._teams_cache.get("nba_teams_dir")
        if cached is not None:
            return cached

        js = await self._request_json(f"{ESPN_BASE}/teams")
        if not js:
            return None

        self._teams_cache.set("nba_teams_dir", js)
        return js

    async def resolve_team_injury_url(self, team_abbr: str) -> Optional[str]:
        abbr = (team_abbr or "").strip().lower()
        if not abbr:
            return None

        js = await self._get_teams_directory()
        if not js:
            return None

        teams = js.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", [])

        for t in teams:
            team = (t or {}).get("team") or {}
            if str(team.get("abbreviation", "")).lower() != abbr:
                continue
            for lk in team.get("links", []) or []:
                rel = lk.get("rel", []) or []
                href = lk.get("href")
                if href and "injuries" in rel:
                    return href
        return None

    @staticmethod
    def _parse_injuries_html(html_text: str) -> List[Dict[str, Any]]:
        if not html_text:
            return []

        txt = re.sub(r"\s+", " ", html_text)
        status_keywords = r"(Out|Day-To-Day|Questionable|Probable|Doubtful)"
        pattern = re.compile(
            r"([A-Z][A-Za-z\.\-\' ]{2,35})\s+[A-Z]{0,2}\s*Status\s+(" + status_keywords + r")",
            re.IGNORECASE,
        )

        injuries: List[Dict[str, Any]] = []
        for m in pattern.finditer(txt):
            injuries.append({"player": m.group(1).strip(), "status": m.group(2).strip()})
        return injuries

    async def fetch_team_injuries(self, team_abbr: str) -> Optional[Dict[str, Any]]:
        """
        Returns (or None):
          {
            "source": "ESPN",
            "team_abbr": "BKN",
            "injuries": [ {player, status}, ... ],
            "injury_count": int,
            "fetched_at": int,
            "url": str
          }
        """
        url = await self.resolve_team_injury_url(team_abbr)
        if not url:
            return None

        html_text = await self._request_text(url)
        if html_text is None:
            return None

        injuries = self._parse_injuries_html(html_text)
        return {
            "source": self.name,
            "team_abbr": team_abbr.upper(),
            "injuries": injuries,
            "injury_count": len(injuries),
            "fetched_at": int(time.time()),
            "url": url,
        }

    async def fetch_rotation_proxy(self, team_abbr: str) -> Optional[Dict[str, Any]]:
        """
        Rotation / roster stress proxy (injury-based).
        DOES NOT fabricate data.
        """
        inj = await self.fetch_team_injuries(team_abbr)
        if not inj:
            return None

        return {
            "source": self.name,
            "team_abbr": team_abbr.upper(),
            "injury_count": inj.get("injury_count", 0),
            "fetched_at": int(time.time()),
        }
