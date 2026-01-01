
"""
FAZ-13 Engine package initialization.

Exports the production-grade FAZ-13 engine and its core data models.
This module is intentionally minimal to avoid circular imports
and to stay compatible with main.py and downstream phases.
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
