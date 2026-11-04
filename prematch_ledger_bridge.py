"""Explicit, fail-closed bridge from pregame projections to the immutable ledger.

Caller must supply authenticated provider fixture identity and verified UTC tipoff.
This module never fetches or guesses identity, schedule, scores, or probabilities.
"""
from __future__ import annotations

import math
from prediction_ledger import PredictionLedger, PredictionRecord


def record_verified_prematch_projection(
    ledger: PredictionLedger, *, league: str, fixture_id: str,
    provider: str, provider_fixture_id: str, tipoff_utc: int,
    prediction_utc: int, expected_home: float, expected_away: float,
    scope: str = "FINAL_WITH_OT",
) -> bool:
    """Record one immutable pre-tipoff projection; reject incomplete provenance."""
    if not isinstance(ledger, PredictionLedger):
        raise TypeError("A PredictionLedger is required")
    for value in (league, fixture_id, provider, provider_fixture_id):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Nonempty fixture and provider identity required")
    if provider != "ESPN":
        raise ValueError("Canonical verified report currently supports ESPN only")
    if type(tipoff_utc) is not int or type(prediction_utc) is not int:
        raise ValueError("UTC timestamps must be integer epoch seconds")
    if not 0 < prediction_utc < tipoff_utc:
        raise ValueError("Prediction must precede verified tipoff")
    if scope not in ("FINAL_WITH_OT", "REGULATION_ONLY"):
        raise ValueError("Unknown scoring scope")
    for value in (expected_home, expected_away):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError("Finite nonnegative expected scores required")
    # Prevent partially inserted records on provenance conflict.
    # A single transaction inserts all three records or none.
    with ledger._connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS fixture_starts (
            league TEXT NOT NULL, fixture_id TEXT NOT NULL,
            start_ts_utc INTEGER NOT NULL, PRIMARY KEY (league, fixture_id)
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS fixture_provenance (
            league TEXT NOT NULL, fixture_id TEXT NOT NULL,
            provider TEXT NOT NULL, provider_fixture_id TEXT NOT NULL,
            start_ts_utc INTEGER NOT NULL,
            PRIMARY KEY (league, fixture_id),
            UNIQUE (league, provider, provider_fixture_id)
        )""")
        prior = db.execute(
            "SELECT start_ts_utc FROM fixture_starts WHERE league=? AND fixture_id=?",
            (league, fixture_id),
        ).fetchone()
        if prior and prior[0] != tipoff_utc:
            raise ValueError("Conflicting fixture start")
        prior = db.execute(
            "SELECT provider, provider_fixture_id, start_ts_utc FROM fixture_provenance WHERE league=? AND fixture_id=?",
            (league, fixture_id),
        ).fetchone()
        if prior and prior != (provider, provider_fixture_id, tipoff_utc):
            raise ValueError("Conflicting provider identity")
        collision = db.execute(
            "SELECT fixture_id FROM fixture_provenance WHERE league=? AND provider=? AND provider_fixture_id=?",
            (league, provider, provider_fixture_id),
        ).fetchone()
        if collision and collision[0] != fixture_id:
            raise ValueError("Provider fixture ID already belongs to another fixture")
        prior_prediction = db.execute(
            "SELECT prediction_ts_utc, expected_home, expected_away, home_win_probability, scope FROM predictions WHERE league=? AND fixture_id=?",
            (league, fixture_id),
        ).fetchone()
        prediction = (prediction_utc, float(expected_home), float(expected_away), None, scope)
        if prior_prediction and prior_prediction != prediction:
            raise ValueError("Immutable prediction already exists with different values")
        db.execute("INSERT OR IGNORE INTO fixture_starts VALUES (?,?,?)", (league, fixture_id, tipoff_utc))
        db.execute(
            "INSERT OR IGNORE INTO fixture_provenance VALUES (?,?,?,?,?)",
            (league, fixture_id, provider, provider_fixture_id, tipoff_utc),
        )
        cursor = db.execute(
            "INSERT OR IGNORE INTO predictions VALUES (?,?,?,?,?,?,?)",
            (league, fixture_id, prediction_utc, float(expected_home), float(expected_away), None, scope),
        )
        return cursor.rowcount == 1
