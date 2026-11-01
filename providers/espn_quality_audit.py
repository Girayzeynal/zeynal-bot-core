"""Read-only quality audit for raw ESPN NBA scoreboard event batches."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from providers.espn_completed_event import parse_completed_nba_event


def _is_unfinished_event(raw: Any) -> bool:
    """Only classify an explicit non-completed ESPN status as unfinished.

    Missing or malformed status data remains unverifiable, not unfinished.
    """
    if not isinstance(raw, dict):
        return False
    competitions = raw.get("competitions")
    if not isinstance(competitions, list) or len(competitions) != 1:
        return False
    competition = competitions[0]
    if not isinstance(competition, dict):
        return False
    status = competition.get("status")
    if not isinstance(status, dict) or not isinstance(status.get("type"), dict):
        return False
    kind = status["type"]
    return (kind.get("state") in ("pre", "in", "post")
            and kind.get("state") != "completed"
            and kind.get("completed") is False)


def audit_espn_events(events: Any, observed_at_utc: int | None = None) -> dict:
    """Account for every raw event; do not silently accept conflicting duplicates.

    This is a data-quality report, not a measure of model accuracy or
    a verification that events were fetched from ESPN.
    """
    if not isinstance(events, list):
        raise ValueError("events must be a list")
    now = observed_at_utc if observed_at_utc is not None else int(
        datetime.now(timezone.utc).timestamp()
    )
    if type(now) is not int or now <= 0:
        raise ValueError("invalid observation timestamp")
    observed = datetime.fromtimestamp(now, tz=timezone.utc)
    counts: Counter[str] = Counter()
    invalid_indices: list[int] = []
    by_id: dict[str, dict] = {}
    occurrences: Counter[str] = Counter()
    conflicts: set[str] = set()
    for index, raw in enumerate(events):
        parsed = parse_completed_nba_event(raw, observed)
        if parsed is None:
            invalid_indices.append(index)
            counts["invalid_or_incomplete"] += 1
            if _is_unfinished_event(raw):
                counts["unfinished_events"] += 1
            else:
                counts["malformed_or_unverifiable_events"] += 1
            continue
        key = parsed["provider_fixture_id"]
        occurrences[key] += 1
        if key in by_id and by_id[key] != parsed:
            conflicts.add(key)
        elif key not in by_id:
            by_id[key] = parsed
    accepted_ids = set(by_id) - conflicts
    counts["accepted_unique"] = len(accepted_ids)
    counts["duplicate_identical"] = sum(
        n - 1 for key, n in occurrences.items()
        if key not in conflicts
    )
    counts["conflicting_fixture_ids"] = len(conflicts)
    counts["conflicting_records"] = sum(
        occurrences[key] for key in conflicts
    )
    total = len(events)
    return {
        "total_raw": total,
        "accepted_unique": counts["accepted_unique"],
        "invalid_or_incomplete": counts["invalid_or_incomplete"],
        "unfinished_events": counts["unfinished_events"],
        "malformed_or_unverifiable_events": counts["malformed_or_unverifiable_events"],
        "duplicate_identical": counts["duplicate_identical"],
        "conflicting_fixture_ids": counts["conflicting_fixture_ids"],
        "conflicting_records": counts["conflicting_records"],
        "conflicting_fixture_ids_detail": sorted(conflicts),
        "invalid_event_indices": invalid_indices,
        "coverage_rate": counts["accepted_unique"] / total if total else None,
    }
