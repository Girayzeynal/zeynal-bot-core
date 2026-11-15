"""Settle isolated NBA forecasts from fresh native finals; never edit forecasts."""
from datetime import datetime, timedelta
import time
from zoneinfo import ZoneInfo

from core.team_identity import digest
from hybrid_engine.forward_nba_results import read_confirmed
from season_archive_collect import fetch_document
from season_archive_inventory import archive_catalog


def settle(ledger, *, fetcher=fetch_document):
    from ledger_reports import LedgerReports
    LedgerReports(ledger.path).read('NBA')  # Validate native outcomes/snapshot indices before any writes.
    records=read_confirmed(ledger.path)
    now=int(time.time())
    due=[r for r in records if r['snapshot']['fixture_start_utc']<now]
    days=set()
    for record in due:
        local=datetime.fromtimestamp(record['snapshot']['fixture_start_utc'],ZoneInfo('America/New_York')).date()
        days.update((local-timedelta(days=1),local,local+timedelta(days=1)))
    inserted=0; unavailable=[]
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
            for year in sorted({int(r['snapshot']['season'].split('/')[0]) for r in due}):
                bundle=archive_catalog(receipt['document'],provider='ESPN',season_start_year=year,
                    observed_at_utc=receipt['observed_at_utc'],ingested_at_utc=receipt['ingested_at_utc'],regular_season_filter=True)
                for g in bundle['payload']['fixtures']:
                    if g['completed'] and g['start_ts_utc']>=receipt['observed_at_utc']:
                        raise ValueError('SETTLEMENT_FINAL_BEFORE_TIPOFF')
                inserted+=ledger.reconcile(bundle,trusted_sha256=bundle['sha256'])
        except OSError:
            unavailable.append(day.isoformat())
    from ledger_reports import LedgerReports
    report=LedgerReports(ledger.path).read('NBA')
    return dict(checked=len(records),due=len(due),settled=inserted,pending=report.get('pending'),
                unavailable_dates=unavailable,status='SOURCE_INCOMPLETE' if unavailable else 'CHECKED')
