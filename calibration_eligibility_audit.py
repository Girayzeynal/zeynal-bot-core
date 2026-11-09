"""Read-only calibration eligibility audit; never manufactures historical forecasts.

An eligible pair requires an original prediction, a final outcome, matching
scope, a pre-tipoff timestamp, consistent provider identity, and replayable
prediction inputs plus final-score evidence.
"""
from __future__ import annotations

from collections import Counter


def audit_calibration_eligibility(ledger, league="NBA"):
    if not isinstance(league, str) or not league.strip():
        raise ValueError("League is required")
    reasons = Counter()
    eligible = []
    with ledger._connect() as db:
        predictions = db.execute(
            "SELECT fixture_id,prediction_ts_utc,scope FROM predictions WHERE league=? ORDER BY fixture_id",
            (league,),
        ).fetchall()
        outcomes = {r[0]: r[1:] for r in db.execute(
            "SELECT fixture_id,result_ts_utc,scope FROM outcomes WHERE league=?", (league,)
        )}
        starts = {r[0]: r[1] for r in db.execute(
            "SELECT fixture_id,start_ts_utc FROM fixture_starts WHERE league=?", (league,)
        )} if _table_exists(db, "fixture_starts") else {}
        providers = {r[0]: r[1:] for r in db.execute(
            "SELECT fixture_id,provider,provider_fixture_id,start_ts_utc FROM fixture_provenance WHERE league=?",
            (league,),
        )} if _table_exists(db, "fixture_provenance") else {}
    for fixture, predicted, scope in predictions:
        outcome = outcomes.get(fixture)
        if outcome is None:
            reasons["missing_outcome"] += 1
            continue
        result_ts, result_scope = outcome
        start = starts.get(fixture)
        if start is None:
            reasons["missing_tipoff"] += 1
            continue
        if not (type(predicted) is int and type(start) is int and type(result_ts) is int
                and predicted < start < result_ts):
            reasons["invalid_timing"] += 1
            continue
        if scope != result_scope:
            reasons["scope_mismatch"] += 1
            continue
        provider = providers.get(fixture)
        if not provider or not provider[0] or not provider[1] or provider[2] != start:
            reasons["missing_or_conflicting_provider"] += 1
            continue
        try:
            inputs = ledger.load_prediction_inputs(league, fixture)
            if inputs is None:
                reasons["missing_prediction_inputs"] += 1
                continue
        except (ValueError, TypeError, KeyError):
            reasons["invalid_prediction_inputs"] += 1
            continue
        try:
            evidence = ledger.load_outcome_evidence(league, fixture)
            if evidence is None:
                reasons["missing_outcome_evidence"] += 1
                continue
        except (ValueError, TypeError, KeyError):
            reasons["invalid_outcome_evidence"] += 1
            continue
        eligible.append(fixture)
    return {
        "league": league,
        "predictions": len(predictions),
        "outcomes": len(outcomes),
        "matched": sum(f in outcomes for f, _, _ in predictions),
        "eligible_count": len(eligible),
        "eligible_fixture_ids": eligible,
        "excluded": dict(sorted(reasons.items())),
        "status": "ELIGIBLE_PAIRS_PRESENT" if eligible else "NO_VERIFIED_PREMATCH_PAIRS",
        # Passing the ledger consistency checks does not independently attest
        # the provider, establish forecast accuracy, or calibrate probabilities.
        "evidence_consistency": {
            "status": "PASSED" if eligible else "NO_ELIGIBLE_PAIRS",
            "pairs": len(eligible),
        },
        "provider_authenticity": {
            "status": "NOT_INDEPENDENTLY_VERIFIED",
            "verified_pairs": 0,
        },
        "predictive_performance": {
            "status": "NOT_EVALUATED",
            "mae": None,
            "rmse": None,
            "brier_score": None,
        },
        "note": "Recorded evidence consistency; independent provider authenticity is not proven.",
    }


def _table_exists(db, name):
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None
