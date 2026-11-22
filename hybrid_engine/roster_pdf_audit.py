"""Offline, read-only NBA official injury PDF archive diagnostics.

This is strictly a forensic parsing audit of a previously imported NBA CDN
PDF. Historical source observations are NOT new prospective pregame evidence.
No network access, future-score creation, athlete availability inference,
online training or first-forecast mutation is allowed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import time

from hybrid_engine.official_report_link import read_entry


def audit(directory, matchup, game_date, *, clock=time.time, extractor=None):
    if re.fullmatch(r'[A-Z]{2,4}@[A-Z]{2,4}', matchup) is None:
        raise ValueError('OFFLINE_PDF_MATCHUP_REQUIRED')
    if not re.fullmatch(r'20[0-9]{2}-[0-9]{2}-[0-9]{2}', game_date):
        raise ValueError('OFFLINE_PDF_DATE_REQUIRED')
    day=datetime.strptime(game_date,'%Y-%m-%d').strftime('%m/%d/%Y')
    root=Path(directory).expanduser().absolute()
    now=int(clock())
    if root.is_symlink() or not root.is_dir():
        raise ValueError('OFFLINE_PDF_ARCHIVE_UNAVAILABLE')
    entries=list(root.glob('link-*.json'))
    if len(entries)>128:
        raise ValueError('OFFLINE_PDF_ARCHIVE_BUDGET')
    latest=None
    for path in entries:
        if path.is_symlink():raise ValueError('OFFLINE_PDF_LINK_SYMLINK_REFUSED')
        info,pin=read_entry(path,root,now)
        if latest is None or (info['report_timestamp_utc'],info['first_archived_at_utc'],pin) > (
                latest[0]['report_timestamp_utc'],latest[0]['first_archived_at_utc'],latest[1]):
            latest=(info,pin)
    base=dict(format='READ_ONLY_OFFICIAL_NBA_PDF_ARCHIVE_AUDIT_V1',
              matchup=matchup,game_date=game_date,
              network_requests_made=0,new_forecast_created=False,
              original_forecasts_changed=False,player_model_activated=False,
              prospective_packet_validated=False,
              historical_document_only=True)
    if latest is None:
        return dict(base,status='NO_ARCHIVED_OFFICIAL_PDF')
    info,pin=latest
    document=root/('pdf-'+info['pdf_sha256']+'.pdf')
    if (document.is_symlink() or not document.is_file() or
            not 8<=document.stat().st_size<=8*1024*1024 or
            hashlib.sha256(document.read_bytes()).hexdigest()!=info['pdf_sha256']):
        raise ValueError('OFFLINE_PDF_CONTENT_PIN_FAILED')
    if extractor is None:
        from hybrid_engine.current_roster import pdf_extract
        extractor=pdf_extract
    extraction=extractor(document,deadline=time.monotonic()+10)
    if not isinstance(extraction,dict):
        raise ValueError('OFFLINE_PDF_EXTRACTION_INVALID')
    details=dict(base,report_timestamp_utc=info['report_timestamp_utc'],
                 archived_at_utc=info['first_archived_at_utc'],
                 pdf_sha256=info['pdf_sha256'],link_entry_sha256=pin,
                 pdf_age_seconds=now-info['report_timestamp_utc'],
                 source_fresh_for_new_pregame_packet=False,
                 extraction_status=extraction.get('status'))
    if extraction.get('status')!='PARSED_TABLE_ROWS_REQUIRE_ID_VERIFICATION':
        return dict(details,status='OFFLINE_PDF_PARSE_INCOMPLETE',matchup_rows=0)
    from core.team_identity import digest
    rows=extraction.get('rows')
    if (not isinstance(rows,list) or len(rows)>500 or
            extraction.get('source_pdf_sha256')!=info['pdf_sha256'] or
            digest(rows)!=extraction.get('rows_sha256')):
        raise ValueError('OFFLINE_PDF_EXTRACTED_ROWS_PIN_FAILED')
    seen=sorted({r.get('matchup') for r in rows if isinstance(r,dict) and
                 isinstance(r.get('matchup'),str) and
                 re.fullmatch(r'[A-Z]{2,4}@[A-Z]{2,4}',r['matchup'])})[:40]
    matching=[r for r in rows if isinstance(r,dict) and
              r.get('matchup')==matchup and r.get('game_date')==day]
    by_team=dict(sorted(Counter(str(r.get('team',''))[:100] for r in matching).items()))
    clocks=sorted({str(r.get('game_time',''))[:24] for r in matching})
    return dict(details,status='OFFLINE_PDF_MATCHUP_ROWS_OBSERVED' if matching else
                'OFFLINE_PDF_NO_MATCHING_ROWS',parsed_rows=len(rows),
                matchups_seen=seen,matchup_rows=len(matching),
                matchup_rows_by_team=by_team,matchup_clocks=clocks)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory',required=True)
    p.add_argument('--matchup',required=True)
    p.add_argument('--game-date',required=True)
    args=p.parse_args()
    try:
        report=audit(args.directory,args.matchup,args.game_date)
    except (ValueError,OSError,KeyError,TypeError) as exc:
        valid={'OFFLINE_PDF_MATCHUP_REQUIRED','OFFLINE_PDF_DATE_REQUIRED',
               'OFFLINE_PDF_ARCHIVE_UNAVAILABLE','OFFLINE_PDF_ARCHIVE_BUDGET',
               'OFFLINE_PDF_LINK_SYMLINK_REFUSED','OFFLINE_PDF_CONTENT_PIN_FAILED',
               'OFFLINE_PDF_EXTRACTION_INVALID','OFFLINE_PDF_EXTRACTED_ROWS_PIN_FAILED'}
        report=dict(format='READ_ONLY_OFFICIAL_NBA_PDF_ARCHIVE_AUDIT_V1',
                    status='BLOCKED',reason=str(exc) if str(exc) in valid else
                    'OFFLINE_PDF_UNVERIFIED',network_requests_made=0,
                    original_forecasts_changed=False,new_forecast_created=False,
                    player_model_activated=False)
    print(json.dumps(report,sort_keys=True))
    return 0 if report['status']=='OFFLINE_PDF_MATCHUP_ROWS_OBSERVED' else 2


if __name__=='__main__':
    raise SystemExit(main())
