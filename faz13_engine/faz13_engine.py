from __future__ import annotations

import html
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from league_profiles import get_league_profile

try:
    from providers.espn_adapter import ESPNAdapter
except Exception:
    ESPNAdapter = None


# =====================================================
# NBA TEAM MAP (SAFE)
# =====================================================

NBA_TEAM_MAP = {
    "atlanta hawks": "ATL",
    "boston celtics": "BOS",
    "brooklyn nets": "BKN",
    "charlotte hornets": "CHA",
    "chicago bulls": "CHI",
    "cleveland cavaliers": "CLE",
    "dallas mavericks": "DAL",
    "denver nuggets": "DEN",
    "detroit pistons": "DET",
    "golden state warriors": "GSW",
    "houston rockets": "HOU",
    "indiana pacers": "IND",
    "los angeles clippers": "LAC",
    "los angeles lakers": "LAL",
    "memphis grizzlies": "MEM",
    "miami heat": "MIA",
    "milwaukee bucks": "MIL",
    "minnesota timberwolves": "MIN",
    "new orleans pelicans": "NOP",
    "new york knicks": "NYK",
    "oklahoma city thunder": "OKC",
    "orlando magic": "ORL",
    "philadelphia 76ers": "PHI",
    "phoenix suns": "PHX",
    "portland trail blazers": "POR",
    "sacramento kings": "SAC",
    "san antonio spurs": "SAS",
    "toronto raptors": "TOR",
    "utah jazz": "UTA",
    "washington wizards": "WAS",
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
    pace: float
    stdev: float


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

        if self.meta:
            out.append("")
            out.append("Meta")
            for k, v in self.meta.items():
                out.append(f"• {esc(str(k))}: {esc(str(v))}")

        out.append("")
        out.append("Bu çıktı analiz/simülasyon amaçlıdır. Bahis tavsiyesi değildir.")
        return "\n".join(out)


# =====================================================
# FAZ-13 ENGINE (FINAL — SYNTAX SAFE)
# =====================================================

class Faz13Engine:
    def __init__(self, *args, **kwargs) -> None:
        self.espn = ESPNAdapter() if ESPNAdapter else None

    @staticmethod
    def _tempo_flag(pace: float) -> str:
        if pace >= 102:
            return "FAST"
        if pace <= 97:
            return "SLOW"
        return "NORMAL"

    async def _team_baseline(
        self, league: str, team: str
    ) -> Tuple[float, float, float, str]:

        key = team.lower().strip()
        abbr = NBA_TEAM_MAP.get(key)

        if self.espn and abbr:
            try:
                games = await self.espn.fetch_team_recent_games("NBA", abbr, 5)
                if games:
                    pf_sum = 0.0
                    pa_sum = 0.0
                    pace_sum = 0.0
                    count = len(games)

                    for g in games:
                        pf_sum += g["pts_for"]
                        pa_sum += g["pts_against"]
                        pace_sum += g["pace"]

                    return (
                        pf_sum / count,
                        pa_sum / count,
                        pace_sum / count,
                        "ESPN_LAST5",
                    )
            except Exception:
                pass

        return 113.5, 113.5, 99.5, "LEAGUE_AVG"

    async def run_prematch(self, req: PrematchRequest) -> Faz13CoreOutput:
        profile = get_league_profile(req.league)

        h_pf, h_pa, h_pace, h_src = await self._team_baseline(
            req.league, req.home
        )
        a_pf, a_pa, a_pace, a_src = await self._team_baseline(
            req.league, req.away
        )

        home_mu = (h_pf + a_pa) / 2.0
        away_mu = (a_pf + h_pa) / 2.0
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

        pace_mean = (h_pace + a_pace) / 2.0
        tempo_flag = self._tempo_flag(pace_mean)

        quarters = {
            "1Q": (int(total_mu * 0.24) - 3, int(total_mu * 0.24) + 3),
            "2Q": (int(total_mu * 0.26) - 3, int(total_mu * 0.26) + 3),
            "3Q": (int(total_mu * 0.25) - 3, int(total_mu * 0.25) + 3),
            "4Q": (int(total_mu * 0.25) - 3, int(total_mu * 0.25) + 3),
        }

        ctx = FixtureContext(
            league=req.league,
            date=req.date_str,
            home=req.home,
            away=req.away,
        )

        return Faz13CoreOutput(
            ctx=ctx,
            home_avg=TeamAverages(h_pf, h_pa, h_pace, 10.0),
            away_avg=TeamAverages(a_pf, a_pa, a_pace, 10.0),
            total_band=total_band,
            home_band=home_band,
            away_band=away_band,
            ou_direction="NO_EDGE",
            quarters=quarters,
            blowout_risk="LOW",
            tempo_flag=tempo_flag,
            notes=[
                "FAZ-13 FINAL SYNTAX SAFE",
                f"Home baseline: {h_src}",
                f"Away baseline: {a_src}",
            ],
            meta={
                "engine": "FAZ-13 FINAL",
                "home_src": h_src,
                "away_src": a_src,
                "expected_total": round(total_mu, 2),
                "pace_mean": pace_mean,
                "degraded_mode": h_src == "LEAGUE_AVG" or a_src == "LEAGUE_AVG",
                "generated_at": int(time.time()),
            },
        )
