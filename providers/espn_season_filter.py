"""Conservative ESPN NBA regular-season classifier.

No inference from date, score or event ID. A game is eligible only if
explicit ESPN season.type metadata identifies the NBA regular season (2).
"""
from __future__ import annotations

from typing import Any, Optional


def is_explicit_regular_season(event: Any) -> Optional[bool]:
    """True=regular, False=explicitly other, None=unknown/ambiguous."""
    if not isinstance(event, dict):
        return None
    season = event.get("season")
    if not isinstance(season, dict):
        return None
    kind = season.get("type")
    if type(kind) is int:
        return kind == 2
    if isinstance(kind, str) and kind in ("1", "2", "3", "4"):
        return kind == "2"
    return None
