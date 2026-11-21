"""Offline read-only research-ledger audit. Never deletes, migrates or settles data."""
import argparse
from collections import defaultdict
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from core.team_identity import digest
from hybrid_engine.data import local_path
from live_analysis_ledger import LiveAnalysisLedger
from ledger_reports import LedgerReports,MAX_PAYLOAD_BYTES,MAX_ROWS


def file_sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(65536),b''):h.update(chunk)
    return h.hexdigest()


def audit_ledger(path,*,assets_directory=None):
    path=local_path(path)
    if not path.is_file():raise ValueError('AUDIT_EXISTING_RESEARCH_LEDGER_REQUIRED')
    before=file_sha(path);asset_jobs=[];total_payload_bytes=0;rows=[];aliases=defaultdict(set);versions=defaultdict(set);pins_seen=set();issues=[]
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.2)) as db:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN');deadline=time.monotonic()+5
        db.set_progress_handler(lambda:int(time.monotonic()>deadline),1000)
        integrity=db.execute('PRAGMA integrity_check(1)').fetchone()[0]
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required={'live_analysis_snapshots','live_analysis_commit_receipts','verified_analysis_results'}
        if not required<=tables:raise ValueError('AUDIT_VERIFIED_LIVE_SCHEMA_REQUIRED')
        sql=f'''SELECT s.league,s.fixture_id,s.model_digest,s.created_utc,
            CASE WHEN length(CAST(s.payload AS BLOB))<={MAX_PAYLOAD_BYTES} THEN s.payload END,
            s.sha256,r.snapshot_sha256,r.completed_utc FROM live_analysis_snapshots s
            LEFT JOIN live_analysis_commit_receipts r USING(league,fixture_id,model_digest)
            WHERE s.league='NBA' ORDER BY s.fixture_id,s.model_digest LIMIT {MAX_ROWS+1}'''
        for league,fid,model,created,raw,pin,receipt,archived in db.execute(sql):
            if len(rows)>=MAX_ROWS:raise ValueError('AUDIT_ROW_BUDGET')
            row=dict(fixture_id=fid,model_digest=model,snapshot_sha256=pin,findings=[])
            rows.append(row)
            try:
                if raw is None:raise ValueError('AUDIT_PAYLOAD_BUDGET')
                total_payload_bytes+=len(raw.encode())
                if total_payload_bytes>16*1024*1024:raise ValueError('AUDIT_TOTAL_PAYLOAD_BUDGET')
                p=LiveAnalysisLedger._decode(raw,pin,expected=(league,fid,model))
                row.update(home=p['home'].get('official_name'),away=p['away'].get('official_name'),
                    provider_fixture_ids=p['provider_fixture_ids'],model_version=p['model_version'],
                    prediction=p['prediction'],prediction_generated_at_utc=p.get('prediction_generated_at_utc'),
                    snapshot_created_at_utc=p['created_at_utc'],first_archived_at_utc=archived,fixture_start_utc=p['fixture_start_utc'])
                if created!=p['created_at_utc']:row['findings'].append('INDEX_CREATED_CLOCK_CONFLICT')
                generated=p.get('prediction_generated_at_utc')
                if generated is None:row['findings'].append('GENERATION_CLOCK_SEPARATELY_UNRECORDED')
                elif type(generated) is not int or not 0<generated<=p['created_at_utc']<p['fixture_start_utc']:
                    row['findings'].append('INVALID_OR_POSTTIPOFF_GENERATION')
                if receipt is None:row['findings'].append('UNCONFIRMED_SNAPSHOT_EXCLUDED_FROM_LIVE_REPORTS')
                elif receipt!=pin or type(archived) is not int or not created<=archived<p.get('record_deadline_utc',p['fixture_start_utc']):
                    row['findings'].append('COMMIT_PROOF_CONFLICT')
                identity=dict(provider='ESPN',league='NBA',season_start_year=int(p['season'].split('/')[0]),
                    start_ts_utc=p['fixture_start_utc'],home_team_id=p['home']['provider_id'],away_team_id=p['away']['provider_id'])
                if digest(identity)!=fid:row['findings'].append('CANONICAL_FIXTURE_ID_CONFLICT')
                if not isinstance(p['provider_fixture_ids'],list) or not p['provider_fixture_ids'] or any(not isinstance(v,str) or not v.isascii() or not v.isdigit() for v in p['provider_fixture_ids']):
                    row['findings'].append('INVALID_ESPN_ID')
                else:
                    for pid in p['provider_fixture_ids']:aliases[pid].add(fid)
                if pin in pins_seen:row['findings'].append('REPEATED_SNAPSHOT_SHA')
                pins_seen.add(pin);versions[fid].add(model)
                if assets_directory is not None and p.get('input_asset') and p.get('prepared_asset'):
                    asset_jobs.append((row,p))
                else:row['source_audit_status']='BLOCKED_NATIVE_ASSETS_NOT_SUPPLIED_OR_LEGACY_RECORD'
            except Exception as exc:
                # Fixed type only: never echo raw SQL/API/credential-bearing text.
                row['findings'].append('ROW_VALIDATION_FAILED');row['error_type']=type(exc).__name__
        orphan_receipts=db.execute('SELECT COUNT(*) FROM live_analysis_commit_receipts r LEFT JOIN live_analysis_snapshots s USING(league,fixture_id,model_digest) WHERE r.league=\'NBA\' AND s.fixture_id IS NULL').fetchone()[0]
        if orphan_receipts:issues.append(dict(code='ORPHAN_COMMIT_RECEIPTS',count=orphan_receipts))
    # Release the database read transaction before file/parameter audits; existing
    # immutable references still bind each source and a running bot can append.
    for row,p in asset_jobs:
        try:
            from hybrid_engine.prediction_audit import audit_snapshot,Assets
            row['source_audit']=audit_snapshot(p,assets_directory)
            from hybrid_engine.forecast_error_review import input_profile
            row['input_profile']=input_profile(p,assets_directory,source_audit=row['source_audit'])
            prepared=Assets(assets_directory).read(p['prepared_asset'])
            row['calibration_inputs']=dict(inputs_available_max_utc=p['source_data_time_utc'],
                model_fit_cutoff_utc=p['parameter_fit_cutoff_utc'],
                model_training_ids=list(prepared['payload']['model']['training_ids']),
                prepared_artifact_sha256=p['prepared_artifact_sha256'])
        except Exception as exc:
            row['findings'].append('NATIVE_ASSET_AUDIT_FAILED');row['error_type']=type(exc).__name__
    for pid,fids in sorted(aliases.items()):
        if len(fids)>1:issues.append(dict(code='ESPN_ID_BOUND_TO_MULTIPLE_FIXTURES',provider_fixture_id=pid,fixture_ids=sorted(fids)))
    try:
        performance=LedgerReports(path).read('NBA')
        performance_status='READ_ONLY_NATIVE_VERIFIED'
    except Exception as exc:
        performance=None;performance_status='BLOCKED_INVALID_ARCHIVE_OR_NATIVE_RESULT';issues.append(dict(code='LIVE_REPORT_REFUSED',error_type=type(exc).__name__))
    after=file_sha(path)
    return dict(format='READ_ONLY_NBA_LEDGER_AUDIT_V1',observed_at_utc=int(time.time()),sqlite_integrity=integrity,
        snapshots_examined=len(rows),unique_fixtures=len({r['fixture_id'] for r in rows}),rows=rows,issues=issues,
        multiple_model_versions=[dict(fixture_id=fid,models=len(v),classification='VERSIONS_NOT_AUTOMATICALLY_DUPLICATE_MATCHES') for fid,v in sorted(versions.items()) if len(v)>1],
        performance_status=performance_status,performance=performance,
        source_asset_audit_requested=assets_directory is not None,
        database_sha256_before=before,database_sha256_after=after,database_bytes_unchanged=before==after,
        concurrent_append_not_ruled_out=True,predictions_recomputed=False,results_fetched=False,
        calibration_fit=False,records_deleted=0,records_overwritten=0,production_changed=False)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ledger',required=True);p.add_argument('--assets-directory');p.add_argument('--output-directory',required=True)
    a=p.parse_args();report=audit_ledger(a.ledger,assets_directory=a.assets_directory)
    from hybrid_engine.boxes import publish_json
    root=local_path(a.output_directory);root.mkdir(parents=True,exist_ok=True)
    out=root/('nba-ledger-audit-'+digest(report)+'.json');publish_json(out,dict(payload=report,sha256=digest(report)))
    print(json.dumps(dict(path=str(out),snapshots_examined=report['snapshots_examined'],sqlite_integrity=report['sqlite_integrity'],
        rows_with_findings=sum(bool(r['findings']) for r in report['rows']),issues=report['issues'],database_bytes_unchanged=report['database_bytes_unchanged'])))


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps(dict(status='BLOCKED',error_type=type(exc).__name__,reason='ARCHIVE_AUDIT_NOT_COMPLETED_NO_RECORDS_CHANGED')))
        raise SystemExit(2)
