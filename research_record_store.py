"""Separate immutable research records; never opens the production ledger."""
from copy import deepcopy
from contextlib import contextmanager
import json
import math
from pathlib import Path
import sqlite3
import time

from core.team_identity import digest


HISTORICAL_DATA='HISTORICAL_DATA'
BACKTEST_SIMULATION='BACKTEST_SIMULATION'
LIVE_PREMATCH_PREDICTION='LIVE_PREMATCH_PREDICTION'
KINDS={HISTORICAL_DATA,BACKTEST_SIMULATION,LIVE_PREMATCH_PREDICTION}


def validate_record(kind,payload,created_at):
    if kind not in KINDS: raise ValueError('UNKNOWN_RECORD_TYPE')
    if type(payload) is not dict or type(created_at) is not int or not 0<created_at<=int(time.time()):
        raise ValueError('INVALID_RECORD_CLOCK_OR_PAYLOAD')
    if payload.get('record_type')!=kind: raise ValueError('RECORD_TYPE_BINDING_MISMATCH')
    for field in ('league','fixture_id','season'):
        if type(payload.get(field)) is not str or not payload[field].strip(): raise ValueError('RECORD_IDENTITY_REQUIRED')
    start=payload.get('fixture_start_utc')
    if type(start) is not int or start<=0: raise ValueError('FIXTURE_START_REQUIRED')
    if kind==HISTORICAL_DATA:
        if payload.get('prediction') is not None: raise ValueError('HISTORICAL_DATA_CANNOT_CONTAIN_PREDICTION')
        scores=payload.get('final_scores')
        if (start>=created_at or type(payload.get('source_catalog_sha256')) is not str or
                len(payload['source_catalog_sha256'])!=64 or type(scores) is not list or len(scores)!=2 or
                any(type(v) is not int or v<0 for v in scores)):
            raise ValueError('COMPLETED_SOURCE_REQUIRED')
    else:
        if type(payload.get('model_version')) is not str or not payload['model_version'].strip():
            raise ValueError('MODEL_VERSION_REQUIRED')
        cutoff=payload.get('cutoff_utc')
        if type(cutoff) is not int or not 0<cutoff<start: raise ValueError('PREMATCH_INFORMATION_CUTOFF_REQUIRED')
        if kind==BACKTEST_SIMULATION:
            if start>=created_at: raise ValueError('SIMULATION_TARGET_MUST_BE_HISTORICAL')
            if payload.get('evaluation_class') not in ('PIT_PROVEN_BACKTEST','AVAILABILITY_ASSUMED_RESEARCH','ABSTAIN'):
                raise ValueError('SIMULATION_CLASS_REQUIRED')
        else:
            # Importing a retrospectively generated forecast into this namespace
            # cannot turn its historical cutoff into a real creation timestamp.
            if not created_at<=cutoff<start: raise ValueError('LIVE_RECORD_AFTER_CUTOFF_OR_TIPOFF')
            if payload.get('evaluation_class')!='LIVE_RECORDED' or payload.get('actual') is not None:
                raise ValueError('LIVE_RECORD_CANNOT_CONTAIN_RESULT_OR_SIMULATION')
            prediction=payload.get('prediction')
            if (type(prediction) is not dict or any(type(prediction.get(s)) not in (int,float) or
                    not math.isfinite(prediction[s]) or prediction[s]<0 for s in ('home','away'))):
                raise ValueError('ACTUAL_PREDICTION_OUTPUT_REQUIRED')
            pins=payload.get('input_clocks')
            if type(pins) is not list or not pins: raise ValueError('LIVE_SOURCE_CLOCKS_REQUIRED')
            for pin in pins:
                o,i=pin['observed_at_utc'],pin['ingested_at_utc']
                if type(o) is not int or type(i) is not int or not 0<o<=i<=created_at:
                    raise ValueError('LIVE_SOURCE_NOT_AVAILABLE')


