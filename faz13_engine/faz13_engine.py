from __future__ import annotations

import asyncio
import html
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
import requests

from baseline.team_baseline_store import (
    TeamBaselineStore,
    TeamBaselineBootstrapper,
    TeamStatsAdapter,
)
from league_profiles import get_league_profile


# =========================
# BALLDONTLIE API HELPER
# =========================
def fetch_team_stats_from_bdl(team_id: int, season: int) -> Dict[str, Any]:
    api_key = os.getenv("BALLDONTLIE_API_KEY")
    if not api_key:
        raise RuntimeError("BALLDONTLIE_API_KEY ortam değişkeni tanımlı değil")

    headers = {"Authorization": api_key}
    url = "https://api.balldontlie.io/nba/v1/stats"
    params = {
        "team_ids[]": team_id,
        "season": season,
        "per_page": 100,
    }

    resp = requests.get(url, headers=headers, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


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
        lines = []
        lines.append("FAZ-13 Ön Analiz")
        lines.append(
            f"Maç: {esc(self.ctx.home)} vs {esc(self.ctx.away)} | Lig: {esc(self.ctx.league)} | Tarih: {esc(self.ctx.date)}"
        )
        lines.append("")
        lines.append("Dar Bant")
        lines.append(f"• Toplam: {self.total_band[0]}–{self.total_band[1]}")
        lines.append(f"• Ev: {self.home_band[0]}–{self.home_band[1]} | Dep: {self.away_band[0]}–{self.away_band[1]}")
        lines.append(f"• Alt/Üst yönü: {esc(self.ou_direction)}")
        lines.append("")
        lines.append("Periyot Bantları")
        for k, (lo, hi) in self.quarters.items():
            lines.append(f"• {k}: {lo}–{hi}")
        lines.append("")
        lines.append("Risk Göstergeleri")
        lines.append(f"• Blowout riski: {esc(self.blowout_risk)}")
        lines.append(f"• Tempo flag: {esc(self.tempo_flag)}")
        if self.notes:
            lines.append("")
            lines.append("Notlar")
            for n in self.notes:
                lines.append(f"• {esc(n)}")
        if self.market:
            lines.append("")
            lines.append("Market Entegrasyonu")
            for k, v in self.market.items():
                lines.append(f"• {esc(str(k))}: {esc(str(v))}")
        lines.append("")
        lines.append("Bu çıktı analiz/simülasyon amaçlıdır. Bahis tavsiyesi değildir.")
        return "\n".join(lines)


# =========================
# ENGINE
# =========================
class Faz13Engine:
    def __init__(
        self,
        api_sports_key: str,
        api_sports_base: str,
        baseline_store: Optional[TeamBaselineStore] = None,
        min_baseline_games: int = 6,
    ) -> None:
        self.api_key = api_sports_key
        self.base = api_sports_base.rstrip("/")
        self.session: Optional[aiohttp.ClientSession] = None
        self.baseline_store = baseline_store
        self.min_baseline_games = min_baseline_games
        self.baseline_bootstrapper = (
            TeamBaselineBootstrapper(baseline_store, TeamStatsAdapter({}))
            if baseline_store
            else None
        )

    async def run_prematch(self, req: PrematchRequest) -> Faz13CoreOutput:
        profile = get_league_profile(req.league)

        # === TEMP: BALLDONTLIE TEST BASELINE ===
        # (Örnek team_id ile – sen mapping ekleyebilirsin)
        try:
            data = fetch_team_stats_from_bdl(team_id=14, season=int(req.date_str[:4]))
            avg_points = data["data"][0]["pts"]
            home_avg = TeamAverages(avg_points, avg_points, 1.0, 9.0)
            away_avg = TeamAverages(avg_points, avg_points, 1.0, 9.0)
            src = "balldontlie"
        except Exception:
            home_avg = TeamAverages(0, 0, 1.0, 9.0)
            away_avg = TeamAverages(0, 0, 1.0, 9.0)
            src = "none"

        total_mu = home_avg.points_for + away_avg.points_for
        hw = profile.band_hw_total

        ctx = FixtureContext(req.league, req.date_str, req.home, req.away)

        return Faz13CoreOutput(
            ctx=ctx,
            home_avg=home_avg,
            away_avg=away_avg,
            total_band=(int(total_mu - hw), int(total_mu + hw)),
            home_band=(0, 0),
            away_band=(0, 0),
            ou_direction="NO_EDGE",
            quarters={"FT": (int(total_mu - hw), int(total_mu + hw))},
            blowout_risk="LOW",
            tempo_flag="NORMAL",
            notes=[f"Baseline source: {src}"],
            meta={
                "home_baseline_src": src,
                "away_baseline_src": src,
            },
        ) 
