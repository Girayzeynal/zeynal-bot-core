"""Settle isolated NBA live forecasts from ESPN final scoreboards; no forecast edits."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from hybrid_engine.forward_nba_results import read_confirmed
from season_archive_collect import fetch_document
from season_archive_inventory import archive_catalog


def settle(ledger, *, fetcher=fetch_document):
    records=read_confirmed(ledger.path)
    if not records:
        return dict(checked=0,settled=0,pending=0)
    days=set()
    for record in records:
        p=record['snapshot']
        local=datetime.fromtimestamp(p['fixture_start_utc'],ZoneInfo('America/New_York')).date()
        days.update((local-timedelta(days=1),local,local+timedelta(days=1)))
    inserted=0
    for day in sorted(days):
        url='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates='+day.strftime('%Y%m%d')+'&limit=1000'
        receipt=fetcher('ESPN',url)
        if receipt.get('status')!='DOCUMENT_RECEIVED':
            continue
        raw=receipt['document']
        # The scoreboard can include non-regular-season events. Preserve the
        # catalog's strict native identity and regular-season filter.
        for year in sorted({int(r['snapshot']['season'].split('/')[0]) for r in records}):
            try:
                bundle=archive_catalog(raw,provider='ESPN',season_start_year=year,
                    observed_at_utc=receipt['observed_at_utc'],
                    ingested_at_utc=receipt['ingested_at_utc'],regular_season_filter=True)
            except ValueError:
                continue
            inserted+=ledger.reconcile(bundle,trusted_sha256=bundle['sha256'])
    from ledger_reports import LedgerReports
    report=LedgerReports(ledger.path).read('NBA')
    return dict(checked=len(records),settled=inserted,pending=report.get('pending'))
