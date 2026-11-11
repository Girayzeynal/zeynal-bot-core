"""Read-only deployment gate for NBA and EuroLeague calibration readiness.

This gate never trains a model or mutates the ledger. It requires a meaningful
number of verified prematch fixtures, not merely a nonempty database.
"""
from __future__ import annotations

import argparse
import json

from calibration_readiness import audit_calibration_readiness


def evaluate(db_path: str, leagues=("NBA", "EuroLeague"), minimum_fixtures: int = 100) -> dict:
    if minimum_fixtures < 2:
        raise ValueError("minimum_fixtures_must_be_at_least_2")
    results = {}
    for league in leagues:
        audit = audit_calibration_readiness(db_path, league)
        # Readiness reports versions, not independent fixtures. A version
        # count must never be treated as independent training samples.
        results[league] = {
            "audit": audit,
            "status": "blocked",
            "reason": "independent_verified_fixture_count_not_yet_audited"
            if audit.get("status") == "ready" else audit.get("reason", "unavailable"),
        }
    return {"status": "blocked", "minimum_independent_fixtures": minimum_fixtures,
            "leagues": results, "automatic_model_update_permitted": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database")
    parser.add_argument("--minimum-fixtures", type=int, default=100)
    args = parser.parse_args(argv)
    try:
        report = evaluate(args.database, minimum_fixtures=args.minimum_fixtures)
    except (ValueError, OSError) as exc:
        print(json.dumps({"status": "error", "reason": str(exc)}))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
