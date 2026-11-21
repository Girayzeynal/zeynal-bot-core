"""Explicit fresh official PDF links, never guessed filenames or latest claims."""
import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
import re
import time
from zoneinfo import ZoneInfo

from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import local_path
from hybrid_engine.nba_injury_source import official_nba_injury_report_reference

MAX_AGE=1800
FORMAT='EXPLICIT_OFFICIAL_NBA_PDF_LINK_V1'


def reference(url,now):
    ref=official_nba_injury_report_reference(url,retrieved_at_utc=now,prediction_utc=now)
    if now-ref['report_timestamp_utc']>MAX_AGE: raise ValueError('EXPLICIT_REPORT_TOO_OLD')
    return ref


def assert_report_title(extraction,ref):
    titles=extraction.get('report_titles',[])
    if len(titles)!=1: raise ValueError('EXPLICIT_REPORT_TITLE_NOT_VERIFIED')
    m=re.fullmatch(r'InjuryReport:(\d{2}/\d{2}/\d{2})(\d{2}:\d{2})(AM|PM)',titles[0])
    if not m: raise ValueError('EXPLICIT_REPORT_TITLE_NOT_VERIFIED')
    value=datetime.strptime(''.join(m.groups()),'%m/%d/%y%I:%M%p').replace(tzinfo=ZoneInfo('America/New_York'))
    if int(value.timestamp())!=ref['report_timestamp_utc']:
        raise ValueError('EXPLICIT_REPORT_TITLE_CLOCK_MISMATCH')


def read_entry(path,directory,now):
    root=local_path(directory); path=local_path(path)
    if path.parent!=root or path.stat().st_size>16384: raise ValueError('EXPLICIT_REPORT_ENTRY_BUDGET')
    w=json.loads(path.read_text()); p=w['payload']
    if digest(p)!=w['sha256'] or p['format']!=FORMAT or path.stem!='link-'+digest(dict(url=p['url'],pdf_sha256=p['pdf_sha256'])):
        raise ValueError('EXPLICIT_REPORT_ENTRY_PIN')
    if (any(type(p[k]) is not int for k in ('report_timestamp_utc','received_at_utc','first_archived_at_utc')) or
            not 0<p['report_timestamp_utc']<=p['received_at_utc']<=p['first_archived_at_utc']<=now or
            p['received_at_utc']-p['report_timestamp_utc']>MAX_AGE or p['latest_report_verified'] is not False):
        raise ValueError('EXPLICIT_REPORT_ENTRY_CLOCK')
    ref=official_nba_injury_report_reference(p['url'],retrieved_at_utc=p['received_at_utc'],prediction_utc=p['received_at_utc'])
    if ref['report_timestamp_utc']!=p['report_timestamp_utc']: raise ValueError('EXPLICIT_REPORT_ENTRY_CLOCK')
    assert_report_title(dict(report_titles=[p['report_title']]),ref)
    return p,w['sha256']


def select_link(directory,season,now):
    root=local_path(directory); selected=None; count=0; ambiguous=False
    match=re.fullmatch(r'(20[0-9]{2})/(20[0-9]{2})',season)
    if not match or int(match[2])!=int(match[1])+1: raise ValueError('EXPLICIT_REPORT_SEASON_REQUIRED')
    zone=ZoneInfo('America/New_York')
    start=int(datetime(int(match[1]),7,1,tzinfo=zone).timestamp())
    end=int(datetime(int(match[2]),7,1,tzinfo=zone).timestamp())
    for path in root.glob('link-*.json'):
        count+=1
        if count>1024: raise ValueError('EXPLICIT_REPORT_SCAN_BUDGET')
        p,pin=read_entry(path,root,now)
        if not start<=p['report_timestamp_utc']<end or now-p['report_timestamp_utc']>MAX_AGE: continue
        rank=(p['report_timestamp_utc'],p['first_archived_at_utc'])
        previous=None if selected is None else (selected[0]['report_timestamp_utc'],selected[0]['first_archived_at_utc'])
        if selected is None or rank>previous:
            selected=p,pin; ambiguous=False
        elif rank==previous and p['pdf_sha256']!=selected[0]['pdf_sha256']:
            ambiguous=True
    if ambiguous: raise ValueError('EXPLICIT_REPORT_AMBIGUOUS_CONTENT_VERSION')
    return selected


