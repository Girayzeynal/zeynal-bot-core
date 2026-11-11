"""Additive snapshot/result tables; legacy prediction/outcome rows stay intact."""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import time

from core.team_identity import digest
from research_record_store import LIVE_PREMATCH_PREDICTION,validate_record
from season_archive_inventory import validate_catalog


class LiveAnalysisLedger:
    def __init__(self,path,*,require_legacy=False):
        self.path=Path(path).absolute()
        self.require_legacy=require_legacy
        if self.path.resolve()!=self.path or not self.path.parent.is_dir():raise ValueError('SAFE_EXISTING_LEDGER_DIRECTORY_REQUIRED')
        with self.connect() as db:
            if require_legacy:
                tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not {'predictions','outcomes'}<=tables:raise ValueError('EXISTING_PRODUCTION_LEDGER_SCHEMA_REQUIRED')
            db.executescript('''
              CREATE TABLE IF NOT EXISTS live_analysis_snapshots (
                league TEXT NOT NULL,fixture_id TEXT NOT NULL,model_digest TEXT NOT NULL,
                created_utc INTEGER NOT NULL,payload TEXT NOT NULL,sha256 TEXT NOT NULL,
                PRIMARY KEY(league,fixture_id,model_digest));
              CREATE TABLE IF NOT EXISTS verified_analysis_results (
                league TEXT NOT NULL,fixture_id TEXT NOT NULL,scope TEXT NOT NULL,
                payload TEXT NOT NULL,sha256 TEXT NOT NULL,PRIMARY KEY(league,fixture_id,scope));
              CREATE TABLE IF NOT EXISTS live_analysis_commit_receipts (
                league TEXT NOT NULL,fixture_id TEXT NOT NULL,model_digest TEXT NOT NULL,
                snapshot_sha256 TEXT NOT NULL,completed_utc INTEGER NOT NULL,
                PRIMARY KEY(league,fixture_id,model_digest));
              CREATE TRIGGER IF NOT EXISTS live_receipt_no_update BEFORE UPDATE ON live_analysis_commit_receipts
                BEGIN SELECT RAISE(ABORT,'IMMUTABLE_COMMIT_RECEIPT'); END;
              CREATE TRIGGER IF NOT EXISTS live_receipt_no_delete BEFORE DELETE ON live_analysis_commit_receipts
                BEGIN SELECT RAISE(ABORT,'IMMUTABLE_COMMIT_RECEIPT'); END;
              CREATE TRIGGER IF NOT EXISTS live_analysis_no_update BEFORE UPDATE ON live_analysis_snapshots
                BEGIN SELECT RAISE(ABORT,'IMMUTABLE_LIVE_SNAPSHOT'); END;
              CREATE TRIGGER IF NOT EXISTS live_analysis_no_delete BEFORE DELETE ON live_analysis_snapshots
                BEGIN SELECT RAISE(ABORT,'IMMUTABLE_LIVE_SNAPSHOT'); END;
              CREATE TRIGGER IF NOT EXISTS analysis_result_no_update BEFORE UPDATE ON verified_analysis_results
                BEGIN SELECT RAISE(ABORT,'IMMUTABLE_VERIFIED_RESULT'); END;
              CREATE TRIGGER IF NOT EXISTS analysis_result_no_delete BEFORE DELETE ON verified_analysis_results
                BEGIN SELECT RAISE(ABORT,'IMMUTABLE_VERIFIED_RESULT'); END;
            ''')

    @contextmanager
    def connect(self):
        if self.path.resolve()!=self.path:raise ValueError('LEDGER_SYMLINK_REFUSED')
        db=sqlite3.connect(self.path.as_uri()+'?mode=rw',uri=True,timeout=1) if self.require_legacy else sqlite3.connect(str(self.path),timeout=1)
        try:
            with db:yield db
        finally:db.close()

    @staticmethod
    def _decode(raw,pin,expected=None):
        p=json.loads(raw)
        if digest(p)!=pin:raise ValueError('LIVE_SNAPSHOT_HASH_MISMATCH')
        validate_record(LIVE_PREMATCH_PREDICTION,p,p['created_at_utc'])
        if expected is not None and (p['league'],p['fixture_id'],p['model_digest'])!=expected:
            raise ValueError('SNAPSHOT_INDEX_PAYLOAD_CONFLICT')
        return p

    def get(self,league,fixture_id,model_digest):
        with self.connect() as db:
            row=db.execute('SELECT payload,sha256 FROM live_analysis_snapshots WHERE league=? AND fixture_id=? AND model_digest=?',
                           (league,fixture_id,model_digest)).fetchone()
        return None if row is None else self._confirm_commit(self._decode(*row,expected=(league,fixture_id,model_digest)))

    def _confirm_commit(self,p):
        """Observe the durable snapshot AFTER commit, never backdate completion.

        Crash/late completion leaves an unconfirmed intent excluded from live
        counts and result evaluation. A restart may confirm it only before its
        original deadline; the original prediction is never rewritten.
        """
        key=(p['league'],p['fixture_id'],p['model_digest']);deadline=p.get('record_deadline_utc',p['fixture_start_utc'])
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            receipt=db.execute('SELECT snapshot_sha256,completed_utc FROM live_analysis_commit_receipts WHERE league=? AND fixture_id=? AND model_digest=?',key).fetchone()
            if receipt:
                if receipt[0]!=digest(p) or not p['created_at_utc']<=receipt[1]<deadline:raise ValueError('COMMIT_RECEIPT_CONFLICT')
                return p
            completed=int(time.time())
            if completed<p['created_at_utc']:raise ValueError('CLOCK_MOVED_BACKWARDS_DURING_COMMIT')
            if completed>=deadline:raise ValueError('MISSED_CUT_NO_DURABLE_COMMIT_PROOF')
            db.execute('INSERT INTO live_analysis_commit_receipts VALUES(?,?,?,?,?)',(*key,digest(p),completed))
        return p

    def commit(self,payload):
        p=deepcopy(payload)
        created=False
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            # Both checks use real time after any SQLite lock wait.
            now=int(time.time())
            deadline=p.get('record_deadline_utc',p['fixture_start_utc'])
            if type(deadline) is not int or not now<deadline<=p['fixture_start_utc']:raise ValueError('TIPOFF_BEFORE_ATOMIC_COMMIT')
            old=db.execute('SELECT payload,sha256 FROM live_analysis_snapshots WHERE league=? AND fixture_id=? AND model_digest=?',
                (p['league'],p['fixture_id'],p['model_digest'])).fetchone()
            if old:p=self._decode(*old,expected=(p['league'],p['fixture_id'],p['model_digest']))
            else:
                p.update(created_at_utc=now,cutoff_utc=now)
                validate_record(LIVE_PREMATCH_PREDICTION,p,now)
                if now-min(pin['observed_at_utc'] for pin in p['input_clocks'])>300:raise ValueError('SOURCE_STALE_BEFORE_COMMIT')
                text=json.dumps(p,sort_keys=True,allow_nan=False)
                db.execute('INSERT INTO live_analysis_snapshots VALUES(?,?,?,?,?,?)',
                    (p['league'],p['fixture_id'],p['model_digest'],now,text,digest(p)))
                if int(time.time())>=deadline:raise ValueError('TIPOFF_DURING_ATOMIC_COMMIT')
                p=json.loads(text);created=True
        # Return the exact persisted JSON representation (tuples become lists),
        # so the first response and a later idempotent read are identical.
        return self._confirm_commit(p),created

    def reconcile(self,catalog,*,trusted_sha256):
        c=validate_catalog(catalog,trusted_sha256=trusted_sha256)
        games={g['canonical_id']:g for g in c['fixtures'] if g['completed']}
        inserted=0
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            snapshots=db.execute('SELECT s.payload,s.sha256 FROM live_analysis_snapshots s JOIN live_analysis_commit_receipts r USING(league,fixture_id,model_digest)').fetchall()
            for raw,pin in snapshots:
                p=self._decode(raw,pin);self._confirm_existing_receipt(db,p);g=games.get(p['fixture_id'])
                if g is None or not set(g['provider_fixture_ids'])&set(p['provider_fixture_ids']):continue
                if (g['start_ts_utc']!=p['fixture_start_utc'] or g['home_team_id']!=p['home']['provider_id'] or
                        g['away_team_id']!=p['away']['provider_id']):raise ValueError('RESULT_FIXTURE_CONFLICT')
                if g['periods'] is None:continue
                actual=[sum(g['periods'][s][:4]) for s in ('home','away')]
                r=dict(record_type='VERIFIED_FINAL_RESULT',league=p['league'],fixture_id=p['fixture_id'],scope='REGULATION_ONLY',
                    actual=actual,final_with_ot=g['final_scores'],periods=g['periods'],source_catalog_sha256=trusted_sha256,
                    observed_at_utc=c['observed_at_utc'],ingested_at_utc=c['ingested_at_utc'])
                native=c['raw']['events'] if c['provider']=='ESPN' else c['raw']['data']
                r['source_fixture']=[v for v in native if v.get('id',v.get('identifier')) in g['provider_fixture_ids']]
                r['source_fixture_sha256']=digest(r['source_fixture'])
                old=db.execute('SELECT payload,sha256 FROM verified_analysis_results WHERE league=? AND fixture_id=? AND scope=?',
                    (p['league'],p['fixture_id'],r['scope'])).fetchone()
                if old:
                    previous=json.loads(old[0])
                    if digest(previous)!=old[1] or any(previous[k]!=r[k] for k in ('actual','final_with_ot','periods')):
                        raise ValueError('CONFLICTING_VERIFIED_FINAL_RESULT')
                    continue
                db.execute('INSERT INTO verified_analysis_results VALUES(?,?,?,?,?)',(p['league'],p['fixture_id'],r['scope'],json.dumps(r,sort_keys=True),digest(r)))
                inserted+=1
        return inserted

    def integrity(self):
        with self.connect() as db:
            status=db.execute('PRAGMA integrity_check').fetchone()[0]
            rows=db.execute('SELECT payload,sha256 FROM live_analysis_snapshots').fetchall()
            outcomes=db.execute('SELECT payload,sha256 FROM verified_analysis_results').fetchall()
            receipts=db.execute('SELECT league,fixture_id,model_digest,snapshot_sha256,completed_utc FROM live_analysis_commit_receipts').fetchall()
        if status!='ok':raise ValueError('SQLITE_INTEGRITY_FAILED')
        decoded={}
        for raw,pin in rows:
            p=self._decode(raw,pin);decoded[(p['league'],p['fixture_id'],p['model_digest'])]=p
        for league,fixture,model,pin,completed in receipts:
            p=decoded.get((league,fixture,model))
            if p is None or digest(p)!=pin or not p['created_at_utc']<=completed<p.get('record_deadline_utc',p['fixture_start_utc']):
                raise ValueError('COMMIT_RECEIPT_CONFLICT')
        for raw,pin in outcomes:
            if digest(json.loads(raw))!=pin:raise ValueError('RESULT_HASH_MISMATCH')
        return dict(sqlite=status,snapshots=len(receipts),unconfirmed_snapshots=len(rows)-len(receipts),verified_results=len(outcomes))

    def commit_proofs(self):
        with self.connect() as db:
            rows=db.execute('SELECT league,fixture_id,model_digest,snapshot_sha256,completed_utc FROM live_analysis_commit_receipts ORDER BY league,fixture_id').fetchall()
        return [dict(zip(('league','fixture_id','model_digest','snapshot_sha256','completed_utc'),r)) for r in rows]

    @staticmethod
    def _confirm_existing_receipt(db,p):
        r=db.execute('SELECT snapshot_sha256,completed_utc FROM live_analysis_commit_receipts WHERE league=? AND fixture_id=? AND model_digest=?',
            (p['league'],p['fixture_id'],p['model_digest'])).fetchone()
        if not r or r[0]!=digest(p) or not p['created_at_utc']<=r[1]<p.get('record_deadline_utc',p['fixture_start_utc']):
            raise ValueError('COMMIT_RECEIPT_CONFLICT')
