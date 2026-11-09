"""Collect/replay only completed results for existing bound EuroLeague predictions."""
import argparse
import asyncio
import json
import os
import sqlite3
import time

from prediction_inputs import canonical_json
from prediction_ledger import PredictionLedger
from providers.euroleague_live import EuroleagueLiveAdapter, parse_game
from providers.euroleague_result_evidence import (
    capture_result_evidence, validate_result_evidence, same_fixture_identity, same_result_observation,
)


def load_bound_outcome(ledger, fixture_id):
    with ledger._connect() as db:
        raw = db.execute("SELECT evidence_json, evidence_sha256 FROM outcome_evidence WHERE league='EUROLEAGUE' AND fixture_id=?",
                         (fixture_id,)).fetchone()
        if raw is None:
            return None
        outcome = db.execute("SELECT result_ts_utc, actual_home, actual_away, scope FROM outcomes WHERE league='EUROLEAGUE' AND fixture_id=?",
                             (fixture_id,)).fetchone()
    fixture = ledger.load_fixture_observation("EUROLEAGUE", fixture_id)
    inputs = ledger.load_prediction_inputs("EUROLEAGUE", fixture_id)
    if fixture is None or inputs is None or outcome is None:
        raise ValueError("Orphan or unbound EuroLeague result observation")
    evidence = json.loads(raw[0])
    if not isinstance(evidence, dict) or evidence.get("sha256") != raw[1]:
        raise ValueError("Stored EuroLeague result digest mismatch")
    game = validate_result_evidence(evidence, original_fixture=fixture, original_inputs=inputs,
                                    observed_at_utc=outcome[0])
    if outcome[1:] != (game["actual_home"], game["actual_away"], "FINAL_WITH_OT"):
        raise ValueError("Stored EuroLeague outcome differs from observed final")
    return evidence


def ingest_bound_result(ledger, fixture_id, evidence):
    """All-or-nothing outcome/evidence insertion. Never creates or backfills predictions."""
    try:
        fixture = ledger.load_fixture_observation("EUROLEAGUE", fixture_id)
        inputs = ledger.load_prediction_inputs("EUROLEAGUE", fixture_id)
        if fixture is None or inputs is None:
            return False
        game = validate_result_evidence(evidence, original_fixture=fixture, original_inputs=inputs)
        observed = evidence["snapshot"]["observed_at_utc"]
        with ledger._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT p.prediction_ts_utc, p.expected_home, p.expected_away, p.scope,
                    v.provider, v.provider_fixture_id, v.start_ts_utc, f.start_ts_utc,
                    i.snapshot_sha256, s.observation_sha256
                FROM predictions p JOIN fixture_provenance v ON p.league=v.league AND p.fixture_id=v.fixture_id
                JOIN fixture_starts f ON p.league=f.league AND p.fixture_id=f.fixture_id
                JOIN prediction_inputs i ON p.league=i.league AND p.fixture_id=i.fixture_id
                JOIN fixture_observations s ON p.league=s.league AND p.fixture_id=s.fixture_id
                WHERE p.league='EUROLEAGUE' AND p.fixture_id=?""", (fixture_id,)).fetchone()
            payload = inputs["payload"]
            expected = (payload["prediction_ts_utc"], payload["expected_home"], payload["expected_away"], "FINAL_WITH_OT",
                        "EUROLEAGUE_LIVE", fixture_id, game["start_ts_utc"], game["start_ts_utc"],
                        inputs["sha256"], fixture["sha256"])
            if row != expected:
                return False
            previous = db.execute("SELECT result_ts_utc, actual_home, actual_away, scope FROM outcomes WHERE league='EUROLEAGUE' AND fixture_id=?",
                                  (fixture_id,)).fetchone()
            prior_evidence = db.execute("SELECT evidence_json, evidence_sha256 FROM outcome_evidence WHERE league='EUROLEAGUE' AND fixture_id=?",
                                        (fixture_id,)).fetchone()
            if previous is not None:
                if prior_evidence is None or previous[1:] != (game["actual_home"], game["actual_away"], "FINAL_WITH_OT"):
                    return False
                original = json.loads(prior_evidence[0])
                if not isinstance(original, dict) or original.get("sha256") != prior_evidence[1]:
                    return False
                validate_result_evidence(original, original_fixture=fixture, original_inputs=inputs,
                                         observed_at_utc=previous[0])
                return same_result_observation(original, evidence)
            if prior_evidence is not None:
                return False
            db.execute("INSERT INTO outcomes VALUES (?,?,?,?,?,?)",
                ("EUROLEAGUE", fixture_id, observed, game["actual_home"], game["actual_away"], "FINAL_WITH_OT"))
            db.execute("INSERT INTO outcome_evidence VALUES (?,?,?,?)",
                ("EUROLEAGUE", fixture_id, canonical_json(evidence), evidence["sha256"]))
            return True
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


async def reconcile_euroleague_result(*, adapter, ledger, fixture_id):
    if not isinstance(adapter, EuroleagueLiveAdapter) or not isinstance(ledger, PredictionLedger):
        raise TypeError("EuroleagueLiveAdapter and PredictionLedger required")
    try:
        fixture = ledger.load_fixture_observation("EUROLEAGUE", fixture_id)
        inputs = ledger.load_prediction_inputs("EUROLEAGUE", fixture_id)
    except (ValueError, TypeError):
        return {"status": "invalid_original_binding"}
    if fixture is None or inputs is None:
        return {"status": "missing_original_binding"}
    original = fixture["payload"]["fixture"]
    if int(time.time()) <= original["start_ts_utc"]:
        return {"status": "awaiting_tipoff", "fixture_id": fixture_id}
    url = fixture["payload"]["source_url"]
    raw = await adapter._get_json(url)
    if raw is None:
        return {"status": "provider_unavailable"}
    game = parse_game(raw, league="EUROLEAGUE", year=fixture["payload"]["year"], observed_at_utc=int(time.time()))
    if game is None:
        return {"status": "invalid_result"}
    if not same_fixture_identity(game, original):
        return {"status": "fixture_identity_conflict"}
    if game["status"] != "PLAYED":
        return {"status": "awaiting_final"}
    stats = await adapter._get_json(url+"/stats")
    if stats is None:
        return {"status": "provider_unavailable"}
    try:
        evidence = capture_result_evidence(raw, stats, original_fixture=fixture, original_inputs=inputs,
                                           observed_at_utc=int(time.time()))
    except (ValueError, TypeError, KeyError):
        return {"status": "invalid_result_evidence"}
    if not ingest_bound_result(ledger, fixture_id, evidence):
        return {"status": "unmatched_or_conflicting_result"}
    original_evidence = ledger.load_outcome_evidence("EUROLEAGUE", fixture_id)
    return dict(status="accepted", fixture_id=fixture_id, result_evidence_sha256=original_evidence["sha256"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", help="Existing local research ledger; verified finals may be recorded")
    parser.add_argument("fixture_id")
    args = parser.parse_args(argv)
    if not os.path.isfile(args.database):
        print(json.dumps({"status": "database_not_found"}))
        return 2
    async def run():
        adapter = EuroleagueLiveAdapter()
        try:
            return await reconcile_euroleague_result(adapter=adapter, ledger=PredictionLedger(args.database), fixture_id=args.fixture_id)
        finally:
            await adapter.aclose()
    try:
        result = asyncio.run(run())
    except (sqlite3.Error, ValueError, RuntimeError, OSError):
        result = {"status": "error"}
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result["status"] in ("accepted", "awaiting_tipoff", "awaiting_final") else 1


if __name__ == "__main__":
    raise SystemExit(main())
