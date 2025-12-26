"""
faz13_engine package
=====================

This package contains the pre‑match analysis engine used by the Zeynal Core bot.
It exposes several classes and data structures which encapsulate the inputs
and outputs of the engine as well as the engine itself.
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
