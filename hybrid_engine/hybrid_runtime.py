"""Actual frozen hybrid inference + all four PTB commands, using loopback HTTP only."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import time
from unittest.mock import patch


async def run(fixture_path,repetitions=20):
    from concurrent.futures import ThreadPoolExecutor
    asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=1,thread_name_prefix='hybrid-test'))
    import numpy as np
    from aiohttp import web,ClientSession
    from telegram.ext import Application
    from hybrid_engine.frozen_archive import FrozenArchive
    from hybrid_engine.test_bot import AuditedRequest,install_isolated_services
    from telegram_delivery import DeliveryJournal
    from tests.test_release_integration import nba_fetcher

    archive_path=Path(__file__).parent.parent/'docs/prospective/euroleague-20261112'
    originals={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in archive_path.iterdir()}
    archive=FrozenArchive(archive_path);records=sorted(archive.records.values(),key=lambda r:r['fixture']['start_ts_utc'])
    def command(r):
        g=r['fixture'];return '/analyze EUROLEAGUE 2026-11-12 '+g['home_name']+' vs '+g['away_name']
    commands=['/nba 2026-11-11']+[command(records[0])]*repetitions+[command(r) for r in records[1:]]+['/accuracy EUROLEAGUE','/compare EUROLEAGUE E2026_103']
    updates=[dict(update_id=i+1,message=dict(message_id=i+1,date=int(time.time()),chat=dict(id=17,type='private'),
        **{'from':dict(id=23,is_bot=False,first_name='Synthetic audit')},text=c,
        entities=[dict(type='bot_command',offset=0,length=len(c.split()[0]))])) for i,c in enumerate(commands)]
    updates.insert(0,dict(update_id=0,message=dict(message_id=999,date=int(time.time()),chat=dict(id=999,type='private'),
        **{'from':dict(id=999,is_bot=False,first_name='Unauthorized synthetic')},text='/accuracy',entities=[dict(type='bot_command',offset=0,length=9)])))
    received=[];polls=0;latencies=[];last=time.perf_counter()
    async def api(request):
        nonlocal polls,last
        name=request.path.rsplit('/',1)[-1]
        if name=='getMe':result=dict(id=123456,is_bot=True,first_name='Synthetic',username='zeynal_test_bot')
        elif name=='getUpdates':
            polls+=1;result=updates[:] if polls==1 else []
            if polls>1:await asyncio.sleep(.05)
        elif name=='sendMessage':
            p=dict(await request.post());now=time.perf_counter();latencies.append(now-last);last=now
            received.append(p['text']);result=dict(message_id=1000+len(received),date=int(time.time()),chat=dict(id=17,type='private'),text=p['text'])
        else:result=True
        return web.json_response(dict(ok=True,result=result))
    http=web.Application();http.router.add_route('*','/{path:.*}',api);runner=web.AppRunner(http);await runner.setup()
    site=web.TCPSite(runner,'127.0.0.1',0);await site.start();port=site._server.sockets[0].getsockname()[1]
    root=Path.cwd();journal=DeliveryJournal(root/'telegram-delivery.sqlite')
    os.environ['TELEGRAM_BOT_TOKEN']='123456:SYNTHETIC_LOCAL_ONLY';os.environ['API_SPORTS_KEY']=''
    os.environ['PORT']='0';os.environ['PREDICTION_LEDGER_DB']=str(root/'unused-live.sqlite')
    import main
    class LocalApplication:
        @staticmethod
        def builder():return Application.builder().base_url(f'http://127.0.0.1:{port}/bot').base_file_url(f'http://127.0.0.1:{port}/file/bot').request(AuditedRequest(journal))
    with patch.object(main,'Application',LocalApplication):app=main.build_app()
    main.PORT=0
    native=nba_fetcher()
    def synthetic_transport(provider,url):
        r=native(provider,url);r['observed_at_utc']=int(time.time());r['ingested_at_utc']=int(time.time());return r
    _,results=install_isolated_services(app,archive,root,chat_id=17,transport=synthetic_transport)
    resident=app.bot_data['resource_cache_resident']=main.production_service()
    fixture=json.loads(Path(fixture_path).read_text())
    for i,item in enumerate(fixture.get('cache_source_documents',[])):
        raw=Path(item['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=item['file_sha256']:raise ValueError('CACHE_SOURCE_PIN')
        body=json.loads(raw)['document'];key=('SYNTHETIC_MEMORY',str(i))
        resident.cache[key]=dict(document=body,observed_at_utc=int(time.time()))
        resident.cache_sizes[key]=len(json.dumps(body).encode())
    health=await main.start_health(app);hp=next(iter(health.sites))._server.sockets[0].getsockname()[1]
    began=time.perf_counter()
    try:
        await app.initialize();await app.start();await app.updater.start_polling(poll_interval=.01,timeout=1,bootstrap_retries=0)
        async with ClientSession() as client:
            async with client.get(f'http://127.0.0.1:{hp}/ready') as r:ready=await r.json()
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            delivered={e['update_id'] for e in journal.read() if e.get('kind')=='DELIVERY_ACCEPTED'}
            if len(delivered)==len(commands):break
            await asyncio.sleep(.02)
        events=journal.read();inputs=[e for e in events if e.get('kind')=='COMMAND_RECEIVED'];sends=[e for e in events if e.get('kind')=='DELIVERY_ACCEPTED']
        errors=[e for e in events if e.get('kind') in ('HANDLER_ERROR','SEND_UNCONFIRMED')]
        if errors or len(inputs)!=len(commands) or len({e['update_id'] for e in sends})!=len(commands):raise ValueError('HYBRID_JOURNAL_ERRORS_OR_COUNTS')
        if any(e['update_id']==0 for e in inputs+sends):raise ValueError('UNAUTHORIZED_CHAT_WAS_PROCESSED')
        if not any('PREMATCH tahmini değildir' in s for s in received):raise ValueError('REPLAY_NOT_LABELED')
        if not any('Güven endeksi: hesaplanamadı' in s for s in received):raise ValueError('UNCALIBRATED_CONFIDENCE_GUARD')
        if sum('ELITE HYBRID PRO' in s for s in received)!=repetitions+4 or any('Analiz hizmeti kullanılamıyor' in s for s in received):
            raise ValueError('HYBRID_INFERENCE_OR_RENDER_FAILURE')
        if any(hashlib.sha256(p.read_bytes()).hexdigest()!=h for p,h in originals.items()):raise ValueError('FROZEN_ARCHIVE_MUTATED')
        if results.comparison()['settled_games']!=0:raise ValueError('INVENTED_REAL_RESULT')
        source_pins={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')}
        for name in ('main.py','verified_analysis.py','ledger_reports.py','telegram_delivery.py','projection_integrity.py','Dockerfile'):
            source_pins['../'+name]=hashlib.sha256((Path(__file__).parent.parent/name).read_bytes()).hexdigest()
        return dict(format='HYBRID_TEST_BOT_RUNTIME_V1',status='PASS',actual_telegram_delivery_verified=False,
            transport='LOCAL_HTTP_API_DOUBLE_NOT_REAL_TELEGRAM',requests=len(commands),successful_message_deliveries=len(received),
            nba_source='SYNTHETIC_NATIVE_SCHEMA_FOR_RESOURCE_TEST_ONLY',
            command_names=sorted({e['command'] for e in inputs}),unauthorized_chat_rejected=True,
            frozen_records=5,frozen_components=20,archive_unchanged=True,new_prematch_records_created=0,
            inference_components=['BAYES_QMC','POSSESSION_ANALYTIC','POSSESSION_MC','FAZ13_MC'],online_training=False,
            verified_confidence_indices=0,actual_final_results=0,report_commands_research_labeled=True,
            health_ready=ready,address_space_limit_bytes=list(resource.getrlimit(resource.RLIMIT_AS)),cpu_affinity=sorted(os.sched_getaffinity(0)),
            peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
            elapsed_seconds=time.perf_counter()-began,reply_interval_p95_seconds=float(np.quantile(latencies,.95)),
            latency_scope='SEQUENTIAL_LOCAL_HTTP_REPLY_INTERVAL_INCLUDES_HANDLER_AND_SEND_NOT_INTERNET_LATENCY',
            cache_serialized_bytes=sum(resident.cache_sizes.values()),python_version=sys.version.split()[0],
            native_ml_libraries_loaded=[n for n in ('scipy','sklearn','lightgbm','catboost') if n in sys.modules],
            timeline_events=[e for e in events if e.get('record_type')=='TELEGRAM_ANALYSIS_DELIVERY'][:4],
            command_examples=[received[0],*received[1:3],received[-2],received[-1]],runtime_source_pins=source_pins)
    finally:
        if app.updater.running:await app.updater.stop()
        if app.running:await app.stop()
        await app.shutdown();await health.cleanup();await runner.cleanup()
