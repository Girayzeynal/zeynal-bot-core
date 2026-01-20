from __future__ import annotations

import html
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from league_profiles import get_league_profile


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
# FAZ-13 ENGINE (FINAL / SURVIVAL / BACKWARD SAFE)
# =====================================================

class Faz13Engine:
    """
    FAZ-13 FINAL ENGINE
    - main.py ile %100 uyumlu
    - Reboot-safe
    - Asla 0–0 dönmez
    """

    def __init__(
        self,
        api_sports_key: Optional[str] = None,
        api_sports_base: Optional[str] = None,
        baseline_store: Any = None,
        **kwargs,
    ) -> None:
        self.api_sports_key = api_sports_key
        self.api_sports_base = api_sports_base
        self.baseline_store = baseline_store
        self.extra_args = kwargs

    # -------------------------------------------------

    @staticmethod
    def _tempo_flag(pace: float) -> str:
        if pace >= 102:
            return "FAST"
        if pace <= 97:
            return "SLOW"
        return "NORMAL"

    # -------------------------------------------------

    async def run_prematch(self, req: PrematchRequest) -> Faz13CoreOutput:
        profile = get_league_profile(req.league)

        # -------------------------------------------------
        # SURVIVAL MODE – LEAGUE AVERAGE
        # -------------------------------------------------
        if req.league.upper() == "NBA":
            league_avg = {
                "pts_for": 113.5,
                "pts_against": 113.5,
                "pace": 99.5,
                "stdev": 10.0,
            }
        else:
            league_avg = {
                "pts_for": 80.0,
                "pts_against": 80.0,
                "pace": 95.0,
                "stdev": 9.0,
            }

        notes = [
            "FAZ-13 FINAL ENGINE",
            "SURVIVAL MODE ACTIVE",
            "Baseline: LEAGUE AVERAGE",
        ]

        home_avg = TeamAverages(
            league_avg["pts_for"],
            league_avg["pts_against"],
            league_avg["pace"],
            league_avg["stdev"],
        )

        away_avg = TeamAverages(
            league_avg["pts_for"],
            league_avg["pts_against"],
            league_avg["pace"],
            league_avg["stdev"],
        )

        # -------------------------------------------------
        # EXPECTED VALUES
        # -------------------------------------------------
        home_mu = (home_avg.points_for + away_avg.points_against) / 2
        away_mu = (away_avg.points_for + home_avg.points_against) / 2
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

        pace_mean = (home_avg.pace + away_avg.pace) / 2
        tempo_flag = self._tempo_flag(pace_mean)

        quarters = {
            "1Q": (int(total_mu * 0.24) - 3, int(total_mu * 0.24) + 3),
            "2Q": (int(total_mu * 0.26) - 3, int(total_mu * 0.26) + 3),
            "3Q": (int(total_mu * 0.25) - 3, int(total_mu * 0.25) + 3),
            "4Q": (int(total_mu * 0.25) - 3, int(total_mu * 0.25) + 3),
        }

        ctx = FixtureContext(req.league, req.date_str, req.home, req.away)

        return Faz13CoreOutput(
            ctx=ctx,
            home_avg=home_avg,
            away_avg=away_avg,
            total_band=total_band,
            home_band=home_band,
            away_band=away_band,
            ou_direction="NO_EDGE",
            quarters=quarters,
            blowout_risk="LOW",
            tempo_flag=tempo_flag,
            notes=notes,
            meta={
                "engine": "FAZ-13 FINAL",
                "baseline_src": "LEAGUE_AVG",
                "expected_total": round(total_mu, 2),
                "pace_mean": pace_mean,
                "degraded_mode": True,
                "generated_at": int(time.time()),
            },
        )