def import_link(url,directory,*,getter=None,extractor=None,clock=time.time):
    # Imports are explicit offline actions. Credentials and guesses are unnecessary.
    from hybrid_engine.current_roster import native_get,pdf_extract
    getter=getter or native_get; extractor=extractor or pdf_extract
    root=local_path(directory); now=int(clock()); ref=reference(url,now)
    receipt=getter(url,deadline=time.monotonic()+12)
    if receipt.get('status')!='RECEIVED': raise ValueError('EXPLICIT_REPORT_SOURCE_UNAVAILABLE')
    body=receipt['body']; pin=receipt['body_sha256']
    if (receipt['url']!=url or type(body) is not bytes or not body.startswith(b'%PDF-') or
            not 8<=len(body)<=8*1024*1024 or hashlib.sha256(body).hexdigest()!=pin or
            any(type(receipt[k]) is not int for k in ('started_at_utc','observed_at_utc')) or
            not ref['report_timestamp_utc']<=receipt['started_at_utc']<=receipt['observed_at_utc']<=int(clock())):
        raise ValueError('EXPLICIT_REPORT_RECEIPT_PIN_OR_CLOCK')
    reference(url,int(clock()))
    root.mkdir(parents=True,exist_ok=True)
    pdf=root/('pdf-'+pin+'.pdf')
    if pdf.exists():
        if pdf.is_symlink() or pdf.read_bytes()!=body: raise ValueError('EXPLICIT_REPORT_PDF_CONFLICT')
    else:
        import os
        with os.fdopen(os.open(pdf,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as f:
            f.write(body);f.flush();os.fsync(f.fileno())
    extraction=extractor(pdf,deadline=time.monotonic()+6)
    if extraction.get('status')!='PARSED_TABLE_ROWS_REQUIRE_ID_VERIFICATION':
        raise ValueError('EXPLICIT_REPORT_PARSER_UNAVAILABLE')
    if extraction.get('source_pdf_sha256')!=pin: raise ValueError('EXPLICIT_REPORT_EXTRACTION_PIN')
    assert_report_title(extraction,ref)
    path=root/('link-'+digest(dict(url=url,pdf_sha256=pin))+'.json')
    if path.exists():
        p,entry=read_entry(path,root,int(clock()))
        return dict(status='EXISTING_EXPLICIT_LINK',entry_sha256=entry,report_timestamp_utc=p['report_timestamp_utc'],
            first_archived_at_utc=p['first_archived_at_utc'],latest_report_verified=False,forecast_created=False)
    archived=int(clock()); reference(url,archived)
    p=dict(format=FORMAT,url=url,pdf_sha256=pin,report_timestamp_utc=ref['report_timestamp_utc'],
        received_at_utc=receipt['observed_at_utc'],first_archived_at_utc=archived,
        discovery_mode='USER_SUPPLIED_OFFICIAL_CDN_URL',latest_report_verified=False,
        report_title=extraction['report_titles'][0],production_enabled=False)
    publish_json(path,dict(payload=p,sha256=digest(p)))
    return dict(status='EXPLICIT_OFFICIAL_LINK_ARCHIVED',entry_sha256=digest(p),
        report_timestamp_utc=p['report_timestamp_utc'],first_archived_at_utc=archived,
        latest_report_verified=False,forecast_created=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True); parser.add_argument('--directory',required=True)
    args=parser.parse_args()
    try: report=import_link(args.url,args.directory)
    except (ValueError,KeyError,TypeError,OSError) as exc:
        codes={'EXPLICIT_REPORT_TOO_OLD','EXPLICIT_REPORT_SOURCE_UNAVAILABLE','EXPLICIT_REPORT_PARSER_UNAVAILABLE',
            'EXPLICIT_REPORT_TITLE_NOT_VERIFIED','EXPLICIT_REPORT_TITLE_CLOCK_MISMATCH'}
        report=dict(status='BLOCKED',reason=str(exc) if str(exc) in codes else 'EXPLICIT_REPORT_VALIDATION_FAILED',
            forecast_created=False,production_changed=False)
    report.update(pdf_dependency_available=importlib.util.find_spec('pdfplumber') is not None,
        production_changed=False,online_training=False)
    print(json.dumps(report,sort_keys=True))
    return 0 if report['status'] in ('EXPLICIT_OFFICIAL_LINK_ARCHIVED','EXISTING_EXPLICIT_LINK') else 2


if __name__=='__main__': raise SystemExit(main())
