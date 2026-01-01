"""
faz13_engine package initialization.

This package exposes the FAZ-13 core engine and its primary data models.
"""

from typing import Optional, Dict

# Re-export main engine and core data models
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
