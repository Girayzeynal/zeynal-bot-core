"""Fail-closed ESPN outcome import by immutable provider fixture identity.

Caller supplies the verified ESPN event and the time it was observed. This
module never guesses a fixture from team names or date and never downloads data.
"""
from __future__ import annotations

import sqlite3
from espn_final_parser import parse_espn_regulation_final
from prediction_ledger import OutcomeRecord, PredictionLedger


def import_verified_espn_outcome(db_path: str, event: object, observed_ts_utc: int) -> dict:
    parsed = parse_espn_regulation_final(event)
    if parsed is None:
        return {"status": "REJECTED_FINAL"}
    if type(observed_ts_utc) is not int or observed_ts_utc <= 0:
        return {"status": "REJECTED_TIME"}
    with sqlite3.connect(db_path) as db:
        try:
            matches = db.execute(
                """SELECT p.fixture_id, p.start_ts_utc, f.start_ts_utc
                   FROM fixture_provenance p
                   JOIN fixture_starts f ON p.league=f.league AND p.fixture_id=f.fixture_id
                   WHERE p.league='NBA' AND p.provider='ESPN' AND p.provider_fixture_id=?""",
                (parsed["provider_fixture_id"],),
            ).fetchall()
        except sqlite3.OperationalError:
            return {"status": "MISSING_PROVENANCE"}
        if len(matches) != 1:
            return {"status": "NO_UNIQUE_MATCH"}
        fixture_id, provenance_start, fixture_start = matches[0]
        if provenance_start != fixture_start or observed_ts_utc <= fixture_start:
            return {"status": "REJECTED_TIME"}
        try:
            predictions = db.execute(
                """SELECT prediction_ts_utc, scope FROM predictions
                   WHERE league='NBA' AND fixture_id=?""", (fixture_id,),
            ).fetchall()
        except sqlite3.OperationalError:
            return {"status": "MISSING_PREDICTION"}
        if len(predictions) != 1 or predictions[0][1] != "REGULATION_ONLY" or predictions[0][0] >= fixture_start:
            return {"status": "NOT_ELIGIBLE"}
    ledger = PredictionLedger(db_path)
    inserted = ledger.record_outcome(OutcomeRecord(
        fixture_id=fixture_id, league="NBA", result_ts_utc=observed_ts_utc,
        actual_home=parsed["home"], actual_away=parsed["away"], scope="REGULATION_ONLY",
    ))
    return {"status": "IMPORTED" if inserted else "ALREADY_RECORDED",
            "fixture_id": fixture_id, "has_overtime": parsed["has_overtime"]}
