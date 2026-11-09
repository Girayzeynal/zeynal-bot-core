"""Evaluate only predictions with replayable original inputs and final-result evidence.

No network calls or invented outcomes. The CLI evaluates a backup of the source
ledger so additive schema setup cannot modify the user's original database.
"""
from dataclasses import asdict

from historical_backtest import HistoricalPrediction, evaluate_predictions
from prediction_ledger import PredictionLedger
from walk_forward_calibration import evaluate_walk_forward
from bound_error_uncertainty import describe_error_uncertainty


def report_bound(db_path, league="NBA"):
    if league not in ("NBA", "EUROLEAGUE"):
        raise ValueError("Bound result evaluation supports NBA and EuroLeague only")
    ledger = PredictionLedger(db_path)
    ledger.audit_provenance(league)
    with ledger._connect() as db:
        predictions = db.execute("""SELECT fixture_id, prediction_ts_utc, expected_home,
                    expected_away, scope FROM predictions WHERE league=?
                    ORDER BY prediction_ts_utc, fixture_id""", (league,)).fetchall()
    excluded = dict(missing_inputs=0, invalid_inputs=0, awaiting_result=0,
                    scope_mismatch=0, missing_result_evidence=0, invalid_result_evidence=0)
    if league == "EUROLEAGUE":
        excluded.update(missing_fixture_observation=0, invalid_fixture_observation=0)
    records = []
    for fixture, predicted, home, away, scope in predictions:
        try:
            inputs = ledger.load_prediction_inputs(league, fixture)
        except (ValueError, TypeError):
            excluded["invalid_inputs"] += 1
            continue
        if inputs is None:
            excluded["missing_inputs"] += 1
            continue
        if league == "EUROLEAGUE":
            try:
                observed_fixture = ledger.load_fixture_observation(league, fixture)
            except (ValueError, TypeError, KeyError, AttributeError):
                excluded["invalid_fixture_observation"] += 1
                continue
            if observed_fixture is None:
                excluded["missing_fixture_observation"] += 1
                continue
        with ledger._connect() as db:
            outcome = db.execute("""SELECT result_ts_utc, actual_home, actual_away, scope
                    FROM outcomes WHERE league=? AND fixture_id=?""", (league, fixture)).fetchone()
        if outcome is None:
            excluded["awaiting_result"] += 1
            continue
        if outcome[3] != scope or scope != "FINAL_WITH_OT":
            excluded["scope_mismatch"] += 1
            continue
        try:
            evidence = ledger.load_outcome_evidence(league, fixture)
        except (ValueError, TypeError, KeyError, AttributeError):
            excluded["invalid_result_evidence"] += 1
            continue
        if evidence is None:
            excluded["missing_result_evidence"] += 1
            continue
        event = evidence["snapshot"]["event"]
        records.append(HistoricalPrediction(
            fixture, league, predicted, outcome[0], home, away, outcome[1], outcome[2],
            prediction_scope=scope, result_scope=outcome[3], fixture_start_ts_utc=event["start_ts_utc"]))
    if len(records) + sum(excluded.values()) != len(predictions):
        raise RuntimeError("Bound-result coverage reconciliation failed")
    return dict(status="evaluated" if records else "no_bound_results", league=league,
                provider="ESPN" if league == "NBA" else "EUROLEAGUE_LIVE",
                verification_scope=("original_inputs_and_observed_provider_final" if league == "NBA" else
                                    "original_inputs_fixture_and_observed_provider_final"),
                predictions=len(predictions), sample_size=len(records), excluded=excluded,
                metrics=asdict(evaluate_predictions(records)) if records else None,
                sample_size_assessment=("no_verified_sample" if not records else
                                        "small_sample" if len(records) < 30 else "descriptive_sample_only"),
                calibration_status="NOT_ESTABLISHED",
                walk_forward=evaluate_walk_forward(records),
                error_uncertainty=describe_error_uncertainty(records))
