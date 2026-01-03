# =====================================================
# FAZ-13 ANALYTIC CORE + FORCE MODE (REAL DATA ONLY)
# File: faz13_engine.py
# =====================================================

from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from baseline.team_baseline_store import TeamBaselineStore
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

    # 🔥 FORCE MODE RESULT
    force: Optional[Dict[str, Any]] = None

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

        out.append("")
        out.append("Analitik Referans")
        out.append(f"• Sim Mean: {self.sim_mean:.2f}")
        out.append(f"• Sim SD: {self.sim_std:.2f}")
        out.append(f"• Tempo: {esc(self.tempo_flag)}")

        # ============================
        # 🔥 FORCE MODE OUTPUT
        # ============================
        if isinstance(self.force, dict):
            f = dict(self.force)  # local copy (no mutation)

            # Market referansı render anında gelir (main.py meta["market_total"] inject ediyor)
            market_total = None
            try:
                mt = self.meta.get("market_total")
                if mt is not None:
                    market_total = float(mt)
            except Exception:
                market_total = None

            total = int(f.get("total", 0))
            direction = f.get("direction", "OVER")

            # Market varsa yönü buna göre güncelle (sadece local)
            if market_total is not None and total > 0:
                direction = "OVER" if total >= market_total else "UNDER"

            out.append("")
            out.append("🔥 FORCE MODE (GERÇEK VERİ – SON 5 MAÇ)")
            if market_total is not None:
                out.append(f"• Referans Market: {market_total:.1f}")
            else:
                out.append("• Referans Market: YOK")

            out.append(f"• Toplam: {total} ({direction})")

            teams = f.get("teams") or {}
            halves = f.get("halves") or {}
            quarters = f.get("quarters") or {}

            out.append(
                f"• Skor: {esc(self.ctx.home)} {int(teams.get('home', 0))} – "
                f"{int(teams.get('away', 0))} {esc(self.ctx.away)}"
            )
            out.append(
                f"• İlk Yarı: {int(halves.get('1H', 0))} | İkinci Yarı: {int(halves.get('2H', 0))}"
            )
            out.append(
                f"• Periyot: {int(quarters.get('1Q', 0))}–{int(quarters.get('2Q', 0))}–"
                f"{int(quarters.get('3Q', 0))}–{int(quarters.get('4Q', 0))}"
            )
            out.append(f"• Handikap: {esc(str(f.get('handicap', 'N/A')))}")
            out.append(f"• Güven: %{int(f.get('confidence', 0))} | Risk: {esc(str(f.get('risk', 'N/A')))}")

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
    ANALYTIC PREMATCH ENGINE + FORCE MODE

    FORCE MODE RULES:
    - ONLY last 5 games real data (TEAM_LAST_5)
    - NO league averages
    - NO fake fallback (no 220, no uydurma)
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
    # HELPERS
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
    # ANALYTIC CORE (LAST 5 ONLY)
    # -------------------------------------------------

    def _compute_mu_sigma_last5(
        self,
        league: str,
        home: str,
        away: str,
        profile,
        h_dyn: Dict[str, Any],
        a_dyn: Dict[str, Any],
    ) -> Tuple[float, float, Dict[str, Any]]:

        mu_base = (
            (h_dyn["pts_for"] + a_dyn["pts_against"]) +
            (a_dyn["pts_for"] + h_dyn["pts_against"])
        ) / 2.0

        pace_mean = (h_dyn["pace"] + a_dyn["pace"]) / 2.0
        pace_delta = pace_mean - profile.pace_ref
        mu_pace = profile.beta_pace * pace_delta

        matchup = (
            (h_dyn["pts_for"] - a_dyn["pts_against"]) +
            (a_dyn["pts_for"] - h_dyn["pts_against"])
        ) / 2.0
        mu_match = profile.beta_matchup * matchup

        mu = mu_base + mu_pace + mu_match

        sigma = max(
            profile.volatility_floor,
            min(profile.volatility_ceil, (h_dyn["stdev_total"] + a_dyn["stdev_total"]) / 2.0),
        )

        meta = {
            "mu_base": round(mu_base, 2),
            "mu_pace": round(mu_pace, 2),
            "mu_matchup": round(mu_match, 2),
            "pace_mean": round(pace_mean, 2),
            "baseline_source": "TEAM_LAST_5",
        }

        return float(mu), float(sigma), meta

    # -------------------------------------------------
    # FORCE MODE (LAST 5 ONLY)
    # -------------------------------------------------

    @staticmethod
    def _force_mode(mu: float, sigma: float, h_dyn: Dict[str, Any], a_dyn: Dict[str, Any]) -> Dict[str, Any]:
        total = int(round(mu))

        denom = float(h_dyn["pts_for"] + a_dyn["pts_for"])
        home_share = float(h_dyn["pts_for"]) / denom if denom > 0 else 0.5

        home_score = int(round(total * home_share))
        away_score = int(total - home_score)

        first_half = int(round(total * 0.495))
        second_half = int(total - first_half)

        q1 = int(round(total * 0.24))
        q2 = int(round(total * 0.255))
        q3 = int(round(total * 0.25))
        q4 = int(total - (q1 + q2 + q3))

        diff = home_score - away_score
        handicap = "HOME_-5.5" if diff > 5.5 else "AWAY_+5.5"

        # Confidence forced but honest (45..80). Uses only sigma; market handled at render time.
        conf = int(round(45 + (abs(mu - float(total)) / max(1.0, float(sigma))) * 18))
        conf = max(45, min(80, conf))
        risk = "LOW" if conf > 65 else "MID" if conf > 55 else "HIGH"

        return {
            "total": total,
            "direction": "FORCE",  # placeholder; render_html decides OVER/UNDER if market exists
            "teams": {"home": home_score, "away": away_score},
            "halves": {"1H": first_half, "2H": second_half},
            "quarters": {"1Q": q1, "2Q": q2, "3Q": q3, "4Q": q4},
            "handicap": handicap,
            "confidence": conf,
            "risk": risk,
            "source": "TEAM_LAST_5",
        }

    # -------------------------------------------------
    # PUBLIC API
    # -------------------------------------------------

    async def run_prematch(self, req: PrematchRequest) -> Faz13CoreOutput:
        profile = get_league_profile(req.league)
        ctx = FixtureContext(req.league, req.date_str, req.home, req.away)

        notes: List[str] = []

        # ✅ Only last 5 games baselines (real data)
        h_dyn = self.baseline_store.compute_dynamic_baseline(req.league, req.home, 5)
        a_dyn = self.baseline_store.compute_dynamic_baseline(req.league, req.away, 5)

        if not h_dyn or not a_dyn:
            # no fake fallback, no league avg
            return Faz13CoreOutput(
                ctx=ctx,
                home_avg=TeamAverages(0, 0, 0, 0),
                away_avg=TeamAverages(0, 0, 0, 0),
                total_band=(0, 0),
                home_band=(0, 0),
                away_band=(0, 0),
                ou_direction="DATA_NOT_READY",
                quarters={},
                blowout_risk="UNKNOWN",
                tempo_flag="UNKNOWN",
                notes=["DATA_NOT_READY: TEAM_LAST_5_REQUIRED"],
                meta={"baseline_source": "TEAM_LAST_5", "data_ready": False},
                force=None,
            )

        mu, sigma, meta_mu = self._compute_mu_sigma_last5(
            req.league, req.home, req.away, profile, h_dyn, a_dyn
        )

        k = float(profile.k_sigma)
        total_band = (int(mu - k * sigma), int(mu + k * sigma))

        home_band = (int(mu / 2 - k * sigma / 2), int(mu / 2 + k * sigma / 2))
        away_band = home_band

        tempo_flag = self._tempo_flag(float(meta_mu["pace_mean"]))
        quarters = self._quarter_band(mu, int(k * sigma))

        # ✅ FORCE always computed if data exists
        force = self._force_mode(mu, sigma, h_dyn, a_dyn)

        notes.append("ANALYTIC MODE: ON")
        notes.append("FORCE MODE: ON (TEAM_LAST_5)")

        return Faz13CoreOutput(
            ctx=ctx,
            home_avg=TeamAverages(float(h_dyn["pts_for"]), float(h_dyn["pts_against"]), float(meta_mu["pace_mean"]), float(sigma)),
            away_avg=TeamAverages(float(a_dyn["pts_for"]), float(a_dyn["pts_against"]), float(meta_mu["pace_mean"]), float(sigma)),
            total_band=total_band,
            home_band=home_band,
            away_band=away_band,
            ou_direction="FORCE",
            quarters=quarters,
            blowout_risk="LOW",
            tempo_flag=tempo_flag,
            sim_mean=round(mu, 2),
            sim_std=round(sigma, 2),
            center_total=round(mu, 1),
            notes=notes,
            meta={**meta_mu, "data_ready": True},
            force=force,
        ) 
