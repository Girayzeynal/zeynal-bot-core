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
        out: List[str] = 

        out.append("FAZ-13 Ön Analiz")
        out.append(
            f"Maç: {esc(self.ctx.home)} vs {esc(self.ctx.away)} | "
            f"Lig: {esc(self.ctx.league)} | Tarih: {esc(self.ctx.date)}"
        )

        out.append("")
        out.append("Dar Bant (bilgi)")
        out.append(f"• Toplam: {self.total_band}–{self.total_band}") [1](https://stackoverflow.com/questions/74837978/syntaxerror-invalid-non-printable-character-u00a0-in-python)
        out.append(f"• Ev: {self.home_band}–{self.home_band} | Dep: {self.away_band}–{self.away_band}") [1](https://stackoverflow.com/questions/74837978/syntaxerror-invalid-non-printable-character-u00a0-in-python)

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
    FAZ-13 Prensiplerine göre maç analizi yapan motor.
    """
    def __init__(self):
        self._baseline_store = TeamBaselineStore()
        self._h2h_store = H2HStore() if H2HStore else None

    def analyze(self, request: PrematchRequest) -> Faz13CoreOutput:
        # 1. Fixture Context
        ctx = FixtureContext(
            league=request.league,
            date=request.date_str,
            home=request.home,
            away=request.away,
        )

        # 2. Team Averages
        home_avg = self._get_team_averages(request.home, request.league)
        away_avg = self._get_team_averages(request.away, request.league)

        # 3. Total Band
        total_band = self._calculate_total_band(home_avg, away_avg)
        home_band = self._calculate_home_band(home_avg, away_avg)
        away_band = self._calculate_away_band(home_avg, away_avg)

        # 4. Direction
        ou_direction = self._determine_ou_direction(home_avg, away_avg)

        # 5. Quarters
        quarters = self._get_quarter_predictions(home_avg, away_avg)

        # 6. Blowout Risk
        blowout_risk = self._determine_blowout_risk(home_avg, away_avg)

        # 7. Tempo Flag
        tempo_flag = self._determine_tempo_flag(home_avg, away_avg)

        # 8. Simulations
        sim_mean, sim_std = self._simulate_match(home_avg, away_avg)

        # 9. Center Total
        center_total = (sim_mean + 0.5) // 1 * 1  # round to nearest integer

        # 10. Notes
        notes = 
        if not home_avg or not away_avg:
            notes.append("⚠️ Takım verileri eksik.")

        # 11. Market (opsiyonel)
        market = {}

        # 12. Meta
        meta = {
            "season": int(request.date_str.split("-")),
            "season_str": f"{request.date_str.split('-')}–{int(request.date_str.split('-')) + 1}",
        }

        # 13. Force Mode (opsiyonel)
        force = None
        if self._h2h_store:
            force = self._get_force_mode_result(request)

        # 14. Output
        return Faz13CoreOutput(
            ctx=ctx,
            home_avg=home_avg,
            away_avg=away_avg,
            total_band=total_band,
            home_band=home_band,
            away_band=away_band,
            ou_direction=ou_direction,
            quarters=quarters,
            blowout_risk=blowout_risk,
            tempo_flag=tempo_flag,
            sim_mean=sim_mean,
            sim_std=sim_std,
            center_total=center_total,
            notes=notes,
            market=market,
            meta=meta,
            force=force,
        )

    def _get_team_averages(self, team: str, league: str) -> TeamAverages:
        # Simülasyon: gerçek veriler yerine örnek veri döner
        profile = get_league_profile(league)
        if not profile:
            return TeamAverages(0.0, 0.0, 0.0, 0.0)

        # Örnek veri
        return TeamAverages(
            points_for=110.0,
            points_against=105.0,
            pace_hint=100.0,
            stdev_hint=5.0,
        )

    def _calculate_total_band(self, home: TeamAverages, away: TeamAverages) -> Tuple[int, int]:
        mean = (home.points_for + away.points_against) / 2
        std = (home.stdev_hint + away.stdev_hint) / 2
        return int(mean - 2 * std), int(mean + 2 * std)

    def _calculate_home_band(self, home: TeamAverages, away: TeamAverages) -> Tuple[int, int]:
        mean = (home.points_for + away.points_against) / 2
        std = (home.stdev_hint + away.stdev_hint) / 2
        return int(mean - 1.5 * std), int(mean + 1.5 * std)

    def _calculate_away_band(self, home: TeamAverages, away: TeamAverages) -> Tuple[int, int]:
        mean = (away.points_for + home.points_against) / 2
        std = (away.stdev_hint + home.stdev_hint) / 2
        return int(mean - 1.5 * std), int(mean + 1.5 * std)

    def _determine_ou_direction(self, home: TeamAverages, away: TeamAverages) -> str:
        total_mean = (home.points_for + away.points_against) / 2
        if total_mean > 210:
            return "OVER"
        elif total_mean < 190:
            return "UNDER"
        else:
            return "NEUTRAL"

    def _get_quarter_predictions(self, home: TeamAverages, away: TeamAverages) -> Dict[str, Tuple[int, int]]:
        # Simülasyon: örnek veri
        return {
            "1Q": (25, 20),
            "2Q": (30, 25),
            "3Q": (28, 27),
            "4Q": (27, 28),
        }

    def _determine_blowout_risk(self, home: TeamAverages, away: TeamAverages) -> str:
        diff = abs(home.points_for - away.points_against)
        if diff > 20:
            return "HIGH"
        elif diff > 10:
            return "MEDIUM"
        else:
            return "LOW"

    def _determine_tempo_flag(self, home: TeamAverages, away: TeamAverages) -> str:
        pace = (home.pace_hint + away.pace_hint) / 2
        if pace > 105:
            return "FAST"
        elif pace < 95:
            return "SLOW"
        else:
            return "NORMAL"

    def _simulate_match(self, home: TeamAverages, away: TeamAverages) -> Tuple[float, float]:
        # Simülasyon: örnek veri
        mean = (home.points_for + away.points_against) / 2
        std = (home.stdev_hint + away.stdev_hint) / 2
        return mean, std

    def _get_force_mode_result(self, request: PrematchRequest) -> Dict[str, Any]:
        # Simülasyon: örnek veri
        return {
            "total": 210,
            "direction": "OVER",
            "teams": {"home": 110, "away": 100},
            "halves": {"1H": 55, "2H": 55},
            "quarters": {"1Q": 25, "2Q": 30, "3Q": 28, "4Q": 27},
            "handicap": "+3.5",
            "confidence": 75,
            "risk": "MEDIUM",
        }
 
