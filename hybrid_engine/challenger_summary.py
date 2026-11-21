"""Read-only challenger report presentation; registered predictor pins stay intact.

The phase94 predictor/review/forward modules are protocol-pinned. Their legacy
CLI read coverage at the wrong level. Correct presentation here without changing
any pinned bytes, inference, stored report, protocol, or first publication.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from core.team_identity import digest

MAX_BYTES = 16*1024*1024


def checked_path(value):
    p=Path(value).absolute()
    if p==Path('/data') or Path('/data') in p.parents or p.resolve()!=p:
        raise ValueError('ISOLATED_REPORT_PATH_REQUIRED')
    return p


def read_report(path, directory):
    root=checked_path(directory); path=checked_path(path)
    if path.parent!=root or not re.fullmatch(r'challengers-[a-f0-9]{64}\.json',path.name):
        raise ValueError('CHALLENGER_REPORT_PATH_OR_NAME')
    if not path.is_file() or path.stat().st_size>MAX_BYTES:
        raise ValueError('CHALLENGER_REPORT_SIZE_OR_MISSING')
    with path.open('rb') as stream:
        raw=stream.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES: raise ValueError('CHALLENGER_REPORT_SIZE_OR_MISSING')
    w=json.loads(raw); p=w['payload']
    if (w['sha256']!=digest(p) or path.stem!='challengers-'+w['sha256'] or
            p['format']!='SAME_INPUT_OFFLINE_CHALLENGERS_V1'):
        raise ValueError('CHALLENGER_REPORT_PIN_OR_FORMAT')
    if (p.get('predictions_replaced') is not False or p.get('prematch_records_created')!=0 or
            p.get('production_changed') is not False or p.get('calibration_fit') is not False):
        raise ValueError('CHALLENGER_REPORT_SCOPE')
    return p,w['sha256']


def latest_report(directory):
    root=checked_path(directory)
    if not root.is_dir(): raise ValueError('EXISTING_CHALLENGER_REPORT_DIRECTORY_REQUIRED')
    paths=[]
    for path in root.glob('challengers-*.json'):
        paths.append(path)
        if len(paths)>1024: raise ValueError('CHALLENGER_REPORT_SCAN_BUDGET')
    if not paths: raise ValueError('EXISTING_CHALLENGER_REPORT_REQUIRED')
    # Most recently written report, never best-performing report. Invalid latest
    # data fails closed rather than silently selecting an older favorable result.
    return max(paths,key=lambda p:(p.stat().st_mtime_ns,p.name))


def summarize(payload, path, sha256):
    groups=[]
    for group in payload['groups']:
        models={}
        for name,m in group['models'].items():
            coverage=m.get('coverage',{}).get('markets',{}).get('TOTAL')
            models[name]=dict(n=m['n'],team_scores=m.get('team_scores'),total=m.get('total'),
                winner=m.get('winner',{}).get('correct'),total_coverage=coverage,
                total_coverage_status='DESCRIPTIVE_NOT_CALIBRATION_PROOF' if coverage else
                    ('NO_SETTLED_SUPPORTED_FORECASTS' if not m['n'] else 'NO_SUPPORTED_TOTAL_INTERVALS'),
                calibration_status=m.get('calibration_status','NOT_CALIBRATED'),confidence_index=None)
        groups.append(dict(cohort=group['cohort'],n=group['n'],day_clusters=group['day_clusters'],
            models=models,abstentions=group['abstentions']))
    return dict(path=str(path),report_sha256=sha256,status=payload['status'],
        reviewed=payload['reviewed'],blocked=payload['blocked'],remaining=payload['remaining'],
        database_and_wal_unchanged=payload['database_and_wal_unchanged'],groups=groups,
        acceptance=payload['acceptance']['decision'],actual_telegram_delivery_verified=False,
        production_changed=False,view_only=True,forecasts_recomputed_by_view=False)


def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    try:
        child_code=0
        child_mode=bool(argv and argv[0]=='--run-review')
        if child_mode:
            # Keep the original offline CLI, argument validation and exit status.
            # This child is NOT a Telegram request. The viewer edits no source
            # or protocol and does not alter the report produced by the child.
            child=subprocess.run([sys.executable,'-B','-m','hybrid_engine.challenger_review',*argv[1:]],
                stdout=subprocess.PIPE,text=True,timeout=600,check=False)
            child_code=child.returncode
            if len(child.stdout)>1024*1024: raise ValueError('CHALLENGER_CLI_OUTPUT_BUDGET')
            old=json.loads(child.stdout)
            if 'path' not in old:
                print(json.dumps(old,sort_keys=True,allow_nan=False));return child_code or 2
            path=checked_path(old['path']);directory=path.parent
        else:
            parser=argparse.ArgumentParser(description=__doc__)
            parser.add_argument('--directory',required=True)
            parser.add_argument('--report',help='Optional exact saved report path; default most recently written file')
            a=parser.parse_args(argv);directory=checked_path(a.directory)
            path=checked_path(a.report) if a.report else latest_report(directory)
        payload,pin=read_report(path,directory)
        output=summarize(payload,path,pin)
        output.update(view_only=not child_mode,review_executed_by_child=child_mode)
        print(json.dumps(output,sort_keys=True,allow_nan=False))
        return child_code or (0 if payload['status']=='REVIEW_COMPLETE' else 2)
    except (ValueError,KeyError,TypeError,OSError,RuntimeError,subprocess.SubprocessError) as exc:
        print(json.dumps(dict(status='BLOCKED',error_type=type(exc).__name__,
            reason='CHALLENGER_SUMMARY_UNAVAILABLE_NO_RECORDS_CHANGED',production_changed=False)))
        return 2


if __name__=='__main__':raise SystemExit(main())
