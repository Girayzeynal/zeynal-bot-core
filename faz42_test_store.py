"""Isolated synthetic storage tests on top of PredictionLedger connections.

No real storage mode exists here. Production or legacy database paths are refused.
"""
import json
from pathlib import Path
import sqlite3
import tempfile
import time
from statistics import fmean
import math

from prediction_ledger import PredictionLedger
from prediction_inputs import digest,canonical_json
from faz40_archive import require
from faz40_research import metrics,MODEL
from faz42_snapshot import validate_snapshot,reconcile
from faz41_evidence import REGISTRY,REGISTRY_PIN


class SyntheticSnapshotStore:
    def __init__(self,directory,*,guard_clock=None):
        root=Path(directory)
        require(not root.is_symlink() and root.resolve().parent==Path(tempfile.gettempdir()).resolve() and
                root.name.startswith('faz42-test-') and root.is_dir(),'ISOLATED_SYNTHETIC_DIRECTORY_REQUIRED')
        self.path=root/'faz42-synthetic.sqlite';require(not self.path.is_symlink(),'SYMLINK_DATABASE_REFUSED')
        if self.path.exists():
            with sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True) as db:
                require(db.execute('SELECT mode FROM faz42_meta').fetchall()==[('SYNTHETIC_TEST',)],'SYNTHETIC_STORE_MODE_REQUIRED')
        self.base=PredictionLedger(str(self.path));self.clock=guard_clock or (lambda:int(time.time()))
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS faz42_meta (mode TEXT PRIMARY KEY)')
            if not db.execute('SELECT 1 FROM faz42_meta').fetchone():db.execute("INSERT INTO faz42_meta VALUES ('SYNTHETIC_TEST')")
            db.execute('CREATE TABLE IF NOT EXISTS faz42_snapshots (canonical_id TEXT PRIMARY KEY,payload TEXT NOT NULL,sha256 TEXT NOT NULL,recorded_utc INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS faz42_results (canonical_id TEXT PRIMARY KEY REFERENCES faz42_snapshots(canonical_id),payload TEXT NOT NULL,sha256 TEXT NOT NULL)')
            for table,key in [('faz42_meta','mode'),('faz42_snapshots','canonical_id'),('faz42_results','canonical_id')]:
                for op in ('UPDATE','DELETE'):
                    db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{op} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable FAZ42'); END")
                db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_replace BEFORE INSERT ON {table} WHEN EXISTS (SELECT 1 FROM {table} WHERE {key}=NEW.{key}) BEGIN SELECT RAISE(ABORT,'immutable FAZ42 replacement'); END")

    def connect(self):
        db=self.base._connect();db.execute('PRAGMA busy_timeout=100');db.execute('PRAGMA foreign_keys=ON');return db

    def insert(self,snapshot,*,registry=REGISTRY,registry_pin=REGISTRY_PIN):
        require(snapshot['payload']['usage']=='SYNTHETIC_TEST','REAL_STORAGE_NOT_ACTIVATED')
        p=validate_snapshot(snapshot,registry=registry,registry_pin=registry_pin,recompute=True)
        require(p['usage']=='SYNTHETIC_TEST','REAL_STORAGE_NOT_ACTIVATED')
        cid=p['fixture']['canonical_id'];encoded=canonical_json(snapshot)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT payload,sha256 FROM faz42_snapshots WHERE canonical_id=?',(cid,)).fetchone()
            if old:
                require(old==(encoded,snapshot['sha256']),'IMMUTABLE_SNAPSHOT_CONFLICT');return False
            def check():
                at=self.clock();require(type(at) is int and p['created_utc']<=at and
                    (p['status']=='ABSTAIN' or at<p['fixture']['start_utc'] and at<=p['cutoff_utc']+60),'PREDICTION_EXPIRED_DURING_RECORDING')
                return at
            recorded=check()
            db.execute('INSERT INTO faz42_snapshots VALUES (?,?,?,?)',(cid,encoded,snapshot['sha256'],recorded))
            check()  # Roll back if SQL/validation crossed tipoff or generation deadline.
        return True

    def record_final(self,canonical_id,final,*,asof_utc,registry=REGISTRY,registry_pin=REGISTRY_PIN):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT payload FROM faz42_snapshots WHERE canonical_id=?',(canonical_id,)).fetchone()
            require(row is not None,'ORIGINAL_PREDICTION_REQUIRED');snapshot=json.loads(row[0])
            incoming=reconcile(snapshot,final,asof_utc=asof_utc,registry=registry,registry_pin=registry_pin)
            old=db.execute('SELECT payload,sha256 FROM faz42_results WHERE canonical_id=?',(canonical_id,)).fetchone()
            if old:
                previous=json.loads(old[0]);require(previous['sha256']==old[1] and digest(previous['payload'])==old[1], 'CORRUPT_RESULT')
                require(previous['payload']['prediction_sha256']==snapshot['sha256'] and
                        previous['payload']['result']['payload']['claims']==incoming['payload']['result']['payload']['claims'] and
                        final['payload']['observed_at_utc']>=previous['payload']['result']['payload']['observed_at_utc'], 'IMMUTABLE_FINAL_CONFLICT')
                return False
            db.execute('INSERT INTO faz42_results VALUES (?,?,?)',(canonical_id,canonical_json(incoming),incoming['sha256']))
        return True

    def audit(self,*,registry=REGISTRY,registry_pin=REGISTRY_PIN,minimum_games=30):
        require(type(minimum_games) is int and minimum_games>=2,'INVALID_EVALUATION_THRESHOLD')
        with sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True) as db:
            require(db.execute('PRAGMA integrity_check').fetchone()==('ok',),'SQLITE_INTEGRITY_FAILURE')
            shots=db.execute('SELECT canonical_id,payload,sha256,recorded_utc FROM faz42_snapshots').fetchall()
            results={cid:(raw,sha) for cid,raw,sha in db.execute('SELECT * FROM faz42_results')}
        require(set(results)<={r[0] for r in shots},'ORPHAN_FINAL_RESULT');groups={};pairs=[]
        for cid,raw,sha,recorded in shots:
            s=json.loads(raw);p=validate_snapshot(s,registry=registry,registry_pin=registry_pin)
            require(s['sha256']==sha and p['fixture']['canonical_id']==cid and p['usage']=='SYNTHETIC_TEST' and
                    p['created_utc']<=recorded<=int(time.time()) and
                    (p['status']=='ABSTAIN' or recorded<p['fixture']['start_utc']),'STORED_SNAPSHOT_BINDING')
            if cid not in results:continue
            raw,sha=results[cid];r=json.loads(raw);q=r['payload']
            expected=reconcile(s,q['result'],asof_utc=q['asof_utc'],registry=registry,registry_pin=registry_pin)
            require(r==expected and r['sha256']==sha,'STORED_RESULT_CANNOT_REPLAY')
            f=p['fixture'];key=(f['league'],f['season_end_year'],p['model_manifest']['payload']['git_sha'],p['scope'],p['usage'])
            groups.setdefault(key,[]).append((s,r));pairs.append(dict(canonical_id=cid,prediction_sha256=s['sha256'],result_sha256=r['sha256'],period_errors=q['period_errors']))
        summaries=[]
        for key,values in sorted(groups.items()):
            rows=[]
            for s,r in values:
                p=s['payload'];q=r['payload'];f=p['fixture'];a=q['actual_regulation'];pred=p['prediction']
                rows.append(dict(canonical_id=f['canonical_id'],league=f['league'],season_end_year=f['season_end_year'],model=MODEL,
                    scope='REGULATION_ONLY',usage='SYNTHETIC_TEST',expected_home=pred['home']['total'],expected_away=pred['away']['total'],
                    actual_home=a['home'],actual_away=a['away'],probabilities=p['simulation']['probabilities'],
                    cutoff_utc=p['cutoff_utc'],start_utc=f['start_utc'],result_observed_utc=q['result']['payload']['observed_at_utc']))
            aggregate=metrics(rows,minimum_games=minimum_games)
            summaries.append(dict(league=key[0],season_end_year=key[1],model_sha=key[2],scope=key[3],usage=key[4],games=len(rows),metrics=aggregate))
        return dict(status='SYNTHETIC_AUDIT_NOT_REAL_PERFORMANCE',snapshots=len(shots),pairs=pairs,cohorts=summaries,
                    prospective_records=0,parameters_updated=False,sqlite_integrity='ok')
