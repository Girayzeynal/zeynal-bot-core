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


def record_faz13_verified_projection(
    ledger: PredictionLedger, core, *, fixture_id: str,
    provider_fixture_id: str, tipoff_utc: int,
    scope: str = "FINAL_WITH_OT",
) -> bool:
    """Bridge a verified FAZ13 output without inferring missing score fields.

    Provider fixture identity and tipoff must be independently authenticated.
    This function is not wired into Telegram handlers until that is available.
    """
    meta = getattr(core, "meta", None)
    ctx = getattr(core, "ctx", None)
    if not isinstance(meta, dict) or meta.get("data_quality") != "VERIFIED_BASELINE":
        raise ValueError("FAZ13 baseline provenance is not verified")
    if ctx is None or not isinstance(getattr(ctx, "league", None), str):
        raise ValueError("Missing FAZ13 fixture context")
    generated = meta.get("generated_at")
    if type(generated) is not int or generated <= 0:
        raise ValueError("Missing original prediction timestamp")
    home = meta.get("expected_home")
    away = meta.get("expected_away")
    total = meta.get("expected_total")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (home, away, total)):
        raise ValueError("Missing explicit finite FAZ13 score projections")
    if abs((home + away) - total) > 0.02:
        raise ValueError("Inconsistent FAZ13 team and total projections")
    return record_verified_prematch_projection(
        ledger, league=ctx.league, fixture_id=fixture_id, provider="ESPN",
        provider_fixture_id=provider_fixture_id, tipoff_utc=tipoff_utc,
        prediction_utc=generated, expected_home=home, expected_away=away,
        scope=scope,
    )


def record_faz13_for_espn_fixture(
    ledger: PredictionLedger, core, fixture: dict, *,
    resolved_home_team_id: str, resolved_away_team_id: str,
    scope: str = "FINAL_WITH_OT",
) -> bool:
    """Persist only when independently resolved FAZ13 teams match ESPN fixture IDs.

    `fixture` must come from parse_scheduled_nba_fixture. The caller remains
    responsible for authenticating the ESPN source and team resolution.
    """
    if not isinstance(fixture, dict) or fixture.get("provider") != "ESPN":
        raise ValueError("ESPN scheduled fixture required")
    for field in ("provider_fixture_id", "home_team_id", "away_team_id"):
        value = fixture.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Missing ESPN fixture identity")
    if not isinstance(resolved_home_team_id, str) or not resolved_home_team_id.strip():
        raise ValueError("Missing resolved home team ID")
    if not isinstance(resolved_away_team_id, str) or not resolved_away_team_id.strip():
        raise ValueError("Missing resolved away team ID")
    if (fixture["home_team_id"] != resolved_home_team_id
            or fixture["away_team_id"] != resolved_away_team_id):
        raise ValueError("FAZ13 home/away identity conflicts with ESPN fixture")
    tipoff = fixture.get("start_ts_utc")
    if type(tipoff) is not int or tipoff <= 0:
        raise ValueError("Invalid ESPN tipoff timestamp")
    ctx = getattr(core, "ctx", None)
    if ctx is None or getattr(ctx, "league", None) != "NBA":
        raise ValueError("ESPN NBA fixture cannot be assigned to another league")
    return record_faz13_verified_projection(
        ledger, core, fixture_id=fixture["provider_fixture_id"],
        provider_fixture_id=fixture["provider_fixture_id"],
        tipoff_utc=tipoff, scope=scope,
    )
