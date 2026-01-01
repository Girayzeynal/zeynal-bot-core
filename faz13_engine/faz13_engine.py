from __future__ import annotations

import html
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from baseline.team_baseline_store import TeamBaselineStore, TeamBaselineBootstrapper
from league_profiles import get_league_profile

# --- Multi-source provider layer (NBA first) ---
try:
    from providers import ESPNAdapter  # type: ignore
except Exception:  # pragma: no cover
    ESPNAdapter = None  # type: ignore

try:
    from core.aggregate_engine import aggregate_baseline  # type: ignore
except Exception:  # pragma: no cover
    def aggregate_baseline(rows):  # type: ignore
        if not rows:
            return None
        total_conf = sum(r.get('confidence', 0) for r in rows)
        if total_conf <= 0:
            return None
        return {
            'pts_for': sum(r['pts_for'] * r['confidence'] for r in rows) / total_conf,
            'pts_against': sum(r['pts_against'] * r['confidence'] for r in rows) / total_conf,
            'confidence': total_conf / len(rows),
            'sources': [r.get('source') for r in rows],
        }


# =====================================================
# DATA MODELS
# =====================================================

@dataclass(frozen=True)
class PrematchRequest:
    fixture_id: int
    league: str
    date_str: str
    home: str
    away: str


@dataclass
class TeamAverages:
    points_for: float
    points_against: float
    pace_hint: float
    stdev_hint: float


@dataclass
class FixtureContext:
    league: str
    date: str
    home: str
    away: str


@dataclass
class Faz13CoreOutput:
    ctx: FixtureContext
    home_avg: TeamAverages
    away_avg: TeamAverages
    total_band: Tuple[int, int]
    home_band: Tuple[int, int]
    away_band: Tuple[int, int]
    ou_direction: str
    quarters: Dict[str, Tuple[int, int]]
    blowout_risk: str
    tempo_flag: str
    notes: List[str] = field(default_factory=list)
    market: Dict[str, Any] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)

    def render_html(self) -> str:
        esc = html.escape
        out: List[str] = []
        out.append("FAZ-13 Ön Analiz")
        out.append(
            f"Maç: {esc(self.ctx.home)} vs {esc(self.ctx.away)} | "
            f"Lig: {esc(self.ctx.league)} | Tarih: {esc(self.ctx.date)}"
        )
        out.append("")
        out.append("Dar Bant")
        out.append(f"• Toplam: {self.total_band[0]}–{self.total_band[1]}")
        out.append(
            f"• Ev: {self.home_band[0]}–{self.home_band[1]} | "
            f"Dep: {self.away_band[0]}–{self.away_band[1]}"
        )
        out.append(f"• Alt/Üst yönü: {esc(self.ou_direction)}")

        out.append("")
        out.append("Risk Göstergeleri")
        out.append(f"• Blowout riski: {esc(self.blowout_risk)}")
        out.append(f"• Tempo flag: {esc(self.tempo_flag)}")

        if self.notes:
            out.append("")
            out.append("Notlar")
            for n in self.notes:
                out.append(f"• {esc(n)}")

        if self.market:
            out.append("")
            out.append("Market Entegrasyonu")
            for k, v in self.market.items():
                out.append(f"• {esc(str(k))}: {esc(str(v))}")

        if self.meta:
            out.append("")
            out.append("Meta Skor")
            for k, v in self.meta.items():
                out.append(f"• {esc(str(k))}: {esc(str(v))}")

        out.append("")
        out.append("Bu çıktı analiz/simülasyon amaçlıdır. Bahis tavsiyesi değildir.")
        return "\n".join(out)


# =====================================================
# FAZ-13 ENGINE (TEAM-FIRST)
# =====================================================

