"""Read live archives without holding SQLite transactions during source validation."""
from collections import defaultdict
from contextlib import closing
import math
import re
import sqlite3
import time

from core.league_identity import resolve_league
from core.team_identity import digest
from hybrid_engine.live_metrics import metrics
from ledger_reports import LedgerReports, MAX_PAYLOAD_BYTES, MAX_ROWS
from hybrid_engine.sqlite_read_guard import BUSY_SECONDS,bounded_rows,retry_read
from live_analysis_ledger import LiveAnalysisLedger

MAX_READ_BYTES = 48 * 1024 * 1024
REPORT_ERRORS = (ValueError, KeyError, TypeError, OSError, sqlite3.Error, RuntimeError)


def failure(exc):
    if isinstance(exc, sqlite3.Error):
        extended = getattr(exc, 'sqlite_errorcode', None)
        name = getattr(exc, 'sqlite_errorname', None)
        primary = extended & 0xff if type(extended) is int else None
        # Older Python SQLite bindings expose neither result-code attributes
        # nor all result-code constants. Diagnostic failures must not abort a
        # recovery loop. Numeric fallbacks are stable SQLite primary codes.
        if primary is None:
            # Python 3.10 lacks the extended-code attributes. Recognize only
            # fixed SQLite diagnostics, never echo arbitrary exception text or
            # fabricate numeric codes that were not provided by the driver.
            return {
                'database is locked': 'SQLITE_BUSY',
                'database is busy': 'SQLITE_BUSY',
                'database table is locked': 'SQLITE_LOCKED',
                'interrupted': 'SQLITE_INTERRUPT',
                'file is not a database': 'SQLITE_INTEGRITY',
                'database disk image is malformed': 'SQLITE_INTEGRITY',
                'unable to open database file': 'SQLITE_ACCESS',
                'attempt to write a readonly database': 'SQLITE_ACCESS',
                'disk i/o error': 'SQLITE_IO',
            }.get(str(exc).strip().lower(), 'SQLITE_OTHER')
        kind = {
            getattr(sqlite3, 'SQLITE_BUSY', 5): 'SQLITE_BUSY',
            getattr(sqlite3, 'SQLITE_LOCKED', 6): 'SQLITE_LOCKED',
            getattr(sqlite3, 'SQLITE_INTERRUPT', 9): 'SQLITE_INTERRUPT',
            getattr(sqlite3, 'SQLITE_CORRUPT', 11): 'SQLITE_INTEGRITY',
            getattr(sqlite3, 'SQLITE_NOTADB', 26): 'SQLITE_INTEGRITY',
            getattr(sqlite3, 'SQLITE_CANTOPEN', 14): 'SQLITE_ACCESS',
            getattr(sqlite3, 'SQLITE_PERM', 3): 'SQLITE_ACCESS',
            getattr(sqlite3, 'SQLITE_READONLY', 8): 'SQLITE_ACCESS',
            getattr(sqlite3, 'SQLITE_AUTH', 23): 'SQLITE_ACCESS',
            getattr(sqlite3, 'SQLITE_IOERR', 10): 'SQLITE_IO',
        }.get(primary, 'SQLITE_OTHER')
        return kind + (f' ({name}/{extended})' if type(name) is str and re.fullmatch(r'SQLITE_[A-Z0-9_]+', name) else '')
    if isinstance(exc, TimeoutError):
        return 'REPORT_TIMEOUT'
    if isinstance(exc, OSError):
        return 'REPORT_FILE_ACCESS_OR_IO'
    label = str(exc)
    return label if re.fullmatch(r'[A-Z][A-Z0-9_]{1,100}', label) else 'REPORT_VALIDATION_FAILED'


