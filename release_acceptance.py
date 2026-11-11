"""Opt-in REAL provider smoke; Telegram transport is captured, never connected."""
import argparse
import asyncio
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from core.team_identity import digest
from live_analysis_ledger import LiveAnalysisLedger
from season_archive_collect import fetch_document,_local_root
from season_archive_inventory import validate_catalog
from verified_analysis import VerifiedAnalyzeService,project_scores,MODEL_DIGEST,MODEL_VERSION


def historical_preview(catalog,trusted_sha256,fixture_id):
    """Replay a real pre-tipoff source cut now, never backdate a live forecast."""
    c=validate_catalog(catalog,trusted_sha256=trusted_sha256)
    g=next(g for g in c['fixtures'] if g['canonical_id']==fixture_id)
    now=int(datetime.now(timezone.utc).timestamp());cutoff=g['start_ts_utc']-1
    if now<g['start_ts_utc']:raise ValueError('HISTORICAL_MODE_REQUIRES_STARTED_TARGET')
    if c['ingested_at_utc']>cutoff:raise ValueError('PRE_TIPOFF_SOURCE_SNAPSHOT_REQUIRED')
    rows=[v for v in c['fixtures'] if v['completed'] and v['periods'] is not None and v['start_ts_utc']<cutoff and v['canonical_id']!=fixture_id]
    prediction,history=project_scores(rows,g['home_team_id'],g['away_team_id'])
    return dict(record_type='BACKTEST_SIMULATION',evaluation_class='PIT_PROVEN_BACKTEST',
        league=g['league'],season=f"{g['season_start_year']}/{g['season_start_year']+1}",fixture_id=fixture_id,
        fixture_start_utc=g['start_ts_utc'],cutoff_utc=cutoff,generated_at_utc=now,
        source_observed_at_utc=c['observed_at_utc'],source_ingested_at_utc=c['ingested_at_utc'],
        source_catalog_sha256=trusted_sha256,model_version=MODEL_VERSION,model_digest=MODEL_DIGEST,
        prediction=prediction,history=history,actual=None,live_prediction_created=False,
        proof_scope='PINNED_LOCAL_SOURCE_CUT_NOT_PROVIDER_SIGNED_OR_LIVE_PREDICTION')


