"""
Package initializer for ``faz17_engine``.

This module exposes the :class:`Faz17Engine` class so that callers can
import it directly from the package, e.g.:

    from faz17_engine import Faz17Engine

The :class:`Faz17Engine` orchestrates market enrichment for pre‑match
analysis results by querying The Odds API and matching fixtures.
"""

from .faz17_engine import Faz17Engine

# Re-exported names for `from faz17_engine import *` convenience.
__all__ = ["Faz17Engine"]
