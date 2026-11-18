"""Opt-in native result collector for the existing verified production ledger.

Code only: no deploy or environment change enables this worker. The existing
release/volume/legacy-schema factory remains the authority for write access.
"""
import asyncio
import time

from hybrid_engine.nba_ledger_settlement import settle
from season_archive_collect import fetch_document


def collect(service, *, fetcher=fetch_document):
    if service is None or getattr(service,'configuration_error',None):
        return dict(status='ABSTAIN',reason='VERIFIED_RELEASE_SERVICE_NOT_CONFIGURED')
    ledger=getattr(service,'ledger',None)
    if ledger is None:
        factory=getattr(service,'ledger_factory',None)
        ledger=factory() if factory is not None else None
    if ledger is None:return dict(status='ABSTAIN',reason='EXISTING_VERIFIED_LEDGER_NOT_AVAILABLE')
    # Does not call analyze, construct a forecast, or change a snapshot.
    return settle(ledger,fetcher=fetcher)


async def run(app):
    while True:
        try:
            result=await asyncio.to_thread(collect,app.bot_data.get('verified_analysis_service'))
        except asyncio.CancelledError:raise
        except Exception as exc:
            result=dict(status='FAILED',error_type=type(exc).__name__)
        app.bot_data['last_verified_result_poll']=dict(result,completed_at_utc=int(time.time()))
        await asyncio.sleep(300)
