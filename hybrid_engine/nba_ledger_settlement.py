"""Settle isolated NBA forecasts from fresh native finals; never edit forecasts."""
from datetime import datetime, timedelta
import time
from zoneinfo import ZoneInfo

from core.team_identity import digest
from hybrid_engine.confirmed_nba import read_confirmed_nba as read_confirmed
from season_archive_collect import fetch_document
from season_archive_inventory import archive_catalog


def settle(ledger, *, fetcher=fetch_document):
    from ledger_reports import LedgerReports
    initial=LedgerReports(ledger.path).read('NBA')  # Validate native outcomes/snapshot indices before any writes.
    records=read_confirmed(ledger.path)
    now=int(time.time())
    pending={(r['fixture_id'],r['snapshot_sha256']) for r in initial.get('forecasts',[]) if r['actual'] is None}
    due=[r for r in records if r['snapshot']['fixture_start_utc']<now and
         (r['snapshot']['fixture_id'],r['snapshot_sha256']) in pending]
    days=set()
    for record in due:
        local=datetime.fromtimestamp(record['snapshot']['fixture_start_utc'],ZoneInfo('America/New_York')).date()
        days.update((local-timedelta(days=1),local,local+timedelta(days=1)))
    inserted=0; unavailable=[];invalid=[];valid_days=0
    for day in sorted(days):
        url='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates='+day.strftime('%Y%m%d')+'&limit=1000'
        try:
            receipt=fetcher('ESPN',url)
            if receipt.get('status')!='DOCUMENT_RECEIVED':
                unavailable.append(day.isoformat());continue
            clock=int(time.time())
            if (receipt.get('provider')!='ESPN' or receipt.get('source_url')!=url or receipt.get('http_status')!=200 or
                digest(receipt['document'])!=receipt.get('document_sha256') or
                any(type(receipt.get(k)) is not int for k in ('observed_at_utc','ingested_at_utc')) or
                not 0<receipt['observed_at_utc']<=receipt['ingested_at_utc']<=clock or clock-receipt['observed_at_utc']>300):
                raise ValueError('SETTLEMENT_NATIVE_RECEIPT_REQUIRED')
            # Parse every season separately; regular-season/native identity checks
            # remain authoritative. A malformed source is not an empty success.
            events=receipt['document']['events']
            if any(type(e.get('season',{}).get('year')) is not int or type(e.get('season',{}).get('type')) is not int for e in events):
                raise ValueError('SETTLEMENT_NATIVE_SEASON_METADATA_REQUIRED')
            for year in sorted({int(r['snapshot']['season'].split('/')[0]) for r in due}):
                # One ledger may retain previous seasons. Never parse a valid
                # 2027 native event as 2026, or let that mismatch starve all finals.
                native=dict(receipt['document'],events=[e for e in events if e['season']['year']==year+1])
                if not native['events']:continue
                bundle=archive_catalog(native,provider='ESPN',season_start_year=year,
                    observed_at_utc=receipt['observed_at_utc'],ingested_at_utc=receipt['ingested_at_utc'],regular_season_filter=True)
                for g in bundle['payload']['fixtures']:
                    if g['completed'] and g['start_ts_utc']>=receipt['observed_at_utc']:
                        raise ValueError('SETTLEMENT_FINAL_BEFORE_TIPOFF')
                inserted+=ledger.reconcile(bundle,trusted_sha256=bundle['sha256'])
            valid_days+=1
        except OSError:
            unavailable.append(day.isoformat())
        except (ValueError,KeyError,TypeError) as exc:
            # A bad day's native document remains rejected, while another day
            # can settle independently. Database errors still stop the worker.
            invalid.append(dict(date=day.isoformat(),error_type=type(exc).__name__))
    if invalid and not valid_days:
        raise ValueError('SETTLEMENT_ALL_NATIVE_DATES_INVALID')
    from ledger_reports import LedgerReports
    report=LedgerReports(ledger.path).read('NBA')
    return dict(checked=len(records),due=len(due),settled=inserted,pending=report.get('pending'),
                unavailable_dates=unavailable,invalid_dates=invalid,
                status='SOURCE_INCOMPLETE' if unavailable or invalid else 'CHECKED')
