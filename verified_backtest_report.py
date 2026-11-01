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
    audit["verified_pair_coverage"] = (
        count / audit["matched"] if audit["matched"] else None
    )
    if count == 0:
        return {"status": "no_verified_pairs", "league": league, "audit": audit, "metrics": None}
    metrics = ledger.evaluate_provenance_verified(league)
    if metrics.n_games != count:
        raise RuntimeError("verified sample count mismatch")
    return {"status": "evaluated", "league": league, "audit": audit, "metrics": asdict(metrics)}
