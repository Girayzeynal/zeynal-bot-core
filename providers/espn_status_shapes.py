"""Aggregate safe ESPN event status shapes without exposing raw event payloads."""
from __future__ import annotations

from collections import Counter
from typing import Any


def summarize_espn_status_shapes(events: Any) -> dict:
    if not isinstance(events, list):
        raise ValueError("events must be a list")
    competition_types: Counter[str] = Counter()
    event_types: Counter[str] = Counter()
    for event in events:
        if not isinstance(event, dict):
            competition_types["missing"] += 1
            event_types["missing"] += 1
            continue
        event_status = event.get("status")
        event_type = event_status.get("type") if isinstance(event_status, dict) else None
        event_types[_status_label(event_type)] += 1
        competitions = event.get("competitions")
        if not isinstance(competitions, list) or len(competitions) != 1:
            competition_types["missing"] += 1
            continue
        competition = competitions[0]
        status = competition.get("status") if isinstance(competition, dict) else None
        kind = status.get("type") if isinstance(status, dict) else None
        competition_types[_status_label(kind)] += 1
    return {
        "event_status_types": dict(sorted(event_types.items())),
        "competition_status_types": dict(sorted(competition_types.items())),
    }


def _status_label(kind: Any) -> str:
    if not isinstance(kind, dict):
        return "missing"
    state = kind.get("state")
    completed = kind.get("completed")
    # Bounded, fixed labels prevent raw provider strings reaching logs.
    state_label = state if state in ("pre", "in", "post", "completed") else "other"
    completed_label = ("true" if completed is True else
                       "false" if completed is False else "other")
    return f"state={state_label},completed={completed_label}"