class RuntimeLedgerReports(LedgerReports):
    """Operational reader. The experiment's pinned reader remains reproducible."""

    def _read_rows(self, league, fixture_id, fit, archived_by, settled_only):
        return retry_read(lambda:self._read_rows_once(league,fixture_id,fit,archived_by,settled_only))

    def _read_rows_once(self, league, fixture_id, fit, archived_by, settled_only):
        with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro', uri=True, timeout=BUSY_SECONDS)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            tables = {row[0] for row in bounded_rows(db,"SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'live_analysis_snapshots','live_analysis_commit_receipts','verified_analysis_results'} <= tables:
                return None
            where, params = [], []
            if league:
                where.append('s.league=?'); params.append(league)
            if fit:
                where.append('s.model_digest=?'); params.append(fit)
            if archived_by is not None:
                where.append('r.completed_utc<=?'); params.append(archived_by)
            if fixture_id is not None:
                where.append("(s.fixture_id=? OR EXISTS(SELECT 1 FROM json_each(s.payload,'$.provider_fixture_ids') p WHERE p.value=?))")
                params.extend((fixture_id, fixture_id))
            if settled_only:
                where.append("o.fixture_id IS NOT NULL")
            clause = ' WHERE ' + ' AND '.join(where) if where else ''
            sql = f'''SELECT s.league,s.fixture_id,s.model_digest,
                CASE WHEN length(CAST(s.payload AS BLOB))<={MAX_PAYLOAD_BYTES} THEN s.payload END,
                s.sha256,r.snapshot_sha256,r.completed_utc,
                CASE WHEN length(CAST(o.payload AS BLOB))<={MAX_PAYLOAD_BYTES} THEN o.payload END,
                o.sha256,length(CAST(s.payload AS BLOB)),length(CAST(o.payload AS BLOB))
                FROM live_analysis_snapshots s JOIN live_analysis_commit_receipts r USING(league,fixture_id,model_digest)
                LEFT JOIN verified_analysis_results o ON o.league=s.league AND o.fixture_id=s.fixture_id AND o.scope='REGULATION_ONLY'
                {clause} ORDER BY s.league,s.fixture_id,s.model_digest LIMIT ?'''
            rows, size = [], 0
            for row in bounded_rows(db,sql,[*params, MAX_ROWS+1]):
                if len(rows) >= MAX_ROWS:
                    raise ValueError('REPORT_SCAN_LIMIT')
                if row[-2] > MAX_PAYLOAD_BYTES or (row[-1] or 0) > MAX_PAYLOAD_BYTES:
                    raise ValueError('REPORT_PAYLOAD_LIMIT')
                size += row[-2] + (row[-1] or 0)
                if size > MAX_READ_BYTES:
                    raise ValueError('REPORT_READ_BYTES_LIMIT')
                rows.append(row)
            return rows

    def read(self, league=None, fixture_id=None, *, fit=None, archived_by=None, settled_only=False, summarize=True):
        code = resolve_league(league).code if league is not None else None
        if fixture_id is not None and (not isinstance(fixture_id,str) or not 1<=len(fixture_id)<=128 or any(c.isspace() for c in fixture_id)):
            raise ValueError('REPORT_FIXTURE_ID_REQUIRED')
        if self.path.resolve() != self.path:
            raise ValueError('REPORT_SYMLINK_REFUSED')
        if not self.path.is_file():
            return dict(status='ARCHIVE_UNAVAILABLE', groups=[], forecasts=[])
        rows = self._read_rows(code, fixture_id, fit, archived_by, settled_only)
        if rows is None:
            return dict(status='NO_VERIFIED_LIVE_SCHEMA', groups=[], forecasts=[])
        # Closing the read transaction releases its lock before hashing or parsing.
        forecasts, cohorts, fixtures = [], defaultdict(list), set()
        for league, fixture, model, raw, pin, receipt, completed, outcome, outcome_pin, _, _ in rows:
            p = LiveAnalysisLedger._decode(raw, pin, expected=(league,fixture,model))
            if pin != receipt or not p['created_at_utc'] <= completed < p.get('record_deadline_utc',p['fixture_start_utc']):
                raise ValueError('REPORT_COMMIT_PROOF_CONFLICT')
            if p.get('scope') != 'REGULATION_ONLY':
                raise ValueError('REPORT_FORECAST_SCOPE')
            ids = p['provider_fixture_ids']
            start = p['fixture_start_utc']
            if league == 'NBA':
                identity = dict(provider='ESPN', league='NBA', season_start_year=int(p['season'].split('/')[0]),
                                start_ts_utc=start, home_team_id=p['home']['provider_id'],
                                away_team_id=p['away']['provider_id'])
                if digest(identity)!=fixture or not ids or any(not isinstance(v,str) or not v.isascii() or not v.isdigit() for v in ids):
                    raise ValueError('REPORT_NATIVE_FIXTURE_IDENTITY')
            generated = p.get('prediction_generated_at_utc')
            if generated is not None and (type(generated) is not int or not 0 < generated <= p['created_at_utc']):
                raise ValueError('REPORT_GENERATION_AFTER_SNAPSHOT')
            scores = [p['prediction'][s] for s in ('home','away')]
            if not all(type(v) in (int,float) and math.isfinite(v) and v>=0 for v in scores):
                raise ValueError('REPORT_SCORE_REQUIRED')
            item = dict(fixture_id=fixture, league=league, season=p['season'], model_version=p['model_version'],
                model_digest=model, provider_fixture_ids=list(ids), prediction=scores, created_utc=p['created_at_utc'],
                snapshot_sha256=pin, actual=None, fixture_start_utc=start, predicted_quarters=p['prediction'].get('quarters'),
                winner=p['prediction'].get('winner'), intervals=p.get('intervals'), predicted_halves=p['prediction'].get('halves'),
                prediction_generated_at_utc=generated, parameter_fit_cutoff_utc=p.get('parameter_fit_cutoff_utc'),
                first_archived_at_utc=completed, home=p['home'].get('official_name',p['home']['provider_id']),
                away=p['away'].get('official_name',p['away']['provider_id']))
            if outcome is not None:
                result = self._result(outcome, outcome_pin, p)
                if result['observed_at_utc'] <= start:
                    raise ValueError('REPORT_FINAL_BEFORE_TIPOFF')
                item.update(actual=result['actual'], actual_periods=result['periods'], final_with_ot=result['final_with_ot'],
                            label_available_utc=result['ingested_at_utc'])
                if summarize:
                    cohorts[(league,p['season'],model,p['model_version'])].append(item)
            forecasts.append(item)
            fixtures.add((league,fixture))
        groups = []
        for (league, season, model, version), values in sorted(cohorts.items()):
            detail = metrics(values)
            groups.append(dict(league=league, season=season, model_digest=model, model_version=version,
                n=len(values), details=detail, team_mae=detail['team_scores']['mae'],
                team_rmse=detail['team_scores']['rmse'], total_mae=detail['total']['mae'],
                claim='DESCRIPTIVE_ONLY_NOT_MODEL_SUPERIORITY'))
        return dict(status='VERIFIED_LIVE_REPORT', scope='REGULATION_ONLY', groups=groups, forecasts=forecasts,
            unique_fixtures=len(fixtures), pending=sum(r['actual'] is None for r in forecasts),
            research_backtests_included=False, query_read_only=True)
