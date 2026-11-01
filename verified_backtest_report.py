"""Read-only report for verified prematch backtesting."""
from dataclasses import asdict
from prediction_ledger import PredictionLedger


def report(db_path: str, league: str = "NBA") -> dict:
    ledger = PredictionLedger(db_path)
    audit = ledger.audit_provenance(league)
    count = audit["provider_consistent_prematch_pairs"]
    if count == 0:
        return {"status": "no_verified_pairs", "audit": audit, "metrics": None}
    metrics = ledger.evaluate_provenance_verified(league)
    if metrics.n_games != count:
        raise RuntimeError("verified sample count mismatch")
    return {"status": "evaluated", "audit": audit, "metrics": asdict(metrics)}
