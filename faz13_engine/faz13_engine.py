# faz13_engine/faz13_engine.py
from __future__ import annotations

import asyncio
import html
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from baseline.team_baseline_store import (
    TeamBaselineStore,
    TeamBaselineBootstrapper,
    TeamStatsAdapter,
    TeamBaseline,
)
from league_profiles import get_league_profile


# =========================
# DATA STRUCTURES
# =========================

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

    @property
    def is_valid(self) -> bool:
        return (
            self.meta.get("home_baseline_src") not in (None, "none")
            and self.meta.get("away_baseline_src") not in (None, "none")
        )

    def render_html(self) -> str:
        esc = html.escape
        lines: List[str] = []
        lines.append("FAZ-13 Ön Analiz")
        lines.append(
            f"Maç: {esc(self.ctx.home)} vs {esc(self.ctx.away)} | "
            f"Lig: {esc(self.ctx.league)} | Tarih: {esc(self.ctx.date)}"
        )
        lines.append("")
        lines.append("Dar Bant")
        lines.append(f"• Toplam: {self.total_band[0]}–{self.total_band[1]}")
        lines.append(
            f"• Ev: {self.home_band[0]}–{self.home_band[1]} | "
            f"Dep: {self.away_band[0]}–{self.away_band[1]}"
        )
        lines.append(f"• Alt/Üst yönü: {esc(self.ou_direction)}")
        lines.append("")
        lines.append("Risk Göstergeleri")
        lines.append(f"• Blowout riski: {esc(self.blowout_risk)}")
        lines.append(f"• Tempo flag: {esc(self.tempo_flag)}")
        if self.notes:
            lines.append("")
            lines.append("Notlar")
            for n in self.notes:
                lines.append(f"• {esc(n)}")
        return "\n".join(lines)


# =========================
# HELPERS
# =========================

class _TTLCache:
    def __init__(self, ttl_sec: float = 25.0) -> None:
        self.ttl = ttl_sec
        self._data: Dict[str, Tuple[float, Any]] = {}

    def get(self, key: str) -> Any:
        hit = self._data.get(key)
        if not hit:
            return None
        ts, val = hit
        if time.time() - ts > self.ttl:
            self._data.pop(key, None)
            return None
        return val

    def set(self, key: str, value: Any) -> None:
        self._data[key] = (time.time(), value)


# =========================
# ENGINE
# =========================

