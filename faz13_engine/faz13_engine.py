# =====================================================
# FAZ-13 ANALYTIC CORE (DYNAMIC MEAN + REAL VARIANCE)
# File: faz13_engine.py
# =====================================================

from __future__ import annotations

import html
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from baseline.team_baseline_store import TeamBaselineStore
from league_profiles import get_league_profile

try:
    from providers.espn_adapter import ESPNAdapter  # type: ignore
except Exception:
    ESPNAdapter = None  # type: ignore


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

    sim_mean: float = 0.0
    sim_std: float = 0.0
    center_total: float = 0.0
    edge_distance: Optional[float] = None
    edge_flag: str = "NO_EDGE"
    watchlist: bool = True

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
        out.append("Analitik Referans")
        out.append(f"• Sim Mean: {self.sim_mean:.2f}")
        out.append(f"• Sim SD: {self.sim_std:.2f}")
        out.append(f"• Tempo: {esc(self.tempo_flag)}")

        if self.notes:
            out.append("")
            out.append("Notlar")
            for n in self.notes:
                out.append(f"• {esc(str(n))}")

        out.append("")
        out.append("Bu çıktı analiz/simülasyon amaçlıdır. Bahis tavsiyesi değildir.")
        return "\n".join(out)


# =====================================================
# FAZ-13 ENGINE
# =====================================================

class Faz13Engine:
    """
    ANALYTIC PREMATCH ENGINE

    - Dynamic mean (μ) from time-series
    - Real variance (σ) from data
    - League profile only scales, does not dominate
    """

    def __init__(
        self,
        baseline_store: TeamBaselineStore,
        min_games: int = 6,
    ) -> None:
        self.baseline_store = baseline_store
        self.min_games = int(min_games)
        self.session: Optional[aiohttp.ClientSession] = None

    async def aclose(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()

    # -------------------------------------------------
    # CORE HELPERS
    # -------------------------------------------------

    @staticmethod
    def _tempo_flag(pace: float) -> str:
        if pace >= 102:
            return "FAST"
        if pace <= 97:
            return "SLOW"
        return "NORMAL"

    @staticmethod
    def _quarter_band(mu: float, hw: int) -> Dict[str, Tuple[int, int]]:
        q_hw = max(2, int(hw / 2.8))
        return {
            "1Q": (int(mu * 0.24 - q_hw), int(mu * 0.24 + q_hw)),
            "2Q": (int(mu * 0.26 - q_hw), int(mu * 0.26 + q_hw)),
            "3Q": (int(mu * 0.25 - q_hw), int(mu * 0.25 + q_hw)),
            "4Q": (int(mu * 0.25 - q_hw), int(mu * 0.25 + q_hw)),
        }

    # -------------------------------------------------
    # ANALYTIC CORE
    # -------------------------------------------------

    def _compute_mu_sigma(
        self,
        league: str,
        home: str,
        away: str,
        profile,
    ) -> Tuple[float, float, Dict[str, Any]]:
        """
        μ = base + form + pace + matchup
        σ = real variance from recent totals
        """

        h_dyn = self.baseline_store.compute_dynamic_baseline(league, home, self.min_games)
        a_dyn = self.baseline_store.compute_dynamic_baseline(league, away, self.min_games)

        if not h_dyn or not a_dyn:
            raise RuntimeError("DYNAMIC_BASELINE_MISSING")

        # ---- base (anchor)
        mu_base = (
            (h_dyn["pts_for"] + a_dyn["pts_against"]) +
            (a_dyn["pts_for"] + h_dyn["pts_against"])
        ) / 2.0

        # ---- pace delta
        pace_mean = (h_dyn["pace"] + a_dyn["pace"]) / 2.0
        pace_delta = pace_mean - profile.pace_ref
        mu_pace = profile.beta_pace * pace_delta

        # ---- matchup delta
        matchup = (
            (h_dyn["pts_for"] - a_dyn["pts_against"]) +
            (a_dyn["pts_for"] - h_dyn["pts_against"])
        ) / 2.0
        mu_match = profile.beta_matchup * matchup

        mu = mu_base + mu_pace + mu_match

        # ---- variance (real)
        sigma = max(
            profile.volatility_floor,
            min(profile.volatility_ceil,
                (h_dyn["stdev_total"] + a_dyn["stdev_total"]) / 2.0),
        )

        meta = {
            "mu_base": round(mu_base, 2),
            "mu_pace": round(mu_pace, 2),
            "mu_matchup": round(mu_match, 2),
            "pace_mean": round(pace_mean, 2),
        }

        return float(mu), float(sigma), meta

    # -------------------------------------------------
    # PUBLIC API
    # -------------------------------------------------

    async def run_prematch(self, req: PrematchRequest) -> Faz13CoreOutput:
        profile = get_league_profile(req.league)
        ctx = FixtureContext(req.league, req.date_str, req.home, req.away)

        notes: List[str] = []

        try:
            mu, sigma, meta_mu = self._compute_mu_sigma(
                req.league, req.home, req.away, profile
            )
        except Exception:
            return Faz13CoreOutput(
                ctx=ctx,
                home_avg=TeamAverages(0, 0, 0, 0),
                away_avg=TeamAverages(0, 0, 0, 0),
                total_band=(0, 0),
                home_band=(0, 0),
                away_band=(0, 0),
                ou_direction="NO_PLAY",
                quarters={},
                blowout_risk="UNKNOWN",
                tempo_flag="UNKNOWN",
                notes=["NO_PLAY: DYNAMIC_BASELINE_MISSING"],
            )

        # ---- bands
        k = profile.k_sigma
        total_band = (int(mu - k * sigma), int(mu + k * sigma))

        home_band = (int(mu / 2 - k * sigma / 2), int(mu / 2 + k * sigma / 2))
        away_band = home_band

        tempo_flag = self._tempo_flag(meta_mu["pace_mean"])
        quarters = self._quarter_band(mu, int(k * sigma))

        notes.append("ANALYTIC MODE: ON")

        return Faz13CoreOutput(
            ctx=ctx,
            home_avg=TeamAverages(0, 0, meta_mu["pace_mean"], sigma),
            away_avg=TeamAverages(0, 0, meta_mu["pace_mean"], sigma),
            total_band=total_band,
            home_band=home_band,
            away_band=away_band,
            ou_direction="NO_EDGE",
            quarters=quarters,
            blowout_risk="LOW",
            tempo_flag=tempo_flag,
            sim_mean=round(mu, 2),
            sim_std=round(sigma, 2),
            center_total=round(mu, 1),
            notes=notes,
            meta=meta_mu,
        )
