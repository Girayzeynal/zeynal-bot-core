# =====================================================
# FAZ-13 ANALYTIC CORE + FORCE MODE (REAL DATA ONLY)
# File: faz13_engine.py
# =====================================================

from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from baseline.team_baseline_store import TeamBaselineStore
from league_profiles import get_league_profile

# Optional H2H (varsa kullan, yoksa sessiz geç)
try:
    from baseline.h2h_store import H2HStore  # type: ignore
except Exception:
    H2HStore = None  # type: ignore


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

    notes: List[str] = field(default_factory=list)
    market: Dict[str, Any] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)

    # FORCE MODE RESULT
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
        out.append("Dar Bant (bilgi)")
        out.append(f"• Toplam: {self.total_band[0]}–{self.total_band[1]}")
        out.append(f"• Ev: {self.home_band[0]}–{self.home_band[1]} | Dep: {self.away_band[0]}–{self.away_band[1]}")

        out.append("")
        out.append("Analitik Referans")
        out.append(f"• Beklenen Toplam (μ): {self.sim_mean:.2f}")
        out.append(f"• Belirsizlik (σ): {self.sim_std:.2f}")
        out.append(f"• Tempo: {esc(self.tempo_flag)}")

        # ============================
        # FORCE MODE OUTPUT (tek rakam)
        # ============================
        if isinstance(self.force, dict):
            f = dict(self.force)  # local copy

            # Market total render anında gelir (main.py meta["market_total"] inject eder)
            market_total = None
            try:
                mt = self.meta.get("market_total")
                if mt is not None:
                    market_total = float(mt)
            except Exception:
                market_total = None

            total = int(f.get("total", 0))

            # Direction: market varsa kesin, yoksa FORCE
            if market_total is not None and total > 0:
                direction = "OVER" if total >= market_total else "UNDER"
            else:
                direction = "OVER" if str(f.get("direction", "OVER")).upper() != "UNDER" else "UNDER"

            teams = f.get("teams") or {}
            halves = f.get("halves") or {}
            quarters = f.get("quarters") or {}

            out.append("")
            out.append("🔥 FORCE MODE (TEK RAKAM – SON 5 MAÇ)")
            out.append(f"• Referans Market: {market_total:.1f}" if market_total is not None else "• Referans Market: YOK")
            out.append(f"• Toplam: {total} | Yön: {direction}")

            out.append(
                f"• Takım Skorları: {esc(self.ctx.home)} {int(teams.get('home', 0))} – "
                f"{int(teams.get('away', 0))} {esc(self.ctx.away)}"
            )
            out.append(f"• İlk Yarı: {int(halves.get('1H', 0))} | İkinci Yarı: {int(halves.get('2H', 0))}")
            out.append(
                f"• Periyotlar: 1Q {int(quarters.get('1Q', 0))} | 2Q {int(quarters.get('2Q', 0))} | "
                f"3Q {int(quarters.get('3Q', 0))} | 4Q {int(quarters.get('4Q', 0))}"
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
    FAZ-13 PREMATCH ENGINE (TEAM_LAST_5)

    - ONLY TEAM_LAST_5 (real data)
    - Optional H2H weighting if H2HStore exists (max %25)
    - FORCE MODE: single-number outputs (Total, team scores, 1H, quarters, handicap, O/U)
    """

    def __init__(
        self,
        baseline_store: TeamBaselineStore,
        min_games: int = 6,
        h2h_store: Optional[Any] = None,
    ) -> None:
        self.baseline_store = baseline_store
        self.min_games = int(min_games)

        # Optional H2H store (if file exists)
        if h2h_store is not None:
            self.h2h_store = h2h_store
        elif H2HStore is not None:
            self.h2h_store = H2HStore()  # type: ignore
        else:
            self.h2h_store = None

    # -------------------------
    # HELPERS
    # -------------------------

    @staticmethod
    def _tempo_flag(pace: float) -> str:
        if pace >= 102:
            return "FAST"
        if pace <= 97:
            return "SLOW"
        return "NORMAL"

    @staticmethod
    def _quarters_from_total(total: int) -> Dict[str, int]:
        # NBA ağırlıkları (toplamı 1'e yakın) – deterministik
        q1 = int(round(total * 0.24))
        q2 = int(round(total * 0.26))
        q3 = int(round(total * 0.25))
        q4 = int(total - (q1 + q2 + q3))
        return {"1Q": q1, "2Q": q2, "3Q": q3, "4Q": q4}

    @staticmethod
    def _halves_from_total(total: int) -> Dict[str, int]:
        h1 = int(round(total * 0.495))
        h2 = int(total - h1)
        return {"1H": h1, "2H": h2}

    @staticmethod
    def _team_split(total: int, h_pf: float, a_pf: float) -> Tuple[int, int]:
        denom = float(h_pf + a_pf)
        if denom <= 0:
            home = int(round(total / 2))
            return home, int(total - home)
        share = float(h_pf) / denom
        home = int(round(total * share))
        away = int(total - home)
        return home, away

    @staticmethod
    def _confidence_from_sigma(sigma: float, extra_edge: float = 0.0) -> Tuple[int, str]:
        # Basit ve stabil: sigma yükseldikçe güven düşer. (45..80)
        base = 78.0 - float(sigma) * 2.2
        base += float(extra_edge) * 0.8  # varsa küçük destek
        conf = int(max(45, min(80, round(base))))
        risk = "LOW" if conf > 65 else "MID" if conf > 55 else "HIGH"
        return conf, risk

    # -------------------------
    # CORE
    # -------------------------

    def _compute_mu_sigma_team_last5(self, league: str, home: str, away: str, profile) -> Tuple[float, float, Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        h_dyn = self.baseline_store.compute_dynamic_baseline(league, home, 5)
        a_dyn = self.baseline_store.compute_dynamic_baseline(league, away, 5)

        if not h_dyn or not a_dyn:
            raise RuntimeError("TEAM_LAST_5_REQUIRED")

        # Base expectation (matchup)
        mu_base = (
            (h_dyn["pts_for"] + a_dyn["pts_against"]) +
            (a_dyn["pts_for"] + h_dyn["pts_against"])
        ) / 2.0

        # Pace adjustment (profile)
        pace_mean = (h_dyn["pace"] + a_dyn["pace"]) / 2.0
        pace_delta = pace_mean - float(getattr(profile, "pace_ref", 100.0))
        beta_pace = float(getattr(profile, "beta_pace", 0.0))
        mu_pace = beta_pace * pace_delta

        # Matchup adjustment (profile)
        matchup = (
            (h_dyn["pts_for"] - a_dyn["pts_against"]) +
            (a_dyn["pts_for"] - h_dyn["pts_against"])
        ) / 2.0
        beta_match = float(getattr(profile, "beta_matchup", 0.0))
        mu_match = beta_match * matchup

        mu_team = float(mu_base + mu_pace + mu_match)

        # Sigma from real totals variability (bounded by profile)
        sig_raw = (h_dyn["stdev_total"] + a_dyn["stdev_total"]) / 2.0
        vol_floor = float(getattr(profile, "volatility_floor", 7.0))
        vol_ceil = float(getattr(profile, "volatility_ceil", 13.0))
        sigma = max(vol_floor, min(vol_ceil, float(sig_raw)))

        meta = {
            "baseline_source": "TEAM_LAST_5",
            "mu_base": round(mu_base, 2),
            "mu_pace": round(mu_pace, 2),
            "mu_matchup": round(mu_match, 2),
            "pace_mean": round(pace_mean, 2),
        }

        return mu_team, sigma, meta, h_dyn, a_dyn

    def _apply_h2h_weight(self, league: str, home: str, away: str, mu_team: float, sigma: float, notes: List[str]) -> Tuple[float, float, Dict[str, Any]]:
        if not self.h2h_store:
            return mu_team, sigma, {"h2h_used": False}

        try:
            h2h_sum = self.h2h_store.compute_summary(league, home, away, 5)  # type: ignore
        except Exception:
            h2h_sum = None

        if not h2h_sum:
            return mu_team, sigma, {"h2h_used": False}

        # Weight: max 0.25
        w = min(0.25, float(h2h_sum.n_games) / 20.0)
        mu_h2h = float(h2h_sum.avg_total)

        mu_final = (1.0 - w) * float(mu_team) + w * mu_h2h

        # sigma: very light blend (optional, bounded)
        if float(h2h_sum.stdev_total) > 0:
            sigma_final = (1.0 - w) * float(sigma) + w * float(h2h_sum.stdev_total)
        else:
            sigma_final = float(sigma)

        notes.append(f"H2H: n={h2h_sum.n_games} | w={w:.2f} | avg_total={mu_h2h:.1f}")
        return float(mu_final), float(sigma_final), {"h2h_used": True, "h2h_n": h2h_sum.n_games, "h2h_w": round(w, 3), "h2h_avg_total": round(mu_h2h, 2)}

    # -------------------------
    # PUBLIC API
    # -------------------------

    async def run_prematch(self, req: PrematchRequest) -> Faz13CoreOutput:
        profile = get_league_profile(req.league)
        ctx = FixtureContext(req.league, req.date_str, req.home, req.away)

        notes: List[str] = []

        try:
            mu_team, sigma, meta_mu, h_dyn, a_dyn = self._compute_mu_sigma_team_last5(req.league, req.home, req.away, profile)
        except Exception:
            # Gerçek veri yoksa: sus (uydurma yok)
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
                market={},
                force=None,
            )

        # Optional H2H adjustment
        mu_final, sigma_final, meta_h2h = self._apply_h2h_weight(req.league, req.home, req.away, mu_team, sigma, notes)

        # Bands (bilgi amaçlı)
        k = float(getattr(profile, "k_sigma", 1.0))
        total_band = (int(mu_final - k * sigma_final), int(mu_final + k * sigma_final))

        # Team bands (bilgi amaçlı)
        home_band = (int(mu_final / 2 - k * sigma_final / 2), int(mu_final / 2 + k * sigma_final / 2))
        away_band = home_band

        # Tempo flag
        tempo_flag = self._tempo_flag(float(meta_mu.get("pace_mean", 100.0)))

        # FORCE: tek rakam toplam
        total = int(round(mu_final))
        q = self._quarters_from_total(total)
        halves = self._halves_from_total(total)
        home_score, away_score = self._team_split(total, float(h_dyn["pts_for"]), float(a_dyn["pts_for"]))

        # Handicap winner (default -5.5)
        diff = home_score - away_score
        handicap = "HOME_-5.5" if diff > 5.5 else "AWAY_+5.5"

        conf, risk = self._confidence_from_sigma(float(sigma_final))

        force = {
            "total": total,
            "direction": "FORCE",  # market varsa render’da OVER/UNDER
            "teams": {"home": home_score, "away": away_score},
            "halves": halves,
            "quarters": q,
            "handicap": handicap,
            "confidence": conf,
            "risk": risk,
            "source": "TEAM_LAST_5",
        }

        notes.insert(0, "ANALYTIC MODE: TEAM_LAST_5 (H2H opsiyonel)")
        if meta_h2h.get("h2h_used"):
            notes.insert(1, "H2H ağırlık aktif (max %25).")

        return Faz13CoreOutput(
            ctx=ctx,
            home_avg=TeamAverages(float(h_dyn["pts_for"]), float(h_dyn["pts_against"]), float(meta_mu.get("pace_mean", 100.0)), float(sigma_final)),
            away_avg=TeamAverages(float(a_dyn["pts_for"]), float(a_dyn["pts_against"]), float(meta_mu.get("pace_mean", 100.0)), float(sigma_final)),
            total_band=total_band,
            home_band=home_band,
            away_band=away_band,
            ou_direction="FORCE",
            quarters={},  # bant yerine tek rakam force veriyoruz; istersen burada bandlı quarters da eklenir
            blowout_risk="LOW",
            tempo_flag=tempo_flag,
            sim_mean=round(mu_final, 2),
            sim_std=round(sigma_final, 2),
            center_total=round(mu_final, 1),
            notes=notes,
            market={},
            meta={**meta_mu, **meta_h2h, "data_ready": True},
            force=force,
        )