class ResearchRecordStore:
    """Opt-in local SQLite, INSERT-only. Existing foreign databases are refused."""
    def __init__(self,path):
        p=Path(path).absolute()
        if p==Path('/data') or Path('/data') in p.parents or p.resolve()!=p or not p.parent.is_dir():
            raise ValueError('ISOLATED_LOCAL_RESEARCH_PATH_REQUIRED')
        self.path=str(p)
        with self._connect() as db:
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables and tables!={'research_records'}: raise ValueError('FOREIGN_DATABASE_REFUSED')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS research_records (
                    kind TEXT NOT NULL CHECK(kind IN ('HISTORICAL_DATA','BACKTEST_SIMULATION','LIVE_PREMATCH_PREDICTION')),
                    record_key TEXT NOT NULL, created_at_utc INTEGER NOT NULL,
                    payload TEXT NOT NULL CHECK(json_valid(payload)), sha256 TEXT NOT NULL,
                    CHECK(COALESCE(json_extract(payload,'$.record_type')=kind,0)),
                    CHECK(kind!='LIVE_PREMATCH_PREDICTION' OR COALESCE(
                        created_at_utc<=json_extract(payload,'$.cutoff_utc') AND
                        json_extract(payload,'$.cutoff_utc')<json_extract(payload,'$.fixture_start_utc') AND
                        json_extract(payload,'$.evaluation_class')='LIVE_RECORDED' AND
                        json_type(payload,'$.actual')='null',0)),
                    PRIMARY KEY(kind,record_key));
                CREATE TRIGGER IF NOT EXISTS research_no_update BEFORE UPDATE ON research_records
                    BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RESEARCH_RECORD'); END;
                CREATE TRIGGER IF NOT EXISTS research_no_delete BEFORE DELETE ON research_records
                    BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RESEARCH_RECORD'); END;
            ''')

    @contextmanager
    def _connect(self):
        if Path(self.path).resolve()!=Path(self.path): raise ValueError('ISOLATED_LOCAL_RESEARCH_PATH_REQUIRED')
        db=sqlite3.connect(self.path,timeout=1)
        try:
            with db:yield db
        finally:db.close()

    def append(self,kind,key,payload):
        payload=deepcopy(payload);at=int(time.time())
        if type(key) is not str or not key.strip(): raise ValueError('RECORD_KEY_REQUIRED')
        validate_record(kind,payload,at)
        text=json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False)
        pin=digest(dict(kind=kind,record_key=key,created_at_utc=at,payload=payload))
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT created_at_utc,payload,sha256 FROM research_records WHERE kind=? AND record_key=?',(kind,key)).fetchone()
            if row:
                if row[1]!=text: raise ValueError('IMMUTABLE_RECORD_CONFLICT')
                if row[2]!=digest(dict(kind=kind,record_key=key,created_at_utc=row[0],payload=payload)):
                    raise ValueError('RESEARCH_RECORD_HASH_MISMATCH')
                return False
            db.execute('INSERT INTO research_records VALUES(?,?,?,?,?)',(kind,key,at,text,pin))
        return True

    def read(self,kind):
        if kind not in KINDS: raise ValueError('UNKNOWN_RECORD_TYPE')
        with self._connect() as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('RESEARCH_SQLITE_INTEGRITY_FAILED')
            rows=db.execute('SELECT record_key,created_at_utc,payload,sha256 FROM research_records WHERE kind=? ORDER BY record_key',(kind,)).fetchall()
        output=[]
        for key,at,raw,pin in rows:
            p=json.loads(raw);validate_record(kind,p,at)
            if pin!=digest(dict(kind=kind,record_key=key,created_at_utc=at,payload=p)):
                raise ValueError('RESEARCH_RECORD_HASH_MISMATCH')
            output.append(dict(kind=kind,record_key=key,created_at_utc=at,payload=p,sha256=pin))
        return output
