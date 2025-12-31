"""
Faz13_engine package initialisation.

This file ensures that any optional type hints used within the package
are properly imported to avoid ``NameError`` when the package is loaded.
It also re-exports the primary classes used by external callers.
"""

from typing import Optional, Dict  # Optional and Dict imported for type hints

# Re-export key classes from the submodule. Importing here makes them available
# at the package level, e.g. ``from faz13_engine import Faz13Engine``.
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
