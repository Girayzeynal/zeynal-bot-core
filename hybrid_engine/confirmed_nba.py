"""Strict NBA-only reader for a ledger shared with other leagues.

The pinned legacy forward reader stays unchanged for registered experiments.
SQL indices, payload identity and confirmed publication must agree.
"""
from contextlib import closing
import sqlite3
import time

from hybrid_engine.data import local_path
from live_analysis_ledger import LiveAnalysisLedger


def read_confirmed_nba(path):
    path=local_path(path)
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        deadline=time.monotonic()+2
        db.set_progress_handler(lambda:int(time.monotonic()>deadline),1000)
        rows=db.execute('''SELECT s.league,s.fixture_id,s.model_digest,
            CASE WHEN length(CAST(s.payload AS BLOB))<=524288 THEN s.payload END,
            s.sha256,r.snapshot_sha256,r.completed_utc
            FROM live_analysis_snapshots s JOIN live_analysis_commit_receipts r
            USING(league,fixture_id,model_digest) WHERE s.league='NBA' LIMIT 1001''').fetchall()
    if len(rows)>1000:raise ValueError('NBA_CONFIRMED_SCAN_LIMIT')
    out=[]
    for league,fid,md,raw,pin,receipt,archived in rows:
        if raw is None:raise ValueError('NBA_CONFIRMED_PAYLOAD_LIMIT')
        p=LiveAnalysisLedger._decode(raw,pin,expected=(league,fid,md))
        if (pin!=receipt or not p['prediction_generated_at_utc']<=p['created_at_utc']<=archived<
            p.get('record_deadline_utc',p['fixture_start_utc'])):raise ValueError('NBA_CONFIRMED_PUBLICATION_CONFLICT')
        out.append(dict(snapshot=p,snapshot_sha256=pin))
    return out
