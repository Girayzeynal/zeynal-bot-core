"""
Initialization for the faz13_engine package.

This module exposes the main engine classes and data structures for
external imports. It pulls the key classes from the underlying
`faz13_engine` module so that users can simply do:

    from faz13_engine import Faz13Engine, PrematchRequest, FixtureContext,
        TeamAverages, Faz13CoreOutput
"""

from .faz13_engine import (
    Faz13Engine,
    PrematchRequest,
    FixtureContext,
    TeamAverages,
    Faz13CoreOutput,
)

__all__ = [
    "Faz13Engine",
    "PrematchRequest",
    "FixtureContext",
    "TeamAverages",
    "Faz13CoreOutput",
]  

