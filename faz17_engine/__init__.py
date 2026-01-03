"""
Package initializer for ``faz17_engine``.

Public FAZ-17 API surface.

Allows:
    from faz17_engine import Faz17Engine, MarketRequest

FAZ-17 responsibilities:
- Market enrichment
- Fixture matching
- Odds API integration
"""

# Import REAL class names (case-sensitive!)
from .faz17_engine import Faz17Engine, MarketRequest

# Explicit public exports
__all__ = [
    "Faz17Engine",
    "MarketRequest",
] 
