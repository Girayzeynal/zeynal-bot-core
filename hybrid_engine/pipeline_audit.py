"""Read-only UserLAnd triage: archives, selected parameters and source blockers.

No provider calls, token output, fitting, prediction, deletion or database writes.
Disk evidence does not certify what an already running process has loaded.
"""
import argparse
from collections import Counter
from itertools import islice
import json
from pathlib import Path
import sqlite3
import time

from core.team_identity import digest
from hybrid_engine.data import local_path
from hybrid_engine.market_turkish import MESSAGES

KNOWN=set(MESSAGES)|{'RECEIVED','CURRENT_OBSERVATIONS_ONLY','PROVIDER_REPORTED_ERROR',
    'OFFICIAL_NEWS_TEXT_NOT_VERIFIED_MATCH_AVAILABILITY','OFFICIAL_REPORT_UNAVAILABLE_OR_UNVERIFIED',
    'MISSING_ABSENCE_CORROBORATION','SOURCE_OBSERVATIONS_STALE','SOURCE_COOLDOWN',
    'SOURCE_HTTP_ERROR','ABSENCE_REQUIRES_BOTH_SOURCE_OBSERVATIONS'}


def code(value):
    return value if value in KNOWN else 'UNRECOGNIZED_STATUS_NOT_EXPORTED'


def inventory(directory,pattern,*,maximum_files=None,maximum_bytes=None,include_segments=False):
    directory=local_path(directory)
    limit=65793 if include_segments else 4096
    legacy=list(islice(directory.glob(pattern),limit+1)) if directory.exists() else []
    segmented=(list(islice(directory.glob('segments/??/'+pattern),max(0,limit+1-len(legacy))))
               if include_segments and directory.exists() else [])
    files=legacy+segmented
    if len(files)>limit:return dict(status='SCAN_LIMIT_REACHED')
    size=sum(local_path(p).stat().st_size for p in files)
    full=(maximum_files is not None and len(files)>=maximum_files or
          maximum_bytes is not None and size>=maximum_bytes)
    result=dict(status='CAPACITY_REACHED' if full else 'AVAILABLE' if files else 'NO_RECORDS',
                files=len(files),bytes=size,maximum_files=maximum_files,maximum_bytes=maximum_bytes)
    if include_segments:
        result.update(legacy_files=len(legacy),segmented_files=len(segmented),
                      storage_layout='IMMUTABLE_LEGACY_PLUS_SHA_PREFIX_SEGMENTS',
                      legacy_at_capacity=len(legacy)>=256)
    records=[]
    # Bounded recent sample, not a complete source history or an active check.
    for path in sorted(files,key=lambda p:p.stat().st_mtime,reverse=True)[:24]:
        try:
            if path.stat().st_size>3*1024*1024:raise ValueError('SIZE')
            w=json.loads(path.read_text());p=w['payload']
            if digest(p)!=w['sha256'] or not path.stem.endswith('-'+w['sha256']):raise ValueError('PIN')
            if p.get('format')=='ISOLATED_PROVIDER_REVIEW_V1':
                records.append(dict(status=code(p['status']),evaluated_at_utc=p['evaluated_at_utc'],
                    providers={name:dict(status=code(row['status']),error_codes=[code(c) for c in row.get('error_codes',[])])
                    for name,row in p['providers'].items() if name in ('THE_ODDS_API','API_BASKETBALL')}))
            elif p.get('format')=='EUROPE_CURRENT_SOURCE_REVIEW_V1':
                details=p['details'];sources=details.get('sources',[])
                records.append(dict(section=p['section'],status=code(p['status']),observed_at_utc=p['observed_at_utc'],
                    source_statuses=[dict(status=code(s['status']),http_status=s.get('http_status')) for s in sources]))
        except (ValueError,KeyError,TypeError,OSError):
            result['invalid_recent_documents']=result.get('invalid_recent_documents',0)+1
    if records:result['recent_observations']=records
    result['observation_scope']='UP_TO_24_RECENT_FILES_NOT_LIVE_PROVIDER_VERIFICATION'
    return result


def audit_europe(directory,league):
    folder=local_path(directory)
    if not folder.is_dir():return dict(status='NOT_PRESENT')
    files=list(islice(folder.glob('*.json'),4097))
    if len(files)>4096:return dict(status='SCAN_LIMIT_REACHED')
    import hashlib
    def fingerprints():
        return {p.name:hashlib.sha256(local_path(p).read_bytes()).hexdigest() for p in folder.glob('*.json')}
    before=fingerprints()
    from hybrid_engine.europe_live import EuropeanRegistry,EuropeanService
    from types import SimpleNamespace
    # Read-only view: deliberately bypass the registry constructor's mkdir.
    registry=EuropeanRegistry.__new__(EuropeanRegistry);registry.root=folder;registry.league=league
    owner=SimpleNamespace(registry=registry,league=league)
    try:
        rows=registry.independent_records();settled=0;late=0;pending_started=0
        for row in rows:
            p=row['payload'];EuropeanService.pair(owner,p)
            if registry.outcome(p) is not None:settled+=1
            elif p['fixture']['start_ts_utc']<=int(time.time()):pending_started+=1
            late+=not row['publication']['eligible_for_prospective_audit']
        result=dict(status='VERIFIED_CURRENT_REGISTRY',unique_fixtures=len(rows),settled=settled,
            pending=len(rows)-settled,pending_started=pending_started,late_commits_excluded_from_live_metrics=late,
            scope='CURRENT_EUROPE_REGISTRY_NOT_ALL_LEGACY_STORES',normal_time_only=True)
    except (ValueError,KeyError,TypeError,OSError) as exc:
        result=dict(status='ARCHIVE_NOT_VERIFIED',error_type=type(exc).__name__)
    result['archive_bytes_unchanged']=before==fingerprints()
    result['concurrent_append_not_ruled_out']=True
    return result


