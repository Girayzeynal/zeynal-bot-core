# baseline package initializer

"""Baseline package for storing and bootstrapping team baselines.

This package provides classes for persisting team baseline statistics to disk
and automatically bootstrapping a baseline when data is missing.  It is
designed to be lightweight and file‑based; you can swap in your own
storage backend by extending ``TeamBaselineStore``.
"""

__all__ = ["TeamBaseline", "TeamBaselineStore", "TeamBaselineBootstrapper", "TeamStatsAdapter"]
