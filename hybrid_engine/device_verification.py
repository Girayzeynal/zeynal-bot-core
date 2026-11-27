"""Bounded read-only native quality + local Telegram journal verification.

No credentials, provider calls, polling, fitting, PREMATCH, settlement or promotion.
Local API evidence has no independent server signature and is not model accuracy.
"""
import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from core.team_identity import digest
from hybrid_engine.data import local_path
from hybrid_engine.quality_report import report as quality_report,comparison_summary
from hybrid_engine.telegram_evidence import evidence_report

MAX_EVENTS=20000
MAX_EVENT_BYTES=65536
MAX_TOTAL_BYTES=16*1024*1024
MAX_JOURNAL_BYTES=64*1024*1024
COMMANDS=('/start','/nba','/analyze','/accuracy','/compare','/test')


def file_sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for part in iter(lambda:f.read(65536),b''):h.update(part)
    return h.hexdigest()


def read_journal(path,*,asof_utc,expected_release=None):
    path=local_path(path)
    if not path.is_file():return dict(status='NOT_PRESENT',actual_telegram_delivery_verified=False,complete_command_suite_verified=False)
    for suffix in ('-wal','-shm'):
        side=path.with_name(path.name+suffix)
        if side.exists():local_path(side)
    if path.stat().st_size>MAX_JOURNAL_BYTES:
        return dict(status='NOT_VERIFIED_JOURNAL_SIZE_LIMIT',actual_telegram_delivery_verified=False,complete_command_suite_verified=False)
    before=file_sha(path)
    try:
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.2)) as db:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN');deadline=time.monotonic()+2
            db.set_progress_handler(lambda:int(time.monotonic()>deadline),1000)
            if db.execute('PRAGMA integrity_check(1)').fetchone()[0]!='ok':raise ValueError('INTEGRITY')
            rows=[];total=0
            for raw,pin in db.execute(f'''SELECT CASE WHEN length(CAST(payload AS BLOB))<={MAX_EVENT_BYTES}
                THEN payload END,sha256 FROM delivery_events ORDER BY rowid LIMIT {MAX_EVENTS+1}'''):
                if len(rows)>=MAX_EVENTS or raw is None:raise ValueError('EVENT_BUDGET')
                total+=len(raw.encode())
                if total>MAX_TOTAL_BYTES:raise ValueError('TOTAL_BUDGET')
                rows.append((raw,pin))
        events=[]
        for raw,pin in rows:
            event=json.loads(raw)
            if type(event) is not dict or digest(event)!=pin:raise ValueError('HASH')
            events.append(event)
        evidence=evidence_report(events,asof_utc=asof_utc)
        # Export known command names and counts only: no chat/bot/update/message
        # IDs, raw commands, native API bodies, URLs or paths in the summary.
        counts=Counter(r['command'] for r in evidence['api_verified'] if r['command'] in COMMANDS)
        excluded=Counter(reason for r in evidence['excluded'] for reason in r['reasons'])
        result=dict(status='LOCAL_JOURNAL_INSPECTED',events=len(events),
            read_snapshot_events_sha256=digest(events),
            accepted_command_counts={c:counts[c] for c in COMMANDS},
            complete_analysis_updates=len(evidence['complete_analysis_updates']),
            actual_telegram_delivery_verified=evidence['actual_telegram_delivery_verified'],
            complete_command_suite_verified=evidence['complete_command_suite_verified'],
            exclusions=dict(excluded),application_result_correctness_verified=False)
        if expected_release is not None:
            from hybrid_engine.accuracy_delivery import inspect_accuracy
            record=next((e for e in reversed(events) if e.get('kind')=='ACCURACY_ALL_DELIVERY'
                         and e.get('release_sha')==expected_release),None)
            linked=[e for e in events if record and e.get('update_id')==record['update_id']]
            command=next((e for e in linked if e.get('kind')=='COMMAND_RECEIVED'),None)
            try:
                result['latest_accuracy_all']=inspect_accuracy(record,command,
                    [e for e in linked if e.get('kind')=='DELIVERY_ACCEPTED'],
                    expected_release=expected_release,now=asof_utc)
            except (ValueError,KeyError,TypeError):
                result['latest_accuracy_all']=dict(status='INVALID_ACCURACY_RECEIPT')
    except (ValueError,KeyError,TypeError,OSError,sqlite3.Error):
        result=dict(status='NOT_VERIFIED_INVALID_OR_INCOMPLETE_JOURNAL',
            actual_telegram_delivery_verified=False,complete_command_suite_verified=False)
    result.update(journal_file_sha256=before,journal_bytes_unchanged=before==file_sha(path),
        concurrent_append_not_ruled_out=True,evidence_authority='LOCAL_HASHED_JOURNAL_NOT_INDEPENDENT_TELEGRAM_SIGNATURE')
    return result