def audit(directory,*,model_path=None,model_sha256=None,verify_archive=True):
    root=local_path(directory);now=int(time.time())
    result=dict(format='MODEL_DATA_PIPELINE_AUDIT_V1',observed_at_utc=now,
        route_policy=dict(main_scores='FROZEN_ORIGINAL_REPLAY_OR_PINNED_TEAM_MODEL',
            adaptive_candidates='SEPARATE_RESEARCH_NOT_AUTOMATICALLY_THE_MAIN_SCORE',automatic_promotion=False,
            market_updates_original_score=False,roster_button_updates_original_score=False,
            europe_roster_adapter='OFFICIAL_NEWS_TEXT_NOT_VERIFIED_PLAYER_STATUS_FEED'),
        api_requests_made=0,predictions_recomputed=False,online_training=False,
        records_deleted=0,records_overwritten=0,production_changed=False,
        running_process_verified=False,actual_telegram_delivery_verified=False)
    configs=[('provider-evidence','provider-*.json',None,None),
             ('europe-provider-evidence','provider-*.json',256,32*1024*1024),
             ('europe-data/sources','source-*.json',64,16*1024*1024),
             ('europe-data/reviews','review-*.json',256,16*1024*1024)]
    result['local_evidence']={name:inventory(root/name,pattern,maximum_files=files,maximum_bytes=size,
                                            include_segments=name=='provider-evidence')
                              for name,pattern,files,size in configs}
    result['europe_archives']={c:audit_europe(root/'europe'/c.lower(),c) for c in ('EUROLEAGUE','EUROCUP')}
    ledger=root/'live-nba/nba-hybrid.sqlite'
    if verify_archive and ledger.is_file():
        from hybrid_engine.archive_audit import audit_ledger
        try:
            a=audit_ledger(ledger,assets_directory=root/'live-nba/assets')
            profiles=[r['input_profile'] for r in a['rows'] if r.get('input_profile')]
            result['nba_archive']=dict(sqlite_integrity=a['sqlite_integrity'],snapshots=a['snapshots_examined'],
                unique_fixtures=a['unique_fixtures'],performance_status=a['performance_status'],
                findings=dict(Counter(c for r in a['rows'] for c in r['findings'])),issues=a['issues'],
                database_bytes_unchanged=a['database_bytes_unchanged'],concurrent_append_not_ruled_out=True,
                input_profiles=len(profiles),feature_usage=[p['feature_usage'] for p in profiles[:1]],
                archived_model_versions=dict(Counter(r.get('model_version','UNKNOWN') for r in a['rows'])))
        except (ValueError,KeyError,TypeError,OSError,sqlite3.Error) as exc:
            result['nba_archive']=dict(status='ARCHIVE_NOT_VERIFIED',error_type=type(exc).__name__)
    else:result['nba_archive']=dict(status='NOT_PRESENT' if not ledger.is_file() else 'NOT_REQUESTED')
    if model_path is not None:
        from hybrid_engine.live_nba import PreparedBayes
        try:
            model=PreparedBayes(model_path,trusted_sha256=model_sha256);p=model.payload['model']
            result['selected_nba_model']=dict(status='PIN_VERIFIED',sha256=model.sha256,
                fit_cutoff_utc=p['cutoff_utc'],fit_age_hours=(now-p['cutoff_utc'])/3600,
                training_games=len(p['training_ids']),player_features=len(p['players']),
                full_game_strength='FROZEN_ATTACK_DEFENSE_COEFFICIENTS')
        except (ValueError,KeyError,TypeError,OSError) as exc:
            result['selected_nba_model']=dict(status='MODEL_NOT_VERIFIED',error_type=type(exc).__name__)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-directory',required=True)
    parser.add_argument('--nba-model');parser.add_argument('--nba-model-sha')
    args=parser.parse_args()
    if bool(args.nba_model)!=bool(args.nba_model_sha):raise ValueError('MODEL_AND_PIN_REQUIRED')
    print(json.dumps(audit(args.data_directory,model_path=args.nba_model,model_sha256=args.nba_model_sha),ensure_ascii=False))


if __name__=='__main__':main()
