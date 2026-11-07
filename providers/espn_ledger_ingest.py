"""Fail-closed bridge from parsed ESPN NBA events to an immutable prediction ledger."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
import json

from prediction_ledger import PredictionLedger
from providers.espn_result_evidence import validate_result_evidence, same_result_observation


def ingest_completed_espn_nba_event(
    ledger: PredictionLedger, fixture_id: str, event: Dict[str, Any],
    observed_at_utc: int | None = None,
    *, result_evidence: dict | None = None,
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
        if type(home) is not int or type(away) is not int or min(home, away) < 0 or home == away:
            return False
        inputs = None
        if result_evidence is not None:
            inputs = ledger.load_prediction_inputs("NBA", fixture_id)
            if inputs is None:
                return False
            validate_result_evidence(result_evidence, event, now, inputs["sha256"])
        with ledger._connect() as db:
            db.execute("BEGIN IMMEDIATE")
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
            if inputs is not None:
                stored_input = db.execute(
                    "SELECT snapshot_sha256 FROM prediction_inputs WHERE league='NBA' AND fixture_id=?",
                    (fixture_id,)).fetchone()
                if stored_input != (inputs["sha256"],):
                    return False
            existing = db.execute("""SELECT result_ts_utc, actual_home, actual_away, scope
                FROM outcomes WHERE league='NBA' AND fixture_id=?""", (fixture_id,)).fetchone()
            if existing is not None:
                if existing[1:] != (home, away, "FINAL_WITH_OT"):
                    return False
                if result_evidence is not None:
                    prior = db.execute("SELECT evidence_json, evidence_sha256 FROM outcome_evidence WHERE league='NBA' AND fixture_id=?",
                                       (fixture_id,)).fetchone()
                    if prior is None:
                        return False  # Never attach observations posthoc.
                    prior_evidence = json.loads(prior[0])
                    if not isinstance(prior_evidence, dict) or prior_evidence.get("sha256") != prior[1]:
                        return False
                    validate_result_evidence(prior_evidence, event, existing[0], inputs["sha256"])
                    return same_result_observation(prior_evidence, result_evidence)
                return True
            if result_evidence is not None and db.execute(
                "SELECT 1 FROM outcome_evidence WHERE league='NBA' AND fixture_id=?", (fixture_id,)
            ).fetchone():
                return False
            db.execute(
                "INSERT INTO outcomes VALUES (?, ?, ?, ?, ?, ?)",
                ("NBA", fixture_id, now, home, away, "FINAL_WITH_OT"),
            )
            if result_evidence is not None:
                db.execute("INSERT INTO outcome_evidence VALUES (?,?,?,?)",
                    ("NBA", fixture_id, json.dumps(result_evidence, sort_keys=True, allow_nan=False),
                     result_evidence["sha256"]))
            return True
    except (KeyError, TypeError, ValueError):
        return False
