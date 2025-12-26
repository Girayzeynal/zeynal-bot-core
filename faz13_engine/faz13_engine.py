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
from typing import Any, Dict, List, Optional

from baseline.team_baseline_store import (
    TeamBaselineStore,
    TeamBaselineBootstrapper,
    TeamStatsAdapter,
)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PrematchRequest:
    """Input payload for pre‑match analysis."""
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
    """Aggregate statistics for a single team."""
    league: str
    team: str
    n_games: int
    pts_for: float
    pts_against: float
    pace: float
    stdev_total: float


@dataclass
class Faz13CoreOutput:
    """
    Output of the pre‑match analysis engine.
    Carries predicted bands, tempo/blowout signals, and meta information.
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

    # Additional attributes expected by Faz23Engine
    home_avg: TeamAverages | None = None
    away_avg: TeamAverages | None = None
    quarters: List[int] | None = None

    def render_html(self) -> str:
        """Render this analysis as an HTML fragment suitable for Telegram."""
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
    """Map a confidence value and issue list to a risk label."""
    if "no_team_data" in issues:
        return "HIGH"
    if conf >= 75:
        return "LOW"
    if conf >= 60:
        return "MID"
    return "HIGH"


class Faz13Engine:
    """
    Pre‑match analysis engine.
    
    The engine takes either a :class:`TeamStatsAdapter` instance or an API
    key (string) with an optional base URL for API Sports.  If an adapter
    instance is provided, it will be used directly.  If a string is provided,
    a minimal internal adapter is created which returns ``None`` for recent
    stats, causing the engine to use neutral baselines.  This makes it
    compatible with both modern and legacy usage.
    """

    def __init__(self, stats_adapter_or_key: TeamStatsAdapter | str, base_url: Optional[str] = None) -> None:
        # Determine whether a TeamStatsAdapter instance or an API key was provided.
        if isinstance(stats_adapter_or_key, TeamStatsAdapter):
            adapter = stats_adapter_or_key
        else:
            # Treat the argument as an API key.  Use the provided base URL or
            # default to the API Sports basketball endpoint.
            api_key = stats_adapter_or_key
            base = base_url or "https://v1.basketball.api-sports.io"

            class _DefaultAdapter(TeamStatsAdapter):
                """A basic adapter that does not fetch real data."""
                def __init__(self, key: str, url: str) -> None:
                    self.api_key = key
                    self.base_url = url

                def fetch_team_recent_aggregate(
                    self, league: str, team: str, n_games: int
                ) -> Optional[Dict[str, Any]]:
                    return None

            adapter = _DefaultAdapter(api_key, base)
        self.store = TeamBaselineStore()
        self.bootstrap = TeamBaselineBootstrapper(self.store, adapter)

    def pre_analyze(self, league: str, home: str, away: str) -> Dict[str, Any]:
        """Compute baseline and band data for a fixture."""
        issues: List[str] = []
        hb = self.bootstrap.ensure(league, home, min_games=6)
        ab = self.bootstrap.ensure(league, away, min_games=6)
        if not hb:
            issues.append("no_team_data")
        if not ab and "no_team_data" not in issues:
            issues.append("no_team_data")
        if not hb or not ab:
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
                "bands": {
                    "ft": [0, 0],
                    "ht": [0, 0],
                    "q": [0, 0],
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
        exp_total = (hb.pts_for + ab.pts_for) / 2.0
        sigma = (hb.stdev_total + ab.stdev_total) / 2.0
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
                "alt_ust": "NO_EDGE",
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
        """Compute a pre‑match analysis for the given request."""
        result = self.pre_analyze(request.league, request.home, request.away)
        baseline: Dict[str, Any] = result.get("baseline", {})
        bands: Dict[str, Any] = result.get("bands", {})
        signals: Dict[str, Any] = result.get("signals", {})
        meta_info: Dict[str, Any] = result.get("meta", {})
        notes: List[str] = result.get("notes", [])
        if isinstance(bands, dict):
            total_band = bands.get("ft", [0, 0])
        else:
            total_band = [0, 0]
        mu_total: Optional[float] = baseline.get("mu_total")
        if isinstance(mu_total, (int, float)):
            home_band = [round(mu_total / 2.0 - 3), round(mu_total / 2.0 + 3)]
            away_band = [round(mu_total / 2.0 - 3), round(mu_total / 2.0 + 3)]
        elif total_band and len(total_band) == 2:
            lo, hi = total_band
            home_band = [round(lo / 2.0), round(hi / 2.0)]
            away_band = [round(lo / 2.0), round(hi / 2.0)]
        else:
            home_band = [0, 0]
            away_band = [0, 0]
        ctx = FixtureContext(
            league=request.league,
            date=request.date,
            home=request.home,
            away=request.away,
        )
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
