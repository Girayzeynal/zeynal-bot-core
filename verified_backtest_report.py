"""Read-only report for verified prematch backtesting."""
from dataclasses import asdict
import math
from prediction_ledger import PredictionLedger
from backtest_uncertainty import bootstrap_mean_interval, moving_block_mean_interval, block_length_sensitivity


def report(db_path: str, league: str = "NBA") -> dict:
    if not isinstance(league, str) or not league.strip():
        raise ValueError("league must be a nonempty string")
    ledger = PredictionLedger(db_path)
    # Ensure optional provenance schema exists before checking provider identities.
    # The ledger audit creates these tables for legacy or empty databases.
    ledger.audit_provenance(league)
    # ESPN-only report: never mix other provider observations into metrics.
    with ledger._connect() as db:
        foreign = db.execute(
            """SELECT COUNT(*) FROM predictions p
               JOIN outcomes o ON p.league=o.league AND p.fixture_id=o.fixture_id
               JOIN fixture_starts f ON p.league=f.league AND p.fixture_id=f.fixture_id
               JOIN fixture_provenance v ON p.league=v.league AND p.fixture_id=v.fixture_id
               WHERE p.league=? AND p.prediction_ts_utc < f.start_ts_utc
                 AND f.start_ts_utc < o.result_ts_utc AND p.scope=o.scope
                 AND f.start_ts_utc=v.start_ts_utc AND v.provider != 'ESPN'""",
            (league,),
        ).fetchone()[0]
    if foreign:
        raise ValueError("non-ESPN verified fixtures present; mixed-provider report refused")
    audit = ledger.audit_provenance(league)
    count = audit["provider_consistent_prematch_pairs"]
    audit["excluded_matched_pairs"] = audit["matched"] - count
    # Counts overlap: a fixture may fail more than one validation gate.
    audit["exclusion_reason_counts_overlap"] = True
    audit["exclusion_reasons"] = {
        "prediction_not_before_result": audit["invalid_time_pairs"],
        "prediction_result_scope_mismatch": audit["scope_mismatch_pairs"],
        "missing_fixture_start": audit["missing_fixture_start"],
        "missing_provider_identity": audit["missing_provider_identity"],
        "provider_fixture_start_conflict": audit["provider_start_conflicts"],
        "not_valid_prematch": audit["matched"] - audit["valid_prematch_pairs"],
    }
    # Mutually exclusive primary reasons, evaluated in a fixed priority order.
    with ledger._connect() as db:
        rows = db.execute(
            """SELECT p.prediction_ts_utc, o.result_ts_utc, p.scope, o.scope,
                      f.start_ts_utc, v.start_ts_utc, v.provider, v.provider_fixture_id
               FROM predictions p
               JOIN outcomes o ON p.league=o.league AND p.fixture_id=o.fixture_id
               LEFT JOIN fixture_starts f ON p.league=f.league AND p.fixture_id=f.fixture_id
               LEFT JOIN fixture_provenance v ON p.league=v.league AND p.fixture_id=v.fixture_id
               WHERE p.league=?""",
            (league,),
        ).fetchall()
    reasons = {
        "prediction_not_before_result": 0,
        "prediction_result_scope_mismatch": 0,
        "missing_fixture_start": 0,
        "prediction_not_before_tipoff": 0,
        "fixture_start_not_before_result": 0,
        "missing_provider_identity": 0,
        "provider_fixture_start_conflict": 0,
    }
    for prediction, result, p_scope, o_scope, start, provider_start, provider, provider_id in rows:
        if prediction >= result:
            reason = "prediction_not_before_result"
        elif p_scope != o_scope:
            reason = "prediction_result_scope_mismatch"
        elif start is None:
            reason = "missing_fixture_start"
        elif prediction >= start:
            reason = "prediction_not_before_tipoff"
        elif start >= result:
            reason = "fixture_start_not_before_result"
        elif provider_start is None or not provider or not provider_id:
            reason = "missing_provider_identity"
        elif start != provider_start:
            reason = "provider_fixture_start_conflict"
        else:
            continue
        reasons[reason] += 1
    audit["primary_exclusion_reasons"] = reasons
    if sum(reasons.values()) != audit["excluded_matched_pairs"]:
        raise RuntimeError("primary exclusion reason reconciliation failed")
    audit["verified_pair_coverage"] = (
        count / audit["matched"] if audit["matched"] else None
    )
    # Sample adequacy is descriptive, never a claim of prediction accuracy.
    audit["sample_size_assessment"] = (
        "no_verified_sample" if count == 0 else
        "small_sample" if count < 30 else
        "moderate_sample" if count < 100 else
        "larger_sample"
    )
    if count == 0:
        return {"status": "no_verified_pairs", "league": league, "audit": audit, "metrics": None}
    metrics = ledger.evaluate_provenance_verified(league)
    if metrics.n_games != count:
        raise RuntimeError("verified sample count mismatch")
    with ledger._connect() as db:
        rows = db.execute(
            """SELECT p.expected_home + p.expected_away,
                      o.actual_home + o.actual_away
               FROM predictions p
               JOIN outcomes o ON p.league=o.league AND p.fixture_id=o.fixture_id
               JOIN fixture_starts f ON p.league=f.league AND p.fixture_id=f.fixture_id
               JOIN fixture_provenance v ON p.league=v.league AND p.fixture_id=v.fixture_id
                                    AND f.start_ts_utc=v.start_ts_utc
               WHERE p.league=? AND p.prediction_ts_utc < f.start_ts_utc
                 AND f.start_ts_utc < o.result_ts_utc AND p.scope=o.scope
               ORDER BY f.start_ts_utc, p.fixture_id""",
            (league,),
        ).fetchall()
    if len(rows) != count:
        raise RuntimeError("uncertainty sample count mismatch")
    errors = [abs(expected - actual) for expected, actual in rows]
    if not math.isclose(sum(errors) / count, metrics.total_mae, rel_tol=1e-10, abs_tol=1e-10):
        raise RuntimeError("total MAE reconciliation failed")
    uncertainty = bootstrap_mean_interval(errors)
    block_uncertainty = moving_block_mean_interval(errors)
    sensitivity = block_length_sensitivity(errors)
    return {"status": "evaluated", "league": league, "audit": audit,
            "metrics": asdict(metrics), "uncertainty": {"total_mae": uncertainty,
                            "total_mae_block_bootstrap": block_uncertainty,
                            "block_length_sensitivity": sensitivity}}
