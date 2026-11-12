"""Discover all provider calendar days, not a sample of hand-picked games.

Public opt-in research collection. Full independent season completeness and PIT
availability are separate claims, neither inferred from successful HTTP reads.
"""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import tempfile
import time
from zoneinfo import ZoneInfo

from core.team_identity import digest
from historical_research import historical_rows
from season_archive_collect import fetch_document,_local_root
from season_archive_inventory import archive_catalog


def nba_calendar_days(document,year,asof_utc):
    try:
        if type(year) is not int or not 2000<=year<=2100 or type(asof_utc) is not int or not 0<asof_utc<=int(time.time()):
            raise ValueError('VALID_SEASON_AND_ASOF_REQUIRED')
        leagues=document['leagues']
        if len(leagues)!=1: raise ValueError('SINGLE_NBA_CALENDAR_REQUIRED')
        node=leagues[0]
        if (node['slug']!='nba' or type(node['season']['year']) is not int or node['season']['year']!=year+1 or
                node['calendarType']!='day' or node['calendarIsWhitelist'] is not True):
            raise ValueError('NBA_SEASON_CALENDAR_NOT_VERIFIED')
        dates=node['calendar']
        if type(dates) is not list or not 1<=len(dates)<=400: raise ValueError('BOUNDED_FULL_CALENDAR_REQUIRED')
        result=set();today=datetime.fromtimestamp(asof_utc,ZoneInfo('America/New_York')).date()
        for raw in dates:
            d=datetime.fromisoformat(raw.replace('Z','+00:00'))
            if d.tzinfo is None or not datetime(year,7,1,tzinfo=timezone.utc)<=d<datetime(year+1,7,1,tzinfo=timezone.utc):
                raise ValueError('CALENDAR_DATE_OUTSIDE_SEASON')
            if d.date()<=today: result.add(d.strftime('%Y%m%d'))
        return sorted(result)
    except (KeyError,TypeError,AttributeError) as exc: raise ValueError('MALFORMED_NBA_CALENDAR') from exc


def collect_season_history(*,year=2026,seed_date='20261110',live=False,fetcher=fetch_document):
    if type(live) is not bool or type(year) is not int or not 2000<=year<=2100: raise ValueError('INVALID_HISTORY_COLLECTION_PLAN')
    seed=datetime.strptime(seed_date,'%Y%m%d').replace(tzinfo=timezone.utc)
    if seed.strftime('%Y%m%d')!=seed_date or not datetime(year,7,1,tzinfo=timezone.utc)<=seed<datetime(year+1,7,1,tzinfo=timezone.utc):
        raise ValueError('SEED_DATE_OUTSIDE_SEASON')
    prefix='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates='
    seed_url=prefix+seed_date+'&limit=1000'
    euro_url=f'https://api-live.euroleague.net/v2/competitions/E/seasons/E{year}/games'
    if not live: return dict(status='DRY_RUN_NO_NETWORK',record_type='HISTORICAL_DATA',seed_url=seed_url,euroleague_url=euro_url,
        network_requests=0,prospective_predictions_created=0)
    receipts=[];catalogs={};blocked=set();asof=int(time.time());calendar=None;planned=[]
    def load(provider,url):
        if provider in blocked: return None
        try: r=fetcher(provider,url)
        except OSError: r=dict(status='SOURCE_NETWORK_ERROR')
        if type(r) is not dict:r=dict(status='SOURCE_RECEIPT_INVALID')
        summary={k:v for k,v in r.items() if k!='document'}
        summary.update(provider=provider,source_url=url);receipts.append(summary)
        if r.get('status') in ('SOURCE_ACCESS_DENIED','SOURCE_RATE_LIMITED'):blocked.add(provider)
        if r.get('status')!='DOCUMENT_RECEIVED':return None
        if r.get('provider')!=provider or r.get('source_url')!=url or r.get('http_status')!=200 or digest(r['document'])!=r.get('document_sha256'):
            summary['validation_error']='SOURCE_BINDING_OR_DIGEST_MISMATCH';return None
        return r
    def catalog(r):
        if r is None:return
        try:
            b=archive_catalog(r['document'],provider=r['provider'],observed_at_utc=r['observed_at_utc'],
                ingested_at_utc=r['ingested_at_utc'],season_start_year=year,regular_season_filter=True)
            catalogs[b['sha256']]=b;receipts[-1]['catalog_sha256']=b['sha256']
        except (ValueError,KeyError,TypeError) as exc:
            receipts[-1]['validation_error']=str(exc) if isinstance(exc,ValueError) else 'MALFORMED_SOURCE'
    seed_receipt=load('ESPN',seed_url)
    if seed_receipt:
        try: calendar=nba_calendar_days(seed_receipt['document'],year,asof)
        except ValueError as exc:receipts[-1]['calendar_error']=str(exc)
        catalog(seed_receipt)
    if calendar is not None:
        planned=calendar
        for day in calendar:
            if day!=seed_date and 'ESPN' not in blocked:catalog(load('ESPN',prefix+day+'&limit=1000'))
    catalog(load('EUROLEAGUE_LIVE',euro_url))
    cohort=historical_rows([(b,pin) for pin,b in catalogs.items()]);summary={}
    for league in ('NBA','EuroLeague'):
        games=[v[0] for v in cohort if v[0]['league']==league]
        league_receipts=[r for r in receipts if (r['provider']=='ESPN')==(league=='NBA')]
        successful=sum('catalog_sha256' in r for r in league_receipts)
        completed=None if not successful else len(games)
        summary[league]=dict(known_completed_games=completed,known_with_periods=None if completed is None else sum(g['periods'] is not None for g in games),
            source_documents=successful,failed_documents=sum('catalog_sha256' not in r for r in league_receipts),
            normalized_partial_team_statistics_games=sum(g['team_statistics'] is not None for g in games),
            incomplete_fields=['complete_team_statistics','player_statistics','pace','efficiency','lineups','rotation','injuries'],
            additional_fields_status='PARTIAL_NORMALIZATION_NATIVE_DOCUMENTS_RETAINED',
            provider_calendar_dates=len(calendar) if league=='NBA' and calendar is not None else None,
            provider_calendar_days_checked=successful if league=='NBA' else None,
            provider_calendar_scan_complete=league=='NBA' and calendar is not None and len(league_receipts)==len(set(calendar+[seed_date])) and successful==len(league_receipts),
            independently_complete_season=False)
    p=dict(format='HISTORICAL_SEASON_DISCOVERY_V1',record_type='HISTORICAL_DATA',season=f'{year}/{year+1}',
        created_at_utc=int(time.time()),calendar_asof_utc=asof,nba_calendar_dates=planned,receipts=receipts,catalogs=catalogs,
        leagues=summary,request_attempts=len(receipts),source_permission='NOT_ESTABLISHED',
        point_in_time_eligibility='EVALUATE_PER_TARGET_CUTOFF_NOT_GLOBALLY_DISCARDED',
        prospective_predictions_created=0,production_database_accessed=False)
    return dict(payload=p,sha256=digest(p))


