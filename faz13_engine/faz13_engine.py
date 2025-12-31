
from __future__ import annotations

import html
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from baseline.team_baseline_store import TeamBaselineStore, TeamBaselineBootstrapper
from league_profiles import get_league_profile


# =====================================================
# NBA CANONICAL TEAM MAP (API-Sports uyumlu)
# =====================================================

NBA_TEAM_CANONICAL = {
    "atlanta hawks": "Hawks",
    "boston celtics": "Celtics",
    "brooklyn nets": "Nets",
    "charlotte hornets": "Hornets",
    "chicago bulls": "Bulls",
    "cleveland cavaliers": "Cavaliers",
    "dallas mavericks": "Mavericks",
    "denver nuggets": "Nuggets",
    "detroit pistons": "Pistons",
    "golden state warriors": "Warriors",
    "houston rockets": "Rockets",
    "indiana pacers": "Pacers",
    "los angeles clippers": "Clippers",
    "los angeles lakers": "Lakers",
    "memphis grizzlies": "Grizzlies",
    "miami heat": "Heat",
    "milwaukee bucks": "Bucks",
    "minnesota timberwolves": "Timberwolves",
    "new orleans pelicans": "Pelicans",
    "new york knicks": "Knicks",
    "oklahoma city thunder": "Thunder",
    "orlando magic": "Magic",
    "philadelphia 76ers": "76ers",
    "phoenix suns": "Suns",
    "portland trail blazers": "Blazers",
    "sacramento kings": "Kings",
    "san antonio spurs": "Spurs",
    "toronto raptors": "Raptors",
    "utah jazz": "Jazz",
    "washington wizards": "Wizards",
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

    # -------------------------------------------------
    # NBA SEASON RESOLVER
    # -------------------------------------------------
    @staticmethod
    def resolve_nba_season(date_str: str) -> str:
        try:
            y = int(date_str[:4])
            m = int(date_str[5:7])
        except Exception:
            return date_str[:4]
        return str(y + 1) if m >= 10 else str(y)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session and not self.session.closed:
            return self.session
        self.session = aiohttp.ClientSession()
        return self.session

    # -------------------------------------------------
    # API-Sports TEAM BASELINE (CANONICAL MAP)
    # -------------------------------------------------
    async def _api_sports_team_baseline(
        self, team: str, league: str, season: str
    ) -> Optional[Tuple[float, float, float, float, int]]:
        if not self.api_key:
            return None

        search_name = team
        if league.upper() == "NBA":
            search_name = NBA_TEAM_CANONICAL.get(team.lower(), team)

        s = await self._get_session()
        headers = {"x-apisports-key": self.api_key}

        try:
            async with s.get(
                f"{self.base}/teams",
                params={"search": search_name},
                headers=headers,
                timeout=15,
            ) as r:
                js = await r.json()
        except Exception:
            return None

        teams = js.get("response") or []
        if not teams:
            return None

        team_id = teams[0].get("id")
        if not team_id:
            return None

        try:
            async with s.get(
                f"{self.base}/statistics",
                params={"team": team_id, "season": season},
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
        pace = max(0.8, min(1.3, (pf + pa) / 180.0))
        stdev = max(profile.volatility_floor, min(profile.volatility_ceil, 10.0))

        return float(pf), float(pa), pace, stdev, 5

    # -------------------------------------------------
    # MAIN PREMATCH (TEAM-FIRST)
    # -------------------------------------------------
    async def run_prematch(self, req: PrematchRequest) -> Faz13CoreOutput:
        profile = get_league_profile(req.league)

        season = (
            self.resolve_nba_season(req.date_str)
            if req.league.upper() == "NBA"
            else req.date_str[:4]
        )

        h = await self._api_sports_team_baseline(req.home, req.league, season)
        a = await self._api_sports_team_baseline(req.away, req.league, season)

        # TEAM-FIRST: takım verisi yoksa NO_PLAY
        if not h or not a:
            ctx = FixtureContext(req.league, req.date_str, req.home, req.away)
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
                notes=["NO_PLAY: TEAM_BASELINE_MISSING"],
                market={},
                meta={
                    "season": season,
                    "team_first": True,
                    "baseline_missing": True,
                },
            )

        h_avg = TeamAverages(h[0], h[1], h[2], h[3])
        a_avg = TeamAverages(a[0], a[1], a[2], a[3])

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
            notes=[
                f"Season: {season}",
                "TEAM-FIRST mode (API-Sports)",
            ],
            market={},
            meta={
                "season": season,
                "team_first": True,
                "baseline_quality": 1.0,
            },
        )
