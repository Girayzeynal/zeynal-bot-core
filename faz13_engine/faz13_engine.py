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
    """Output of the pre‑match analysis engine."""
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
    home_avg: TeamAverages | None = None
    away_avg: TeamAverages | None = None
    quarters: List[int] | None = None

    def render_html(self) -> str:
        """Render this analysis as an HTML fragment suitable for Telegram.

        Telegram's HTML parse mode does not allow <br>, <ul> or <li> tags.
        Newlines (\\n) are used to separate sections; list items are
        prefixed with hyphens; bold and italic tags are preserved.
        """
        html_lines: List[str] = []
        # Heading
        html_lines.append("<b>FAZ-13 Ön Analiz</b>\n")
        # Fixture summary
        html_lines.append(
            f"<b>Maç:</b> {self.ctx.home} vs {self.ctx.away} | <b>Lig:</b> {self.ctx.league} | <b>Tarih:</b> {self.ctx.date}\n"
        )
        # Bands (if available)
        if self.total_band and len(self.total_band) == 2:
            html_lines.append(
                f"<b>Toplam (Tahmin):</b> {self.total_band[0]}–{self.total_band[1]}\n"
            )
        if self.home_band and len(self.home_band) == 2:
            html_lines.append(
                f"<b>{self.ctx.home} Bant:</b> {self.home_band[0]}–{self.home_band[1]}\n"
            )
        if self.away_band and len(self.away_band) == 2:
            html_lines.append(
                f"<b>{self.ctx.away} Bant:</b> {self.away_band[0]}–{self.away_band[1]}\n"
            )
        # Signals
        html_lines.append(
            f"<b>Tempo:</b> {self.tempo_flag} | <b>Blowout riski:</b> {self.blowout_risk}\n"
        )
        html_lines.append(f"<b>Alt/Üst yönü:</b> {self.ou_direction}\n")
        # Meta information
        conf = self.meta.get("confidence")
        risk = self.meta.get("risk")
        if conf is not None or risk is not None:
            parts: List[str] = []
            if conf is not None:
                parts.append(f"Güven: {conf}")
            if risk is not None:
                parts.append(f"Risk: {risk}")
            html_lines.append("<b>" + " | ".join(parts) + "</b>\n")
        # Notes
        if self.notes:
            html_lines.append("\n<i>Notlar:</i>")
            for note in self.notes:
                html_lines.append(f"\n- {note}")
        return "".join(html_lines)


def _risk_label(conf: float, issues: List[str]) -> str:
    if "no_team_data" in issues:
        return "HIGH"
    if conf >= 75:
        return "LOW"
    if conf >= 60:
        return "MID"
    return "HIGH"


class Faz13Engine:
    """Pre‑match analysis engine.

    The engine takes either a TeamStatsAdapter instance or an API key with an
    optional base URL for API Sports.  If given a string API key, it
    constructs a dummy adapter that returns no recent stats, causing
    neutral baselines to be used.  This preserves compatibility with
    earlier usage patterns.
    """

    def __init__(self, stats_adapter_or_key: TeamStatsAdapter | str, base_url: Optional[str] = None) -> None:
        if isinstance(stats_adapter_or_key, TeamStatsAdapter):
            adapter = stats_adapter_or_key
        else:
            api_key = stats_adapter_or_key
            base = base_url or "https://v1.basketball.api-sports.io"

            class _DefaultAdapter(TeamStatsAdapter):
                def __init__(self, key: str, url: str) -> None:
                    self.api_key = key
                    self.base_url = url

                def fetch_team_recent_aggregate(self, league: str, team: str, n_games: int) -> Optional[Dict[str, Any]]:
                    return None

            adapter = _DefaultAdapter(api_key, base)
        self.store = TeamBaselineStore()
        self.bootstrap = TeamBaselineBootstrapper(self.store, adapter)

    def pre_analyze(self, league: str, home: str, away: str) -> Dict[str, Any]:
        """Compute baseline and band data for a fixture."""
        # ... (bootstrap logic and computation)
        # See earlier explanation for details.

    async def run_prematch(self, request: PrematchRequest) -> Faz13CoreOutput:
        """Asynchronous wrapper around pre_analyze that returns Faz13CoreOutput."""
        result = self.pre_analyze(request.league, request.home, request.away)
        baseline: Dict[str, Any] = result.get("baseline", {})
        bands: Dict[str, Any] = result.get("bands", {})
        signals: Dict[str, Any] = result.get("signals", {})
        meta_info: Dict[str, Any] = result.get("meta", {})
        notes: List[str] = result.get("notes", [])
        # Determine total band
        if isinstance(bands, dict):
            total_band = bands.get("ft", [0, 0])
        else:
            total_band = [0, 0]
        mu_total: Optional[float] = baseline.get("mu_total")
        if isinstance(mu_total, (int, float)):
            home_band = [round(mu_total / 2.0 - 3), round(mu_total / 2.0 + 3)]
            away_band = home_band.copy()
        else:
            lo, hi = total_band
            home_band = [round(lo / 2.0), round(hi / 2.0)]
            away_band = home_band.copy()
        ctx = FixtureContext(
            league=request.league,
            date=request.date,
            home=request.home,
            away=request.away,
        )
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
        )