def publish_history(directory,bundle):
    """Atomic insert-only local archive, including native source documents."""
    root=_local_root(directory)
    if (type(bundle) is not dict or set(bundle)!={'payload','sha256'} or digest(bundle['payload'])!=bundle['sha256']):
        raise ValueError('HISTORY_ARCHIVE_PIN_MISMATCH')
    p=bundle['payload']
    if (p.get('format')!='HISTORICAL_SEASON_DISCOVERY_V1' or p.get('record_type')!='HISTORICAL_DATA' or
            p.get('prospective_predictions_created')!=0 or p.get('production_database_accessed') is not False or
            type(p.get('created_at_utc')) is not int or not 0<p['created_at_utc']<=int(time.time())):
        raise ValueError('HISTORY_ARCHIVE_KIND_OR_CLOCK_INVALID')
    rows=historical_rows([(v,k) for k,v in p['catalogs'].items()])
    for league in ('NBA','EuroLeague'):
        count=sum(v[0]['league']==league for v in rows)
        known=p['leagues'][league]['known_completed_games']
        if known is not None and known!=count: raise ValueError('HISTORY_CENSUS_MISMATCH')
    target=root/('historical-data-'+bundle['sha256']+'.json')
    body=(json.dumps(bundle,sort_keys=True,allow_nan=False)+'\n').encode()
    if target.is_symlink():raise ValueError('HISTORY_TARGET_SYMLINK_REFUSED')
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=root,prefix='.history-',delete=False) as stream:
            temporary=Path(stream.name);stream.write(body);stream.flush();os.fsync(stream.fileno())
        try:os.link(temporary,target)
        except FileExistsError:
            if target.is_symlink() or target.read_bytes()!=body:raise ValueError('HISTORY_ARCHIVE_CONTENT_CONFLICT')
            return dict(path=str(target),sha256=bundle['sha256'],created=False)
        fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
        return dict(path=str(target),sha256=bundle['sha256'],created=True)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--year',type=int,default=2026)
    p.add_argument('--seed-date',default='20261110');p.add_argument('--live',action='store_true')
    p.add_argument('--output-dir')
    args=p.parse_args(argv)
    try:
        if args.live:
            if not args.output_dir:raise ValueError('LIVE_COLLECTION_REQUIRES_LOCAL_OUTPUT_DIRECTORY')
            _local_root(args.output_dir)
        result=collect_season_history(year=args.year,seed_date=args.seed_date,live=args.live)
        if not args.live:print(json.dumps(result,sort_keys=True));return 0
        publication=publish_history(args.output_dir,result)
        complete=(result['payload']['leagues']['NBA']['provider_calendar_scan_complete'] and
            result['payload']['leagues']['EuroLeague']['source_documents']==1 and
            result['payload']['leagues']['EuroLeague']['failed_documents']==0)
        print(json.dumps(dict(record_type='HISTORICAL_DATA',leagues=result['payload']['leagues'],publication=publication,
            status='PROVIDER_SCAN_COLLECTED' if complete else 'PARTIAL_OR_BLOCKED',
            prospective_predictions_created=0),sort_keys=True));return 0 if complete else 1
    except (ValueError,OSError) as exc:
        print(json.dumps(dict(status='HISTORY_COLLECTION_NOT_CONFIRMED',reason=str(exc))));return 2


if __name__=='__main__':raise SystemExit(main())