async def run_acceptance(directory):
    root=_local_root(directory)/('release-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8]);root.mkdir()
    receipts=[]
    def fetch(provider,url):
        r=fetch_document(provider,url)
        if r.get('document') is not None:
            (root/(r['document_sha256']+'.json')).write_text(json.dumps(r['document'],sort_keys=True))
        receipts.append({k:v for k,v in r.items() if k!='document'})
        return r
    ledger=LiveAnalysisLedger(root/'acceptance.sqlite')
    service=VerifiedAnalyzeService(ledger,fetcher=fetch,release_sha=os.getenv('ZEYNAL_RELEASE_SHA','UNKNOWN'))
    # This official source check remains explicit even when ESPN works.
    official=await asyncio.to_thread(fetch,'NBA_OFFICIAL','https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json')
    # Access alone is not a cross-check: fixture/season matching needs validation.
    blockers=['REAL_TELEGRAM_DELIVERY_NOT_TESTED','USERLAND_VOLUME_AND_PRODUCTION_LEDGER_NOT_AUDITED']
    blockers.append('NBA_OFFICIAL_CROSSCHECK_NOT_VERIFIED:'+official.get('status','UNKNOWN'))
    today=datetime.now(ZoneInfo('Europe/Istanbul')).date();nba=None
    for offset in range(3):
        day=(today+timedelta(days=offset)).isoformat()
        rows=await service.list_nba_games(day)
        future=[g for g in rows if g['start'].timestamp()>datetime.now(timezone.utc).timestamp()+3600]
        if future:nba=(day,future[0]);break
    if nba is None:raise ValueError('NO_VERIFIED_FUTURE_NBA_FIXTURE')
    euro=await asyncio.to_thread(fetch,'EUROLEAGUE_LIVE','https://api-live.euroleague.net/v2/competitions/E/seasons/E2026/games')
    if euro.get('status')!='DOCUMENT_RECEIVED':raise ValueError('EUROLEAGUE_PROVIDER_ACCESS_FAILED')
    future=sorted([g for g in euro['document']['data'] if not g['played'] and
        datetime.fromisoformat(g['utcDate'].replace('Z','+00:00')).timestamp()>datetime.now(timezone.utc).timestamp()+3600],key=lambda g:g['utcDate'])
    if not future:raise ValueError('NO_VERIFIED_FUTURE_EUROLEAGUE_FIXTURE')
    g=future[0];start=datetime.fromisoformat(g['utcDate'].replace('Z','+00:00'))
    participants=await asyncio.to_thread(service.identity.participants.load,'EUROLEAGUE',2026)
    names={t['provider_id']:t['official_name'] for t in participants['payload']['participants']}
    cases=[('NBA',nba[0],nba[1]['home'],nba[1]['away']),('EUROLEAGUE',start.astimezone(ZoneInfo('Europe/Istanbul')).date().isoformat(),names[g['local']['club']['code']],names[g['road']['club']['code']])]
    results=[];messages=[]
    with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'123456:LOCAL_CAPTURE_ONLY','API_SPORTS_KEY':''}):
        import main as app
    for case in cases:
        result=await service.analyze(*case)
        command='/analyze '+' '.join(case[:2])+' '+case[2]+' vs '+case[3]
        if result['status']=='ANALYSIS_OK':
            retry=await service.analyze(*case)
            if retry.get('snapshot')!=result['snapshot'] or retry['new_record']:raise ValueError('IDEMPOTENCY_FAILED')
        reply=AsyncMock();msg=SimpleNamespace(text=command,reply_text=reply)
        ctx=SimpleNamespace(application=SimpleNamespace(bot_data={'verified_analysis_service':service}))
        await app.analyze_command(SimpleNamespace(message=msg),ctx)
        messages.append(dict(command=command,text=reply.call_args.args[0],kwargs=reply.call_args.kwargs,transport='LOCAL_CAPTURE_NOT_TELEGRAM_API'))
        results.append(dict(command=command,result=result))
    from nba_command import nba_command
    reply=AsyncMock();msg=SimpleNamespace(reply_text=reply)
    ctx=SimpleNamespace(args=[],application=SimpleNamespace(bot_data={'nba_fixture_loader':service.list_nba_games}))
    await nba_command(SimpleNamespace(effective_message=msg),ctx)
    messages.append(dict(command='/nba',text=reply.call_args.args[0],transport='LOCAL_CAPTURE_NOT_TELEGRAM_API'))
    report=dict(created_at_utc=datetime.now(timezone.utc).isoformat(),cases=results,messages=messages,receipts=receipts,
        integrity=ledger.integrity(),production_database_accessed=False,telegram_api_delivery_verified=False,
        functional_checks_ok=all(r['result']['status']=='ANALYSIS_OK' for r in results),
        production_release_permitted=False,release_blockers=blockers)
    path=root/'report.json';path.write_text(json.dumps(report,indent=2));return path,report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--execute',action='store_true');p.add_argument('--output-dir')
    a=p.parse_args(argv)
    if not a.execute:print(json.dumps(dict(status='DRY_RUN_NO_NETWORK_OR_TELEGRAM',production_release_permitted=False)));return 0
    try:
        if not a.output_dir:raise ValueError('ISOLATED_LOCAL_OUTPUT_DIRECTORY_REQUIRED')
        path,report=asyncio.run(run_acceptance(a.output_dir))
        print(json.dumps(dict(path=str(path),functional_checks_ok=report['functional_checks_ok'],integrity=report['integrity'],
            production_release_permitted=False,blockers=report['release_blockers'])));return 0 if report['functional_checks_ok'] else 1
    except (ValueError,OSError,KeyError,TypeError) as exc:
        print(json.dumps(dict(status='ACCEPTANCE_NOT_CONFIRMED',reason=str(exc),production_release_permitted=False)));return 2


if __name__=='__main__':raise SystemExit(main())
