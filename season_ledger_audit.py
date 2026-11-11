"""Read-only census of a static LOCAL ledger copy; never opens Fly /data.

Source-consistent candidates are not model/PIT-verified training examples.
Repeated prediction versions are counted separately from independent fixtures.
"""
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path
import hashlib
import math
import sqlite3
import time

from season_archive_inventory import validate_catalog


REQUIRED = {
    'prediction_versions': {'league', 'fixture_id', 'version_id', 'prediction_ts_utc', 'expected_home', 'expected_away', 'home_win_probability', 'scope'},
    'outcomes': {'league', 'fixture_id', 'result_ts_utc', 'actual_home', 'actual_away', 'scope'},
    'fixture_starts': {'league', 'fixture_id', 'start_ts_utc'},
    'fixture_provenance': {'league', 'fixture_id', 'provider', 'provider_fixture_id', 'start_ts_utc'},
}


def audit_ledger_fixtures(db_path, league='NBA', *, catalog=None, trusted_catalog_sha256=None, asof_utc=None):
    if league not in ('NBA', 'EuroLeague'):
        raise ValueError('unsupported_audit_league')
    now = int(time.time()) if asof_utc is None else asof_utc
    if type(now) is not int or not 0 < now <= int(time.time()):
        raise ValueError('invalid_audit_clock')
    if (catalog is None) != (trusted_catalog_sha256 is None):
        raise ValueError('archive_and_trusted_pin_required_together')
    archive = None if catalog is None else validate_catalog(catalog, trusted_sha256=trusted_catalog_sha256)
    if archive is not None and (archive['league'] != league or archive['ingested_at_utc'] > now):
        raise ValueError('archive_league_or_clock_mismatch')
    report = dict(status='blocked', league=league, reason=None, counts=None,
        independent_candidate_fixtures=None, source_matched_independent_fixtures=None,
        candidate_prediction_versions=None, verified_prematch_fixtures=None,
        season_start_year=None if archive is None else archive['season_start_year'],
        season_assignment='UNAVAILABLE_IN_LEDGER' if archive is None else 'MATCHED_SOURCE_CATALOG_ONLY',
        metrics=None, calibration_status='NOT_ESTABLISHED', automatic_model_update_permitted=False,
        prospective_predictions_created=0, production_database_accessed=False)

    def blocked(reason):
        return dict(report, reason=reason)

    path = Path(db_path).absolute()
    if path == Path('/data') or Path('/data') in path.parents:
        return blocked('production_path_refused_use_local_snapshot')
    if not path.is_file():
        return blocked('ledger_not_found')
    if path.is_symlink() or path.resolve() != path:
        return blocked('symlink_ledger_refused')
    if any(Path(str(path)+s).exists() for s in ('-wal', '-shm', '-journal')):
        return blocked('static_snapshot_required')
    try:
        if path.stat().st_size > 256*1024*1024:
            return blocked('bounded_snapshot_required')
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        with path.open('rb') as stream:
            header = stream.read(100)
        if not header.startswith(b'SQLite format 3\x00') or header[18:20] != b'\x01\x01':
            return blocked('static_sqlite_snapshot_required')
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1', uri=True, timeout=1)) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA query_only=ON')
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                return blocked('sqlite_integrity_failed')
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            missing = sorted(set(REQUIRED)-tables)
            if missing:
                return dict(blocked('missing_tables'), missing_tables=missing)
            rows = {}
            for table, fields in REQUIRED.items():
                columns = {r[1] for r in db.execute(f'PRAGMA table_info("{table}")')}
                if not fields <= columns:
                    return dict(blocked('missing_columns'), table=table, missing_columns=sorted(fields-columns))
                # Names come only from the module constant, values remain bound.
                selected = ','.join(sorted(fields))
                data = db.execute(f'SELECT {selected} FROM "{table}" WHERE league=? LIMIT 100001', (league,)).fetchall()
                if len(data) > 100000:
                    return blocked('bounded_snapshot_required')
                rows[table] = [dict(row) for row in data]
        after = hashlib.sha256(path.read_bytes()).hexdigest()
        if before != after or any(Path(str(path)+s).exists() for s in ('-wal', '-shm', '-journal')):
            return blocked('ledger_changed_during_audit')
    except (sqlite3.Error, OSError, ValueError):
        return blocked('ledger_read_or_integrity_error')

    report.update(ledger_sha256=before, source_files_unchanged=True,
                  counts={k: len(v) for k, v in rows.items()})
    lookups = {}
    for table in ('outcomes', 'fixture_starts', 'fixture_provenance'):
        grouped = defaultdict(list)
        for row in rows[table]:
            grouped[row['fixture_id']].append(row)
        lookups[table] = grouped
    source_index = {} if archive is None else {
        (archive['provider'], alias): game for game in archive['fixtures'] for alias in game['provider_fixture_ids']}
    provider = 'ESPN' if league == 'NBA' else 'EUROLEAGUE_LIVE'
    exclusions, candidates, matched = Counter(), {}, set()
    conflicts, source_conflicts = set(), set()
    eligible = 0
    for p in rows['prediction_versions']:
        fid = p['fixture_id']
        related = [lookups[t].get(fid, []) for t in ('outcomes', 'fixture_starts', 'fixture_provenance')]
        if any(len(v) != 1 for v in related):
            exclusions['missing_or_ambiguous_join'] += 1
            continue
        outcome, start, provenance = [v[0] for v in related]
        ts, tip, end = p['prediction_ts_utc'], start['start_ts_utc'], outcome['result_ts_utc']
        if not (all(type(v) is int for v in (ts, tip, end, provenance['start_ts_utc'])) and
                0 < ts < tip < end <= now and provenance['start_ts_utc'] == tip):
            exclusions['invalid_chronology_or_start'] += 1
            continue
        scope = p['scope']
        if scope not in ('REGULATION_ONLY', 'FINAL_WITH_OT') or scope != outcome['scope']:
            exclusions['scope_mismatch'] += 1
            continue
        actual = (outcome['actual_home'], outcome['actual_away'])
        prob = p['home_win_probability']
        if (not all(type(v) is int and v >= 0 for v in actual) or
                not all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in (p['expected_home'], p['expected_away'])) or
                (prob is not None and (type(prob) not in (int, float) or not math.isfinite(prob) or not 0 <= prob <= 1))):
            exclusions['invalid_score_or_probability'] += 1
            continue
        pid = provenance['provider_fixture_id']
        if provenance['provider'] != provider or type(pid) is not str or not pid or pid != pid.strip():
            exclusions['unsupported_provider_or_identity'] += 1
            continue
        key = (provider, pid)
        signature = (tip, scope, actual)
        if key in candidates and candidates[key] != signature:
            conflicts.add(key)
        candidates[key] = signature
        eligible += 1
        if archive is None:
            continue
        game = source_index.get(key)
        if game is None or game['start_ts_utc'] != tip or not game['completed']:
            exclusions['source_fixture_missing_or_not_final'] += 1
            continue
        if scope == 'REGULATION_ONLY':
            parts = game['periods']
            expected_actual = None if parts is None else (sum(parts['home'][:4]), sum(parts['away'][:4]))
        else:
            expected_actual = tuple(game['final_scores'])
        if expected_actual != actual:
            exclusions['source_score_or_scope_conflict'] += 1
            source_conflicts.add(game['canonical_id'])
            continue
        matched.add((key, game['canonical_id']))
    matched_ids = {cid for key, cid in matched if key not in conflicts and cid not in source_conflicts}
    report.update(status='audited_candidates_not_calibration', reason='verified_model_pit_and_oos_proof_required',
        independent_candidate_fixtures=len(set(candidates)-conflicts), candidate_prediction_versions=eligible,
        source_matched_independent_fixtures=None if archive is None else len(matched_ids),
        conflicting_provider_fixture_ids=len(conflicts), exclusions=dict(sorted(exclusions.items())),
        verified_prematch_fixtures=0,
        proof_missing=['canonical_team_identity_in_prediction', 'model_version_and_source_digest',
                       'feature_availability_before_prediction', 'independent_outcome_source_receipt',
                       'chronological_out_of_sample_evaluation'],
        season_archive_complete=False)
    return report
