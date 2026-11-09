"""Explicit, fail-closed bridge from pregame projections to the immutable ledger.

Caller must supply authenticated provider fixture identity and verified UTC tipoff.
This module never fetches or guesses identity, schedule, scores, or probabilities.
"""
from __future__ import annotations

import math
import time
from prediction_ledger import PredictionLedger, PredictionRecord
from prediction_inputs import canonical_json, validate_prediction_inputs


def record_verified_prematch_projection(
    ledger: PredictionLedger, *, league: str, fixture_id: str,
    provider: str, provider_fixture_id: str, tipoff_utc: int,
    prediction_utc: int, expected_home: float, expected_away: float,
    scope: str = "FINAL_WITH_OT",
    input_snapshot: dict | None = None,
    fixture_evidence: dict | None = None,
    stage_bundle: dict | None = None,
) -> bool:
    """Record one immutable pre-tipoff projection; reject incomplete provenance."""
    if not isinstance(ledger, PredictionLedger):
        raise TypeError("A PredictionLedger is required")
    for value in (league, fixture_id, provider, provider_fixture_id):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Nonempty fixture and provider identity required")
    if provider not in ("ESPN", "EUROLEAGUE_LIVE"):
        raise ValueError("Unsupported canonical projection provider")
    if provider == "EUROLEAGUE_LIVE" and (league != "EUROLEAGUE" or scope != "FINAL_WITH_OT"
            or input_snapshot is None or fixture_evidence is None or fixture_id != provider_fixture_id):
        raise ValueError("EuroLeague projections require original inputs and fixture evidence")
    if provider == "ESPN" and fixture_evidence is not None:
        raise ValueError("EuroLeague fixture observations cannot be assigned to ESPN")
    if type(tipoff_utc) is not int or type(prediction_utc) is not int:
        raise ValueError("UTC timestamps must be integer epoch seconds")
    if not 0 < prediction_utc < tipoff_utc:
        raise ValueError("Prediction must precede verified tipoff")
    if scope not in ("FINAL_WITH_OT", "REGULATION_ONLY"):
        raise ValueError("Unknown scoring scope")
    for value in (expected_home, expected_away):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError("Finite nonnegative expected scores required")
    serialized_inputs = None
    if input_snapshot is not None:
        validate_prediction_inputs(input_snapshot, league=league, prediction_utc=prediction_utc,
            expected_home=expected_home, expected_away=expected_away, scope=scope)
        serialized_inputs = canonical_json(input_snapshot)
    serialized_fixture = None
    if fixture_evidence is not None:
        from providers.euroleague_fixture_evidence import validate_fixture_evidence
        validate_fixture_evidence(fixture_evidence, fixture_id=fixture_id, tipoff_utc=tipoff_utc,
                                  prediction_utc=prediction_utc, input_snapshot=input_snapshot)
        serialized_fixture = canonical_json(fixture_evidence)
    # Prevent partially inserted records on provenance conflict.
    # A single transaction inserts provenance, projection and inputs or none.
    with ledger._connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if stage_bundle is not None:
            if league != 'NBA' or provider != 'ESPN' or scope != 'FINAL_WITH_OT':
                raise ValueError('FAZ24 requires NBA ESPN final-with-OT inputs')
            from faz24 import insert_stages
            insert_stages(db, stage_bundle, fixture_id=fixture_id, tipoff=tipoff_utc,
                          prediction_utc=prediction_utc, input_snapshot=input_snapshot)
        if provider == "EUROLEAGUE_LIVE" and int(time.time()) >= tipoff_utc:
            raise ValueError("EuroLeague fixture has already started; no historical backfill")
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
        prior_inputs = db.execute(
            "SELECT snapshot_json FROM prediction_inputs WHERE league=? AND fixture_id=?",
            (league, fixture_id)).fetchone()
        if serialized_inputs is not None:
            if prior_inputs and prior_inputs[0] != serialized_inputs:
                raise ValueError("Immutable prediction input snapshot already differs")
            if prior_prediction and not prior_inputs:
                raise ValueError("Cannot backfill inputs onto an existing prediction")
            if prior_inputs and not prior_prediction:
                raise ValueError("Orphan prediction input snapshot")
        if serialized_fixture is not None:
            prior_fixture = db.execute("SELECT observation_json, observation_sha256 FROM fixture_observations WHERE league=? AND fixture_id=?",
                                       (league, fixture_id)).fetchone()
            if prior_prediction and not prior_fixture:
                raise ValueError("Cannot backfill fixture evidence onto an existing prediction")
            if prior_fixture:
                import json
                previous = json.loads(prior_fixture[0])
                if not isinstance(previous, dict) or previous.get("sha256") != prior_fixture[1]:
                    raise ValueError("Stored EuroLeague fixture digest mismatch")
                validate_fixture_evidence(previous, fixture_id=fixture_id, tipoff_utc=tipoff_utc,
                                          prediction_utc=prediction_utc, input_snapshot=input_snapshot)
                old, new = dict(previous["payload"]), dict(fixture_evidence["payload"])
                old_time, new_time = old.pop("observed_at_utc"), new.pop("observed_at_utc")
                if not prior_prediction or old != new or new_time < old_time:
                    raise ValueError("Immutable fixture observation already differs")
        db.execute("INSERT OR IGNORE INTO fixture_starts VALUES (?,?,?)", (league, fixture_id, tipoff_utc))
        db.execute(
            "INSERT OR IGNORE INTO fixture_provenance VALUES (?,?,?,?,?)",
            (league, fixture_id, provider, provider_fixture_id, tipoff_utc),
        )
        cursor = db.execute(
            "INSERT OR IGNORE INTO predictions VALUES (?,?,?,?,?,?,?)",
            (league, fixture_id, prediction_utc, float(expected_home), float(expected_away), None, scope),
        )
        inserted = cursor.rowcount == 1
        if serialized_inputs is not None:
            db.execute("INSERT OR IGNORE INTO prediction_inputs VALUES (?,?,?,?)",
                       (league, fixture_id, serialized_inputs, input_snapshot["sha256"]))
        if serialized_fixture is not None:
            db.execute("INSERT OR IGNORE INTO fixture_observations VALUES (?,?,?,?)",
                       (league, fixture_id, serialized_fixture, fixture_evidence["sha256"]))
        return inserted


def record_faz13_verified_projection(
    ledger: PredictionLedger, core, *, fixture_id: str,
    provider_fixture_id: str, tipoff_utc: int,
    scope: str = "FINAL_WITH_OT",
    stage_bundle: dict | None = None,
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
        input_snapshot=meta.get("input_snapshot"), stage_bundle=stage_bundle,
    )


def record_faz13_for_espn_fixture(
    ledger: PredictionLedger, core, fixture: dict, *,
    resolved_home_team_id: str, resolved_away_team_id: str,
    scope: str = "FINAL_WITH_OT",
    stage_bundle: dict | None = None,
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
        tipoff_utc=tipoff, scope=scope, stage_bundle=stage_bundle,
    )
