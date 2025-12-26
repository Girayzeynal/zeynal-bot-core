"""
faz13_engine package
=====================

This package contains the pre‑match analysis engine used by the Zeynal Core bot.
It exposes several classes and data structures which encapsulate the inputs
and outputs of the engine as well as the engine itself.  Importing from
``faz13_engine`` will give you direct access to these classes without needing
to reference the underlying module path.

The principal class is :class:`Faz13Engine`, which consumes a
``TeamStatsAdapter`` (defined in ``baseline.team_baseline_store``) to supply
team statistics and produces pre‑match analysis results.  These results are
returned as instances of :class:`Faz13CoreOutput`, a simple data container
that also knows how to render itself as HTML for Telegram messages.

The input to :meth:`Faz13Engine.run_prematch` is a
:class:`PrematchRequest` object, which captures all of the information
necessary to perform an analysis (league, date and team names).  A
:class:`FixtureContext` is carried through the analysis to retain fixture
metadata.  :class:`TeamAverages` is a lightweight structure holding per‑team
averages; it is defined for completeness and potential future use.

Exports
-------

``Faz13Engine``
    The main pre‑match analysis engine.
``PrematchRequest``
    Data class encapsulating user id and fixture information.
``TeamAverages``
    Data class for summarising a team's recent performance.
``FixtureContext``
    Data class describing the analysed fixture.
``Faz13CoreOutput``
    Data class representing the outcome of a pre‑match analysis.
"""

from .faz13_engine import (
    Faz13Engine,
    PrematchRequest,
    TeamAverages,
    FixtureContext,
    Faz13CoreOutput,
)

__all__ = [
    "Faz13Engine",
    "PrematchRequest",
    "TeamAverages",
    "FixtureContext",
    "Faz13CoreOutput",
]
