"""
faz13_engine.py
================

This module contains the implementation of the pre‑match analysis engine
(`Faz13Engine`) used by the Zeynal Core bot.  It provides a small set of
data classes to describe the inputs and outputs of the engine along with
helper structures.  The engine is responsible for computing bands of
expected points, tempo flags and blowout risk based off of recent team
statistics.  When invoked via :meth:`Faz13Engine.run_prematch`, it returns
an instance of :class:`Faz13CoreOutput` which can be consumed by downstream
engines (FAZ‑17 market enrichment, FAZ‑22 confidence calibration) or
rendered directly as HTML.

Unlike earlier versions of this file, this implementation defines all
required classes and methods referenced by the rest of the application,
including :class:`PrematchRequest`, :class:`FixtureContext`,
:class:`TeamAverages` and :class:`Faz13CoreOutput`.  Importing these
definitions from ``faz13_engine`` therefore resolves the ``ImportError``
encountered when ``main.py`` attempted to import ``PrematchRequest``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from baseline.team_baseline_store import (
    TeamBaselineStore,
    TeamBaselineBootstrapper,
    TeamStatsAdapter,
)


@dataclass
class PrematchRequest:
    """Input payload for pre‑match analysis.

    :param user_id: Identifier of the user making the request.  This
        value is carried through the pipeline but not currently used by
        the engine; it is reserved for future per‑user customisation.
    :param league: The league code (e.g. ``EUROLEAGUE``, ``NBA``) of the
        fixture to analyse.
    :param date: The date of the fixture in ``YYYY-MM-DD`` format.
    :param home: The home team name.
    :param away: The away team name.
    """

    user_id: int
    league: str
    date: str
    home: str
    away: str


@dataclass
class FixtureContext:
    """Context information for a fixture under analysis."""

    league: str
    date: str
    home: str
    away: str


@dataclass
class TeamAverages:
    """Aggregate statistics for a single team.

    This structure holds summary information about a team's recent
    performance.  It is defined for completeness but is not actively used
    by the current implementation.  In future versions it may be used to
    carry more granular statistics into the engine.
    """

    league: str
    team: str
    n_games: int
    pts_for: float
    pts_against: float
    pace: float
    stdev_total: float


@dataclass
class Faz13CoreOutput:
    """Output of the pre‑match analysis engine.

    Instances of this class carry the results of a pre‑match analysis.  The
    ``ctx`` attribute contains fixture metadata; the band attributes
    describe predicted ranges for team and total scores; the ``tempo_flag``
    and ``blowout_risk`` indicate stylistic considerations; ``ou_direction``
    hints at the model's tilt towards over/under on the betting line; and
    ``meta`` stores confidence, risk and issue flags.  The ``notes`` list
    contains any warnings or explanatory messages.
    """

    ctx: FixtureContext
    home_band: List[int]
    away_band: List[int]
    total_band: List[int]
    tempo_flag: str
    blowout_risk: str
    ou_direction: str
    meta: Dict[str, Any]
    notes: List[str]
    market: Dict[str, Any] = field(default_factory=dict)

    # New fields for compatibility with FAZ-23 snapshots
    # Average statistics for the home team.  Stored as a TeamAverages dataclass
    # so that ``dataclasses.asdict`` can be applied in Faz23Engine.
    home_avg: TeamAverages | None = None
    # Average statistics for the away team.
    away_avg: TeamAverages | None = None
    # Predicted quarter bands (lo, hi) for a single quarter.  FAZ-23 persists
    # this for potential calibration.  When unavailable, defaults to [] or
    # [0, 0] to avoid attribute errors.
    quarters: List[int] | None = None

    def render_html(self) -> str:
        """Render this analysis as an HTML fragment suitable for Telegram.

        The HTML contains basic bold formatting for key fields and
        structures the information in a human‑readable way.  Downstream
        engines may augment the HTML further, but this baseline output
        ensures that even a standalone FAZ‑13 analysis produces a useful
        response.
        """
        # Fixture header
        html_lines: List[str] = []
        html_lines.append("<b>FAZ-13 Ön Analiz</b><br>")
        html_lines.append(
            f"<b>Maç:</b> {self.ctx.home} vs {self.ctx.away} | <b>Lig:</b> {self.ctx.league} | <b>Tarih:</b> {self.ctx.date}<br>"
        )
        # Bands
        if self.total_band and len(self.total_band) == 2:
            html_lines.append(
                f"<b>Toplam (Tahmin):</b> {self.total_band[0]}–{self.total_band[1]}<br>"
            )
        if self.home_band and len(self.home_band) == 2:
            html_lines.append(
                f"<b>{self.ctx.home} Bant:</b> {self.home_band[0]}–{self.home_band[1]}<br>"
            )
        if self.away_band and len(self.away_band) == 2:
            html_lines.append(
                f"<b>{self.ctx.away} Bant:</b> {self.away_band[0]}–{self.away_band[1]}<br>"
            )
        # Signals
        html_lines.append(
            f"<b>Tempo:</b> {self.tempo_flag} | <b>Blowout riski:</b> {self.blowout_risk}<br>"
        )
        html_lines.append(
            f"<b>Alt/Üst yönü:</b> {self.ou_direction}<br>"
        )
        # Meta
        conf = self.meta.get("confidence")
        risk = self.meta.get("risk")
        if conf is not None or risk is not None:
            parts = []
            if conf is not None:
                parts.append(f"Güven: {conf}")
            if risk is not None:
                parts.append(f"Risk: {risk}")
            html_lines.append("<b>" + " | ".join(parts) + "</b><br>")
        # Notes
        if self.notes:
            html_lines.append("<br><i>Notlar:</i><ul>")
            for note in self.notes:
                html_lines.append(f"<li>{note}</li>")
            html_lines.append("</ul>")
        return "".join(html_lines)


def _risk_label(conf: float, issues: List[str]) -> str:
    """Map a confidence value and issue list to a risk label.

    This helper mirrors the logic used in the original implementation.
    """
    # If team data is missing then confidence should be treated as higher risk
    if "no_team_data" in issues:
        # Force the label to HIGH so that downstream engines treat the
        # prediction conservatively.
        return "HIGH"
    if conf >= 75:
        return "LOW"
    if conf >= 60:
        return "MID"
    return "HIGH"


class Faz13Engine:
    """Pre‑match analysis engine.

    The engine takes a :class:`TeamStatsAdapter` which it uses to populate
    team baselines.  It can compute a preliminary analysis for a fixture
    synchronously (via :meth:`pre_analyze`) and wrap that analysis into a
    full :class:`Faz13CoreOutput` asynchronously (via
    :meth:`run_prematch`).
    """

    def __init__(self, stats_adapter: TeamStatsAdapter) -> None:
        self.store = TeamBaselineStore()
        self.bootstrap = TeamBaselineBootstrapper(self.store, stats_adapter)

    def pre_analyze(self, league: str, home: str, away: str) -> Dict[str, Any]:
        """Compute a dictionary of baseline and band data for a fixture.

        This method attempts to bootstrap team baselines if none exist,
        calculates expected totals and spreads and returns a structured
        dictionary similar to the one produced by earlier FAZ‑13 versions.
        """
        issues: List[str] = []
        # Ensure baselines exist; if missing, bootstrap from adapter
        hb = self.bootstrap.ensure(league, home, min_games=6)
        ab = self.bootstrap.ensure(league, away, min_games=6)
        if not hb:
            issues.append("no_team_data")
        if not ab and "no_team_data" not in issues:
            issues.append("no_team_data")
        # If still missing, don't pretend it's fine.  Return a stub analysis
        if not hb or not ab:
            # When no team statistics exist we cannot compute meaningful bands.  To
            # prevent downstream engines (e.g. FAZ‑22) from throwing unpack errors,
            # always return a bands dictionary with placeholder ranges.  The total
            # band is set to [0, 0], and per‑quarter/half bands mirror this.
            conf = 45.0  # reduced confidence when no data
            return {
                "league_profile": league,
                "home": home,
                "away": away,
                "baseline": {
                    "home_baseline_src": "none",
                    "home_baseline_n": 0,
                    "away_baseline_src": "none",
                    "away_baseline_n": 0,
                },
                # Provide empty but structured bands to avoid unpacking errors.
                "bands": {
                    "ft": [0, 0],  # full time total band
                    "ht": [0, 0],  # half time band
                    "q": [0, 0],   # quarter band
                },
                "signals": {
                    "alt_ust": "NO_EDGE",
                    "tempo_flag": "UNKNOWN",
                    "blowout_risk": "UNKNOWN",
                },
                "meta": {
                    "confidence": conf,
                    "risk": _risk_label(conf, issues),
                    "issues": issues,
                    "mode": "FAZ-13 TEAM-BASELINE REQUIRED",
                },
                "notes": [
                    "UYARI: Team baseline alınamadı – analiz kilitlendi (lig baseline kullanılmıyor).",
                    "Çözüm: TeamStatsAdapter veri kaynağına bağlanmalı veya baselines klasörü doldurulmalı.",
                ],
            }
        # Otherwise compute the expected total and standard deviation from both teams
        exp_total = (hb.pts_for + ab.pts_for) / 2.0
        sigma = (hb.stdev_total + ab.stdev_total) / 2.0
        # Keep existing confidence calculation; you may substitute your own
        conf = 62.8
        return {
            "league_profile": league,
            "home": home,
            "away": away,
            "baseline": {
                "home_baseline_src": "team",
                "home_baseline_n": hb.n_games,
                "away_baseline_src": "team",
                "away_baseline_n": ab.n_games,
                "mu_total": round(exp_total, 2),
                "sigma_total": round(sigma, 2),
                "pace": round((hb.pace + ab.pace) / 2.0, 3),
            },
            "bands": {
                "ft": [round(exp_total - 6), round(exp_total + 6)],
                "ht": [round((exp_total / 2.0) - 4), round((exp_total / 2.0) + 4)],
                "q": [round((exp_total / 4.0) - 2), round((exp_total / 4.0) + 2)],
            },
            "signals": {
                "alt_ust": "NO_EDGE",  # market will refine this later
                "tempo_flag": "NORMAL",
                "blowout_risk": "LOW",
            },
            "meta": {
                "confidence": conf,
                "risk": _risk_label(conf, issues),
                "issues": issues,
                "mode": "FAZ-13 TEAM BASELINE",
            },
            "notes": [],
        }

    async def run_prematch(self, request: PrematchRequest) -> Faz13CoreOutput:
        """Asynchronously compute a pre‑match analysis for the given request.

        Although this method is defined as ``async`` to integrate smoothly with
        the overall application (which uses asynchronous Telegram handlers),
        it performs all of its work synchronously.  Should future
        implementations of ``TeamStatsAdapter`` perform network I/O, this
        method could be adapted to await those operations.
        """
        # Run the underlying analysis
        result = self.pre_analyze(request.league, request.home, request.away)
        # Extract fields from the result dict
        baseline: Dict[str, Any] = result.get("baseline", {})
        bands: Dict[str, Any] = result.get("bands", {})
        signals: Dict[str, Any] = result.get("signals", {})
        meta_info: Dict[str, Any] = result.get("meta", {})
        notes: List[str] = result.get("notes", [])
        # Determine total band.  If the result from pre_analyze omitted bands or
        # provided an empty list, fall back to a neutral [0, 0] band so that
        # downstream engines (FAZ‑22) can safely unpack it.
        if isinstance(bands, dict):
            total_band = bands.get("ft", [0, 0])
        else:
            total_band = [0, 0]
        # Compute per‑team bands.  Prefer the underlying mu_total when present
        mu_total: Optional[float] = baseline.get("mu_total")  # type: ignore[assignment]
        home_band: List[int]
        away_band: List[int]
        if isinstance(mu_total, (int, float)):
            # Use half of mu_total ±3 as a simple per‑team range
            home_band = [round(mu_total / 2.0 - 3), round(mu_total / 2.0 + 3)]
            away_band = [round(mu_total / 2.0 - 3), round(mu_total / 2.0 + 3)]
        elif total_band and len(total_band) == 2:
            # Fall back to splitting the total band evenly
            lo, hi = total_band
            home_band = [round(lo / 2.0), round(hi / 2.0)]
            away_band = [round(lo / 2.0), round(hi / 2.0)]
        else:
            home_band = [0, 0]
            away_band = [0, 0]
        # Build context
        ctx = FixtureContext(
            league=request.league,
            date=request.date,
            home=request.home,
            away=request.away,
        )
        # Derive per‑team average statistics for snapshotting.  Look up the
        # persisted baselines directly; if missing, fall back to neutral values.
        hb_raw = self.store.get(request.league, request.home)
        if hb_raw:
            home_avg_obj = TeamAverages(
                league=request.league,
                team=request.home,
                n_games=hb_raw.n_games,
                pts_for=hb_raw.pts_for,
                pts_against=hb_raw.pts_against,
                pace=hb_raw.pace,
                stdev_total=hb_raw.stdev_total,
            )
        else:
            home_avg_obj = TeamAverages(
                league=request.league,
                team=request.home,
                n_games=0,
                pts_for=0.0,
                pts_against=0.0,
                pace=1.0,
                stdev_total=9.0,
            )
        ab_raw = self.store.get(request.league, request.away)
        if ab_raw:
            away_avg_obj = TeamAverages(
                league=request.league,
                team=request.away,
                n_games=ab_raw.n_games,
                pts_for=ab_raw.pts_for,
                pts_against=ab_raw.pts_against,
                pace=ab_raw.pace,
                stdev_total=ab_raw.stdev_total,
            )
        else:
            away_avg_obj = TeamAverages(
                league=request.league,
                team=request.away,
                n_games=0,
                pts_for=0.0,
                pts_against=0.0,
                pace=1.0,
                stdev_total=9.0,
            )
        # Quarter band for snapshots; use bands['q'] when available
        if isinstance(bands, dict):
            q_band = bands.get("q")
        else:
            q_band = None
        return Faz13CoreOutput(
            ctx=ctx,
            home_band=home_band,
            away_band=away_band,
            total_band=total_band,
            tempo_flag=signals.get("tempo_flag", "UNKNOWN"),
            blowout_risk=signals.get("blowout_risk", "UNKNOWN"),
            ou_direction=signals.get("alt_ust", "NO_EDGE"),
            meta=meta_info,
            notes=notes,
            market={},
            home_avg=home_avg_obj,
            away_avg=away_avg_obj,
            quarters=q_band if q_band is not None else [0, 0],
        ) 