class Faz13Engine:
    """
    FAZ-13 Engine (TEAM-FIRST)
    - NBA season fix
    - API-Sports canonical team resolver (kept for ID + fallback)
    - NEW: ESPN provider baseline + confidence aggregation (NBA first)
    """

    def __init__(
        self,
        api_sports_key: str,
        api_sports_base: str,
        baseline_store: Optional[TeamBaselineStore] = None,
        min_baseline_games: int = 6,
    ) -> None:
        self.api_key = (api_sports_key or "").strip()
        self.base = (api_sports_base or "https://v1.basketball.api-sports.io").rstrip("/")
        self.session: Optional[aiohttp.ClientSession] = None

        self.baseline_store = baseline_store
        self.min_baseline_games = int(min_baseline_games)

        self.baseline_bootstrapper: Optional[TeamBaselineBootstrapper] = None
        if self.baseline_store is not None:
            self.baseline_bootstrapper = TeamBaselineBootstrapper(self.baseline_store, None)

        # ---- Canonical team map cache (API-Sports) ----
        # key: f"{LEAGUE}:{SEASON}"
        # value: {"ts": float, "team_map": {team_id: {...}}, "alias_index": {alias: team_id}}
        self._teammap_cache: Dict[str, Dict[str, Any]] = {}
        self._teammap_ttl_sec = int(os.getenv("FAZ13_TEAMMAP_TTL_SEC", "21600"))  # default 6h

        # NBA league id (API-Sports Basketball)
        self._nba_league_id = int(os.getenv("API_SPORTS_NBA_LEAGUE_ID", "12"))

    # -------------------------------------------------
    # NBA SEASON RESOLVER  (FIXED)
    # -------------------------------------------------
    @staticmethod
    def resolve_nba_season(date_str: str) -> str:
        """
        NBA sezonu Ekim'de başlar.
          - 2026-01-02 => 2025 season (2025-26)
          - 2026-11-02 => 2026 season (2026-27)
        """
        try:
            y = int(date_str[:4])
            m = int(date_str[5:7])
        except Exception:
            return date_str[:4]
        return str(y) if m >= 10 else str(y - 1)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session and not self.session.closed:
            return self.session
        self.session = aiohttp.ClientSession()
        return self.session

    # -------------------------------------------------
    # Canonical Team Map (API-Sports) - kept
    # -------------------------------------------------
    @staticmethod
    def _norm(s: str) -> str:
        return " ".join((s or "").strip().lower().replace("-", " ").replace("_", " ").split())

    def _cache_key(self, league: str, season: str) -> str:
        return f"{league.upper()}:{season}"

    def _teammap_cache_get(self, key: str) -> Optional[Dict[str, Any]]:
        entry = self._teammap_cache.get(key)
        if not entry:
            return None
        ts = float(entry.get("ts", 0))
        if (time.time() - ts) > self._teammap_ttl_sec:
            self._teammap_cache.pop(key, None)
            return None
        return entry

    def _teammap_cache_set(self, key: str, team_map: Dict[int, Dict[str, Any]], alias_index: Dict[str, int]) -> None:
        self._teammap_cache[key] = {
            "ts": time.time(),
            "team_map": team_map,
            "alias_index": alias_index,
        }

    # -------------------------------------------------
    # ESPN (NBA) TEAM ABBR RESOLVER (no key required)
    # -------------------------------------------------
    async def _espn_get_team_alias_index(self) -> Dict[str, str]:
        """
        Builds a normalized alias -> ESPN team abbreviation map using ESPN teams endpoint.
        Cached with TTL via _teammap_cache (separate key namespace).
        """
        cache_key = self._cache_key("NBA_ESPN_TEAMS", "0")
        cached = self._teammap_cache_get(cache_key)
        if cached:
            # reuse alias_index field to store alias->abbr
            return cached["alias_index"]

        s = await self._get_session()
        try:
            async with s.get(
                "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams",
                timeout=20,
            ) as r:
                js = await r.json()
        except Exception:
            return {}

        alias_index: Dict[str, str] = {}
        try:
            sports = js.get("sports") or []
            leagues = (sports[0].get("leagues") or []) if sports else []
            teams = (leagues[0].get("teams") or []) if leagues else []
        except Exception:
            teams = []

        for t in teams:
            team = (t or {}).get("team") or {}
            abbr = (team.get("abbreviation") or "").lower()
            display = team.get("displayName") or ""
            short = team.get("shortDisplayName") or ""
            name = team.get("name") or ""
            location = team.get("location") or ""
            nickname = team.get("nickname") or ""

            if not abbr:
                continue

            for raw in (display, short, name, location, nickname, abbr):
                key = self._norm(raw)
                if key:
                    alias_index.setdefault(key, abbr)

            combo = self._norm(f"{location} {name}")
            if combo:
                alias_index.setdefault(combo, abbr)

        # store into ttl cache structure
        self._teammap_cache_set(cache_key, team_map={}, alias_index=alias_index)  # type: ignore[arg-type]
        return alias_index

    async def _espn_resolve_abbr(self, team_name: str) -> Optional[str]:
        key = self._norm(team_name)
        if not key:
            return None
        idx = await self._espn_get_team_alias_index()
        return idx.get(key)

    async def _fetch_teams_for_league(self, league: str, season: str) -> List[Dict[str, Any]]:
        if not self.api_key:
            return []

        s = await self._get_session()
        headers = {"x-apisports-key": self.api_key}

        if league.upper() == "NBA":
            try:
                async with s.get(
                    f"{self.base}/teams",
                    params={"league": self._nba_league_id, "season": season},
                    headers=headers,
                    timeout=20,
                ) as r:
                    js = await r.json()
            except Exception:
                return []
            return js.get("response") or []

        return []

    async def _build_canonical_team_map(self, league: str, season: str) -> Tuple[Dict[int, dict], Dict[str, int]]:
        ck = self._cache_key(league, season)
        cached = self._teammap_cache_get(ck)
        if cached:
            return cached["team_map"], cached["alias_index"]

        team_map: Dict[int, dict] = {}
        alias_index: Dict[str, int] = {}

        teams = await self._fetch_teams_for_league(league, season)

        for t in teams:
            obj = t.get("team") if isinstance(t, dict) and "team" in t else t
            if not isinstance(obj, dict):
                continue

            team_id = obj.get("id")
            if not team_id:
                continue

            name = obj.get("name") or ""
            code = obj.get("code") or ""
            city = obj.get("city") or ""
            nickname = obj.get("nickname") or ""

            aliases = set()

            aliases.add(self._norm(name))
            if code:
                aliases.add(self._norm(code))
            if city and nickname:
                aliases.add(self._norm(f"{city} {nickname}"))
            if city and name:
                aliases.add(self._norm(f"{city} {name}"))
            if nickname:
                aliases.add(self._norm(nickname))

            team_map[int(team_id)] = {
                "id": int(team_id),
                "name": name,
                "code": code,
                "aliases": aliases,
            }

        for tid, info in team_map.items():
            for a in info.get("aliases", set()):
                if a:
                    alias_index.setdefault(a, tid)

        self._teammap_cache_set(ck, team_map, alias_index)
        return team_map, alias_index

    async def _resolve_team_id(self, team_name: str, league: str, season: str) -> Optional[int]:
        if not self.api_key:
            return None

        key = self._norm(team_name)

        if league.upper() == "NBA":
            _, alias_index = await self._build_canonical_team_map(league, season)
            tid = alias_index.get(key)
            if tid:
                return tid

        s = await self._get_session()
        headers = {"x-apisports-key": self.api_key}
        try:
            async with s.get(
                f"{self.base}/teams",
                params={"search": team_name},
                headers=headers,
                timeout=15,
            ) as r:
                js = await r.json()
        except Exception:
            return None

        resp = js.get("response") or []
        if not resp:
            return None

        obj = resp[0].get("team") if isinstance(resp[0], dict) and "team" in resp[0] else resp[0]
        if isinstance(obj, dict) and obj.get("id"):
            return int(obj["id"])
        return None

    # -------------------------------------------------
    # API-Sports TEAM BASELINE (TEAM_ID FIRST) - kept as fallback
    # -------------------------------------------------
    async def _api_sports_team_baseline_by_id(
        self, team_id: int, league: str, season: str
    ) -> Optional[Tuple[float, float, float, float, int]]:
        if not self.api_key:
            return None

        s = await self._get_session()
        headers = {"x-apisports-key": self.api_key}

        try:
            async with s.get(
                f"{self.base}/statistics",
                params={"team": int(team_id), "season": season},
                headers=headers,
                timeout=15,
            ) as r:
                js = await r.json()
        except Exception:
            return None

        resp = js.get("response") or {}
        pf = resp.get("points", {}).get("for", {}).get("average", {}).get("total")
        pa = resp.get("points", {}).get("against", {}).get("average", {}).get("total")

        if pf is None or pa is None:
            return None

        profile = get_league_profile(league)
        pace = max(0.8, min(1.3, (float(pf) + float(pa)) / 180.0))
        stdev = max(profile.volatility_floor, min(profile.volatility_ceil, 10.0))

        return float(pf), float(pa), pace, stdev, 5

    async def run_prematch(self, req: PrematchRequest) -> Faz13CoreOutput:
        profile = get_league_profile(req.league)

        # NBA season fix (important for any source)
        season = (
            self.resolve_nba_season(req.date_str)
            if req.league.upper() == "NBA"
            else req.date_str[:4]
        )

        notes: List[str] = [f"Season: {season}", "TEAM-FIRST mode (MULTI-SOURCE)"]

        # 1) Resolve team IDs (API-Sports) for diagnostics + fallback
        home_id = await self._resolve_team_id(req.home, req.league, season)
        away_id = await self._resolve_team_id(req.away, req.league, season)

        # 2) Primary baseline path (NBA): ESPN (no key), aggregated (confidence aware)
        home_rows: List[Dict[str, Any]] = []
        away_rows: List[Dict[str, Any]] = []

        if req.league.upper() == "NBA" and ESPNAdapter is not None:
            espn = ESPNAdapter()
            home_abbr = await self._espn_resolve_abbr(req.home)
            away_abbr = await self._espn_resolve_abbr(req.away)

            if home_abbr:
                r = await espn.fetch_team_baseline(home_abbr)  # type: ignore[attr-defined]
                if r:
                    home_rows.append(r)
            if away_abbr:
                r = await espn.fetch_team_baseline(away_abbr)  # type: ignore[attr-defined]
                if r:
                    away_rows.append(r)

            if home_abbr or away_abbr:
                notes.append(f"ESPN abbr: home={home_abbr} away={away_abbr}")

        home_baseline = aggregate_baseline(home_rows) if home_rows else None
        away_baseline = aggregate_baseline(away_rows) if away_rows else None

        # 3) Fallback: API-Sports statistics by ID (when ESPN missing or partial)
        if home_baseline is None and home_id:
            h = await self._api_sports_team_baseline_by_id(home_id, req.league, season)
            if h:
                home_baseline = {
                    "pts_for": float(h[0]),
                    "pts_against": float(h[1]),
                    "pace": float(h[2]),
                    "stdev": float(h[3]),
                    "confidence": 0.55,
                    "sources": ["API_SPORTS"],
                }
        if away_baseline is None and away_id:
            a = await self._api_sports_team_baseline_by_id(away_id, req.league, season)
            if a:
                away_baseline = {
                    "pts_for": float(a[0]),
                    "pts_against": float(a[1]),
                    "pace": float(a[2]),
                    "stdev": float(a[3]),
                    "confidence": 0.55,
                    "sources": ["API_SPORTS"],
                }

        if not home_baseline or not away_baseline:
            ctx = FixtureContext(req.league, req.date_str, req.home, req.away)
            miss = []
            if not home_baseline:
                miss.append("home")
            if not away_baseline:
                miss.append("away")
            notes.append(f"NO_PLAY: BASELINE_NOT_AVAILABLE ({','.join(miss)})")
            return Faz13CoreOutput(
                ctx=ctx,
                home_avg=TeamAverages(0, 0, 1, 9),
                away_avg=TeamAverages(0, 0, 1, 9),
                total_band=(0, 0),
                home_band=(0, 0),
                away_band=(0, 0),
                ou_direction="NO_PLAY",
                quarters={},
                blowout_risk="UNKNOWN",
                tempo_flag="UNKNOWN",
                notes=notes,
                market={},
                meta={
                    "season": season,
                    "team_first": True,
                    "baseline_missing": True,
                    "home_id": home_id,
                    "away_id": away_id,
                    "sources_home": (home_baseline or {}).get("sources"),
                    "sources_away": (away_baseline or {}).get("sources"),
                    "confidence": 0.0,
                },
            )

        # Convert to TeamAverages
        def _pace_from_pts(pf: float, pa: float) -> float:
            pace = (pf + pa) / 180.0 if (pf + pa) > 0 else 1.0
            return max(0.8, min(1.3, pace))

        h_pf = float(home_baseline["pts_for"])
        h_pa = float(home_baseline["pts_against"])
        a_pf = float(away_baseline["pts_for"])
        a_pa = float(away_baseline["pts_against"])

        h_pace = float(home_baseline.get("pace", _pace_from_pts(h_pf, h_pa)))
        a_pace = float(away_baseline.get("pace", _pace_from_pts(a_pf, a_pa)))

        h_stdev = float(home_baseline.get("stdev", max(profile.volatility_floor, min(profile.volatility_ceil, 10.0))))
        a_stdev = float(away_baseline.get("stdev", max(profile.volatility_floor, min(profile.volatility_ceil, 10.0))))

        h_avg = TeamAverages(h_pf, h_pa, h_pace, h_stdev)
        a_avg = TeamAverages(a_pf, a_pa, a_pace, a_stdev)

        # Classic FAZ-13 math
        home_mu = (h_avg.points_for + a_avg.points_against) / 2
        away_mu = (a_avg.points_for + h_avg.points_against) / 2
        total_mu = home_mu + away_mu

        total_band = (
            int(total_mu - profile.band_hw_total),
            int(total_mu + profile.band_hw_total),
        )
        home_band = (
            int(home_mu - profile.band_hw_team),
            int(home_mu + profile.band_hw_team),
        )
        away_band = (
            int(away_mu - profile.band_hw_team),
            int(away_mu + profile.band_hw_team),
        )

        sources_home = home_baseline.get("sources") or home_baseline.get("sources_home") or home_baseline.get("source")
        sources_away = away_baseline.get("sources") or away_baseline.get("sources_away") or away_baseline.get("source")
        notes.append(f"Sources(home)={sources_home}")
        notes.append(f"Sources(away)={sources_away}")

        conf_home = float(home_baseline.get("confidence", 0.5))
        conf_away = float(away_baseline.get("confidence", 0.5))
        meta_conf = min(conf_home, conf_away)

        ctx = FixtureContext(req.league, req.date_str, req.home, req.away)

        return Faz13CoreOutput(
            ctx=ctx,
            home_avg=h_avg,
            away_avg=a_avg,
            total_band=total_band,
            home_band=home_band,
            away_band=away_band,
            ou_direction="NO_EDGE",
            quarters={},
            blowout_risk="LOW",
            tempo_flag="NORMAL",
            notes=notes,
            market={},
            meta={
                "season": season,
                "team_first": True,
                "baseline_missing": False,
                "home_id": home_id,
                "away_id": away_id,
                "confidence": round(meta_conf * 100, 1),
                "sources_home": sources_home,
                "sources_away": sources_away,
            },
        ) 
