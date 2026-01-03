"""
Package initializer for ``faz17_engine``.

This module exposes the public FAZ-17 API so that callers can import
core classes directly from the package, e.g.:

    from faz17_engine import Faz17Engine, MarketRequest

FAZ-17 is responsible for market enrichment and fixture matching
via The Odds API. It is designed to be:
- crash-safe
- backward compatible
- tolerant to missing market data
"""

from .faz17_engine import Faz17Engine, MarketRequest

# Explicit public exports
__all__ = [
    "Faz17Engine",
    "MarketRequest",
] 
