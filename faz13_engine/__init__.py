# faz13_engine/__init__.py
"""
Package initializer for faz13_engine.

This file re-exports the core classes and data structures defined in
faz13_engine.py so that other modules can import them directly from the
package (e.g. ``from faz13_engine import Faz13CoreOutput``).
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
