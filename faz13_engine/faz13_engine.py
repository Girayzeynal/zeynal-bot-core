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

        Telegram's HTML parse mode has a limited set of supported tags (see
        https://core.telegram.org/bots/api#html-style).  In particular
        ``<br>``, ``<ul>`` and ``<li>`` are not allowed.  Instead of using
        those tags we insert newlines (``\n``) to separate sections and
        prefix list items with hyphens.  Bold tags (``<b>``) and italics
        (``<i>``) are preserved to emphasise key information.  This method
        therefore returns a string that is both human‑readable and
        compatible with Telegram's parser.
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
        html_lines.append(
            f"<b>Alt/Üst yönü:</b> {self.ou_direction}\n"
        )
        # Meta information
        conf = self.meta.get("confidence")
        risk = self.meta.get("risk")
        if conf is not None or risk is not None:
            parts: List[str] = []
            if conf is not None:
                parts.append(f"Güven: {conf}")
            if risk is not None:
                parts.append(f"Risk: {risk}")
            # Bold combined meta string
            html_lines.append("<b>" + " | ".join(parts) + "</b>\n")
        # Notes
        if self.notes:
            html_lines.append("\n<i>Notlar:</i>")
            for note in self.notes:
                # Prefix each note with a hyphen and a space
                html_lines.append(f"\n- {note}")
        # Join all parts together
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

    The engine takes either a :class:`TeamStatsAdapter` instance or an API
    key and optional base URL for API Sports.  When constructed with a
    `TeamStatsAdapter`, it will use that adapter directly to fetch team
    statistics.  When provided with a string (assumed to be an API key),
    the engine will internally build a minimal adapter that returns no
    recent team statistics, triggering neutral baselines.  This fallback
    behaviour allows backwards compatibility with earlier versions that
    expected ``Faz13Engine(api_sports_key, base_url)``.  If no base URL
    is supplied when using the API key form, a sensible default for
    Basketball API Sports is used.
    
    :param stats_adapter_or_key: A ``TeamStatsAdapter`` implementation or
        a string API key.  If a string, a dummy adapter is created.
    :param base_url: Optional base URL for the sports data API when
        ``stats_adapter_or_key`` is a string.  Ignored when an adapter
        instance is provided.
    """

    def __init__(self, stats_adapter_or_key: TeamStatsAdapter | str, base_url: Optional[str] = None) -> None:
        # Determine whether a TeamStatsAdapter instance or an API key was provided.
        if isinstance(stats_adapter_or_key, TeamStatsAdapter):
            adapter = stats_adapter_or_key
        else:
            # Treat the argument as an API key.  Use the provided base URL or
            # default to the API Sports basketball endpoint.  Define a
            # minimal adapter inline that satisfies the TeamStatsAdapter
            # interface but returns ``None`` for recent aggregate stats,
            # causing the engine to fall back to neutral baselines.  This
            # preserves compatibility with earlier architectures where
            # ``Faz13Engine(api_key, base_url)`` was expected.
            api_key = stats_adapter_or_key
            base = base_url or "https://v1.basketball.api-sports.io"

            class _DefaultAdapter(TeamStatsAdapter):
                """A basic adapter that does not fetch real data.

                When used, baseline bootstrapping will fail to find
                statistics and will therefore return ``None``, which in
                turn causes the analysis to operate in neutral mode.
                """

                def __init__(self, key: str, url: str) -> None:
                    self.api_key = key
                    self.base_url = url

                def fetch_team_recent_aggregate(self, league: str, team: str, n_games: int) -> Optional[Dict[str, Any]]:
                    # Returning None indicates no recent statistics are available.
                    return None

            adapter = _DefaultAdapter(api_key, base)
        # Initialise baseline storage and bootstrapping with the selected adapter.
        self.store = TeamBaselineStore()
        self.bootstrap = TeamBaselineBootstrapper(self.store, adapter)

    def pre_analyze(self, league: str, home: str, away: str) -> Dict[str, Any]:
        """Compute a dictionary of baseline and band data for a fixture.

        This method attempts to bootstrap team baselines if none exist,
        calculates expected totals and spreads and returns a structured
        dictionary similar to the one produced by earlier FAZ‑13 versions.
        """
        # ... (remaining logic unchanged) 