class Faz13Engine:
    """
    FAZ-13: TEAM BASELINE ENGINE
    - NBA season fix
    - BallDontLie: en güncel ve tamamlanmış maçlar
    - Minimum NBA örnek sayısı: 12
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
        self.cache = _TTLCache()

        self._league_id_map: Dict[str, int] = self._load_league_id_map()
        self.baseline_store = baseline_store
        self.min_baseline_games = min_baseline_games
        self.baseline_bootstrapper: Optional[TeamBaselineBootstrapper] = None

        self._bdl_team_map: Optional[Dict[str, int]] = None

    # =========================
    # NBA SEASON FIX
    # =========================
    def _season_for_league(self, league: str, date_str: str) -> str:
        try:
            y = int(str(date_str)[:4])
            m = int(str(date_str)[5:7])
        except Exception:
            return str(date_str).split("-")[0]

        profile = get_league_profile(league)
        if profile.name.upper() == "NBA":
            # Oct–Dec => same year, Jan–Sep => previous year
            season_year = y if m >= 10 else (y - 1)
            return str(season_year)

        return str(y)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session and not self.session.closed:
            return self.session
        self.session = aiohttp.ClientSession()
        return self.session

    # =========================
    # BALLDONTLIE (NBA)
    # =========================
    async def _bdl_load_team_map(self) -> Dict[str, int]:
        if self._bdl_team_map is not None:
            return self._bdl_team_map

        s = await self._get_session()
        headers = {"Authorization": os.getenv("BALLDONTLIE_API_KEY", "")}
        async with s.get(
            "https://api.balldontlie.io/nba/v1/teams",
            headers=headers,
            timeout=20,
        ) as resp:
            js = await resp.json()

        out: Dict[str, int] = {}
        for t in js.get("data", []) or []:
            tid = t.get("id")
            if isinstance(tid, int):
                name = (t.get("full_name") or "").lower()
                out[name] = tid

        self._bdl_team_map = out
        return out

    async def _bdl_team_baseline(
        self,
        team: str,
        season: str,
        profile_name: str,
    ) -> Optional[Tuple[float, float, float, float, int]]:

        if profile_name.upper() != "NBA":
            return None

        team_map = await self._bdl_load_team_map()
        tid = team_map.get(team.strip().lower())
        if not tid:
            return None

        s = await self._get_session()
        headers = {"Authorization": os.getenv("BALLDONTLIE_API_KEY", "")}

        async with s.get(
            "https://api.balldontlie.io/nba/v1/games",
            params={"seasons[]": season, "team_ids[]": tid, "per_page": 100},
            headers=headers,
            timeout=20,
        ) as resp:
            js = await resp.json()

        games = js.get("data") or []
        if not games:
            return None

        # 🔥 FIX: en güncel maçlar önce
        games = sorted(games, key=lambda g: str(g.get("date") or ""), reverse=True)

        scored: List[float] = []
        allowed: List[float] = []
        totals: List[float] = []

        for g in games:
            hs = g.get("home_team_score")
            vs = g.get("visitor_team_score")
            if hs is None or vs is None:
                continue

            hid = (g.get("home_team") or {}).get("id")
            vid = (g.get("visitor_team") or {}).get("id")

            if hid == tid:
                scored.append(float(hs))
                allowed.append(float(vs))
            elif vid == tid:
                scored.append(float(vs))
                allowed.append(float(hs))
            else:
                continue

            totals.append(float(hs) + float(vs))

            if len(scored) >= max(self.min_baseline_games, 12):
                break

        if len(scored) < max(self.min_baseline_games, 12):
            return None

        pf = sum(scored) / len(scored)
        pa = sum(allowed) / len(allowed)
        pace = (pf + pa) / 180.0 if (pf + pa) > 0 else 1.0
        pace = max(0.70, min(1.35, pace))

        mean_total = sum(totals) / len(totals)
        var = sum((x - mean_total) ** 2 for x in totals) / max(1, (len(totals) - 1))
        stdev_total = var ** 0.5

        return pf, pa, pace, stdev_total, len(scored)

    # =========================
    # MAIN PREMATCH
    # =========================
    async def run_prematch(self, req: PrematchRequest) -> Faz13CoreOutput:
        profile = get_league_profile(req.league)

        # ✅ FIXED SEASON
        season = self._season_for_league(req.league, req.date_str)

        (h_avg, h_src, h_n), (a_avg, a_src, a_n) = await asyncio.gather(
            self._team_baseline(req.home, req.league, season),
            self._team_baseline(req.away, req.league, season),
        )

        home_mu = (h_avg.points_for + a_avg.points_against) / 2
        away_mu = (a_avg.points_for + h_avg.points_against) / 2
        total_mu = home_mu + away_mu

        hw_total = profile.band_hw_total
        hw_team = profile.band_hw_team

        total_band = (
            int(round(total_mu - hw_total)),
            int(round(total_mu + hw_total)),
        )
        home_band = (
            int(round(home_mu - hw_team)),
            int(round(home_mu + hw_team)),
        )
        away_band = (
            int(round(away_mu - hw_team)),
            int(round(away_mu + hw_team)),
        )

        notes = [
            f"NBA season={season}",
            f"Baseline(home)={h_src} n={h_n}",
            f"Baseline(away)={a_src} n={a_n}",
        ]

        return Faz13CoreOutput(
            ctx=FixtureContext(req.league, req.date_str, req.home, req.away),
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
            meta={
                "home_baseline_src": h_src,
                "away_baseline_src": a_src,
            },
    ) 
