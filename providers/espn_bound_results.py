"""Collect a final score for an existing bound NBA prediction. Never makes predictions."""
import argparse
import asyncio
import json
import os
import sqlite3
import time
from datetime import datetime

from prediction_ledger import PredictionLedger
from providers.espn_adapter import ESPNAdapter, ESPN_BASE
from providers.espn_ledger_ingest import ingest_completed_espn_nba_event
from providers.espn_result_evidence import capture_result_evidence, parse_final_summary


async def reconcile_bound_result(*, adapter, ledger, fixture_id):
    if not isinstance(adapter, ESPNAdapter) or not isinstance(ledger, PredictionLedger):
        raise TypeError("ESPNAdapter and PredictionLedger required")
    try:
        inputs = ledger.load_prediction_inputs("NBA", fixture_id)
    except (ValueError, TypeError):
        return {"status": "invalid_prediction_inputs"}
    if inputs is None:
        return {"status": "missing_prediction_inputs"}
    with ledger._connect() as db:
        registered = db.execute("""SELECT p.prediction_ts_utc, p.scope, f.start_ts_utc,
                v.provider, v.provider_fixture_id, v.start_ts_utc
            FROM predictions p JOIN fixture_starts f ON p.league=f.league AND p.fixture_id=f.fixture_id
            JOIN fixture_provenance v ON p.league=v.league AND p.fixture_id=v.fixture_id
            WHERE p.league='NBA' AND p.fixture_id=?""", (fixture_id,)).fetchone()
    if (registered is None or registered[1] != "FINAL_WITH_OT"
            or registered[3] != "ESPN" or registered[2] != registered[5]
            or not 0 < registered[0] < registered[2]):
        return {"status": "invalid_registered_fixture"}
    source_id = registered[4]
    if not isinstance(source_id, str) or not source_id.isascii() or not source_id.isdigit():
        return {"status": "invalid_provider_fixture_id"}
    if int(time.time()) <= registered[2]:
        return {"status": "awaiting_tipoff", "fixture_id": fixture_id}
    payload = await adapter._get_json(f"{ESPN_BASE}/summary?event={source_id}")
    if payload is None:
        return {"status": "provider_unavailable"}
    try:
        header = payload["header"]
        if len(header["competitions"]) != 1:
            return {"status": "invalid_result"}
        competition = header["competitions"][0]
        source_start = datetime.fromisoformat(competition["date"].replace("Z", "+00:00"))
        if (header["id"] != source_id or competition["id"] != source_id
                or source_start.tzinfo is None or source_start.timestamp() != registered[2]):
            return {"status": "fixture_identity_conflict"}
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return {"status": "invalid_result"}
    observed = int(time.time())
    event = parse_final_summary(payload, observed)
    if event is None:
        try:
            statuses = [item["status"]["type"] for item in (header, competition) if "status" in item]
            pending = statuses and all(s.get("state") in ("pre", "in") and s.get("completed") is False for s in statuses)
        except (KeyError, TypeError, AttributeError):
            pending = False
        return {"status": "awaiting_final" if pending else "invalid_result"}
    if event["provider_fixture_id"] != source_id or event["start_ts_utc"] != registered[2]:
        return {"status": "fixture_identity_conflict"}
    context = inputs["payload"]["context"]
    refs = {side: await adapter.resolve_team(context[side]) for side in ("home", "away")}
    if any(not isinstance(refs[side], dict) or refs[side].get("id") != event[f"{side}_team_id"]
           for side in refs):
        return {"status": "team_identity_conflict"}
    observed = int(time.time())
    try:
        evidence = capture_result_evidence(payload, observed_at_utc=observed,
            input_sha256=inputs["sha256"], home_team_id=refs["home"]["id"],
            away_team_id=refs["away"]["id"])
        accepted = ingest_completed_espn_nba_event(
            ledger, fixture_id, event, observed, result_evidence=evidence)
    except (ValueError, TypeError):
        return {"status": "invalid_result_evidence"}
    if not accepted:
        return {"status": "unmatched_or_conflicting_result"}
    return {"status": "accepted", "fixture_id": fixture_id,
            "result_evidence_sha256": ledger.load_outcome_evidence("NBA", fixture_id)["sha256"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", help="Existing local research ledger; verified finals may be recorded")
    parser.add_argument("fixture_id")
    args = parser.parse_args(argv)
    if not os.path.isfile(args.database):
        print(json.dumps({"status": "database_not_found"}))
        return 2
    async def run():
        adapter = ESPNAdapter()
        try:
            return await reconcile_bound_result(adapter=adapter, ledger=PredictionLedger(args.database),
                                                 fixture_id=args.fixture_id)
        finally:
            await adapter.aclose()
    try:
        result = asyncio.run(run())
    except (sqlite3.Error, OSError, RuntimeError, ValueError):
        result = {"status": "error"}
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result["status"] in ("accepted", "awaiting_tipoff", "awaiting_final") else 1


if __name__ == "__main__":
    raise SystemExit(main())
