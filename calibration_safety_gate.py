"""Read-only deployment gate for NBA and EuroLeague calibration readiness.

This gate never trains a model or mutates the ledger. It requires a meaningful
number of verified prematch fixtures, not merely a nonempty database.
"""
from __future__ import annotations

import argparse
import json

from pathlib import Path

from season_ledger_audit import audit_ledger_fixtures


def evaluate(db_path: str, leagues=("NBA", "EuroLeague"), minimum_fixtures: int = 100,
             *, catalogs=None) -> dict:
    if type(minimum_fixtures) is not int or minimum_fixtures < 2:
        raise ValueError("minimum_fixtures_must_be_at_least_2")
    if (type(leagues) not in (tuple, list) or not leagues or any(type(v) is not str for v in leagues)
            or len(set(leagues)) != len(leagues)
            or any(league not in ('NBA', 'EuroLeague') for league in leagues)):
        raise ValueError('supported_unique_leagues_required')
    catalogs = {} if catalogs is None else catalogs
    if type(catalogs) is not dict or not set(catalogs) <= set(leagues):
        raise ValueError('catalog_league_binding_required')
    results = {}
    for league in leagues:
        reference = catalogs.get(league, {})
        if type(reference) is not dict or set(reference) not in (set(), {'catalog', 'trusted_catalog_sha256'}):
            raise ValueError('archive_and_trusted_pin_required_together')
        audit = audit_ledger_fixtures(db_path, league, **reference)
        count = audit.get('source_matched_independent_fixtures')
        results[league] = {
            "audit": audit,
            "status": "blocked",
            "reason": audit.get('reason') or 'verified_season_archive_and_oos_evaluation_required',
            'candidate_sample_threshold_met': count is not None and count >= minimum_fixtures,
        }
    return {"status": "blocked", "minimum_independent_fixtures": minimum_fixtures,
            "leagues": results, "automatic_model_update_permitted": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database")
    parser.add_argument("--minimum-fixtures", type=int, default=100)
    for league in ('nba', 'euroleague'):
        parser.add_argument('--'+league+'-catalog')
        parser.add_argument('--'+league+'-catalog-sha256')
    args = parser.parse_args(argv)
    try:
        catalogs = {}
        for key, league in (('nba', 'NBA'), ('euroleague', 'EuroLeague')):
            path, pin = getattr(args, key+'_catalog'), getattr(args, key+'_catalog_sha256')
            if bool(path) != bool(pin):
                raise ValueError('archive_and_trusted_pin_required_together')
            if path:
                p = Path(path).absolute()
                if (p == Path('/data') or Path('/data') in p.parents or p.is_symlink()
                        or p.resolve() != p or p.stat().st_size > 16*1024*1024):
                    raise ValueError('local_bounded_archive_file_required')
                catalogs[league] = dict(catalog=json.loads(p.read_text()), trusted_catalog_sha256=pin)
        report = evaluate(args.database, minimum_fixtures=args.minimum_fixtures, catalogs=catalogs)
    except (ValueError, OSError) as exc:
        print(json.dumps({"status": "error", "reason": str(exc)}))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
