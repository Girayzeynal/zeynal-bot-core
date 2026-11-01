"""Offline end-to-end ESPN NBA completion pipeline.

Only consumes supplied ESPN payloads; network retrieval is handled by ESPNAdapter.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from prediction_ledger import PredictionLedger
from providers.espn_completed_event import parse_completed_nba_event
from providers.espn_ledger_ingest import ingest_completed_espn_nba_event


def ingest_espn_payload(
    ledger: PredictionLedger, fixture_id: str, raw_event: Dict[str, Any],
    observed_at_utc: int | None = None,
) -> str:
    """Return a stable status; never report an unverified insertion as successful."""
    now = observed_at_utc if observed_at_utc is not None else int(datetime.now(timezone.utc).timestamp())
    if type(now) is not int or now <= 0:
        return "invalid_observation_time"
    parsed = parse_completed_nba_event(
        raw_event, datetime.fromtimestamp(now, tz=timezone.utc)
    )
    if parsed is None:
        return "invalid_or_incomplete_event"
    if not ingest_completed_espn_nba_event(ledger, fixture_id, parsed, now):
        return "unmatched_or_conflicting_fixture"
    return "accepted"
