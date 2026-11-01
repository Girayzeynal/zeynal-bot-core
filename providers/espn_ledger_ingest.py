"""Fail-closed bridge from parsed ESPN NBA events to an immutable prediction ledger."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from prediction_ledger import OutcomeRecord, PredictionLedger


def ingest_completed_espn_nba_event(
    ledger: PredictionLedger, fixture_id: str, event: Dict[str, Any],
    observed_at_utc: int | None = None,
) -> bool:
    """Record a final score only for a pre-registered matching ESPN fixture.

    The event must already have passed parse_completed_nba_event().
    Returns False for unmatched or conflicting data; never creates predictions.
    """
    if not isinstance(event, dict) or event.get("provider") != "ESPN":
        return False
    if event.get("scope") != "FINAL_WITH_OT":
        return False
    if not isinstance(fixture_id, str) or not fixture_id.strip():
        return False
    now = observed_at_utc if observed_at_utc is not None else int(datetime.now(timezone.utc).timestamp())
    if type(now) is not int or now <= 0:
        return False
    try:
        source_id = event["provider_fixture_id"]
        start = event["start_ts_utc"]
        home = event["actual_home"]
        away = event["actual_away"]
        if not isinstance(source_id, str) or not source_id.strip():
            return False
        if type(start) is not int or start <= 0 or now <= start:
            return False
        if type(home) is not int or type(away) is not int or min(home, away) < 0:
            return False
        with ledger._connect() as db:
            row = db.execute("""SELECT p.prediction_ts_utc, p.scope,
                    f.start_ts_utc, v.provider, v.provider_fixture_id, v.start_ts_utc
                FROM predictions p
                JOIN fixture_starts f ON p.league=f.league AND p.fixture_id=f.fixture_id
                JOIN fixture_provenance v ON p.league=v.league AND p.fixture_id=v.fixture_id
                WHERE p.league='NBA' AND p.fixture_id=?""", (fixture_id,)).fetchone()
            if row is None or row != (row[0], "FINAL_WITH_OT", start, "ESPN", source_id, start):
                return False
            if not row[0] < start < now:
                return False
            existing = db.execute("""SELECT result_ts_utc, actual_home, actual_away, scope
                FROM outcomes WHERE league='NBA' AND fixture_id=?""", (fixture_id,)).fetchone()
            if existing is not None:
                return existing[1:] == (home, away, "FINAL_WITH_OT")
        return ledger.record_outcome(OutcomeRecord(
            fixture_id=fixture_id, league="NBA", result_ts_utc=now,
            actual_home=home, actual_away=away,
        ))
    except (KeyError, TypeError, ValueError):
        return False