def inspect(directory,*,expected_release=None):
    root=local_path(directory);now=int(time.time());ledger=root/'live-nba/nba-hybrid.sqlite'
    result=dict(format='READ_ONLY_DEVICE_VERIFICATION_V1',observed_at_utc=now,
        reader_source_sha256=file_sha(Path(__file__)),
        nba=dict(status='NOT_PRESENT'),running_process_identity='NOT_VERIFIED_USE_TEST_RUNTIME',
        acceptance='NO_GO',acceptance_scope='RESEARCH_EVIDENCE_REVIEW_NOT_FUNCTIONAL_ACTIVATION',
        features_disabled_by_this_review=False,automatic_promotion=False,production_changed=False,
        api_requests_made=0,predictions_recomputed=False,calibration_fit=False,results_ingested=False,
        records_deleted=0,records_overwritten=0)
    if ledger.is_file():
        try:
            full=quality_report(ledger,assets_directory=root/'live-nba/assets');a=full['archive_audit']
            verified=sum(not row['findings'] and (row.get('source_audit') or {}).get('snapshot_sha256')==row['snapshot_sha256'] and
                (row.get('source_audit') or {}).get('status')=='VERIFIED_WITH_LIMITATIONS' for row in a['rows'])
            result['nba']=dict(status=a['performance_status'],sqlite_integrity=a['sqlite_integrity'],
                database_bytes_unchanged=a['database_bytes_unchanged'],
                original_input_sources_verified=verified,
                all_original_input_sources_verified=bool(a['rows']) and verified==len(a['rows']),
                unique_fixtures=a['unique_fixtures'],native_audit_findings=dict(Counter(c for row in a['rows'] for c in row['findings'])),
                comparison=comparison_summary(full),
                quality_groups=(full.get('current_quality') or {}).get('groups',[]))
            # monitor groups contain only aggregate cohort IDs/metrics, not raw inputs.
        except (ValueError,KeyError,TypeError,OSError,sqlite3.Error):
            result['nba']=dict(status='NOT_VERIFIED_NATIVE_ARCHIVE_AUDIT_FAILED')
    result['telegram']=read_journal(root/'telegram-delivery.sqlite',asof_utc=now,expected_release=expected_release)
    result['remaining_checks']=[code for code,ok in (
        ('NATIVE_DEVICE_ARCHIVE',result['nba'].get('status')=='READ_ONLY_NATIVE_VERIFIED' and result['nba'].get('all_original_input_sources_verified')),
        ('REAL_TELEGRAM_COMMAND_SUITE',result['telegram'].get('complete_command_suite_verified')),
        ('RUNNING_MODEL_IDENTITY',False),('REGISTERED_FUTURE_MODEL_COMPARISON',False)) if not ok]
    result['status']='REVIEW_COMPLETED_WITH_GAPS'
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--data-directory',required=True)
    import re
    parser.add_argument('--release-sha',help='Full SHA for /accuracy all delivery verification')
    args=parser.parse_args()
    if args.release_sha is not None and not re.fullmatch(r'[0-9a-f]{40}',args.release_sha):
        parser.error('--release-sha requires a full lowercase commit SHA')
    try:value=inspect(args.data_directory,expected_release=args.release_sha)
    except (ValueError,OSError):value=dict(status='NOT_VERIFIED_ISOLATED_PATH_REQUIRED',production_changed=False)
    print(json.dumps(value,ensure_ascii=False,allow_nan=False))


if __name__=='__main__':main()
