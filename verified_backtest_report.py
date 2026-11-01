"""Read-only report for verified prematch backtesting."""
from dataclasses import asdict
from prediction_ledger import PredictionLedger


def report(db_path: str, league: str = "NBA") -> dict:
    if not isinstance(league, str) or not league.strip():
        raise ValueError("league must be a nonempty string")
    ledger = PredictionLedger(db_path)
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
    audit["verified_pair_coverage"] = (
        count / audit["matched"] if audit["matched"] else None
    )
    if count == 0:
        return {"status": "no_verified_pairs", "league": league, "audit": audit, "metrics": None}
    metrics = ledger.evaluate_provenance_verified(league)
    if metrics.n_games != count:
        raise RuntimeError("verified sample count mismatch")
    return {"status": "evaluated", "league": league, "audit": audit, "metrics": asdict(metrics)}
