"""Native-payload NBA + PTB resource replay. Never real Telegram delivery evidence."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import resource
import time
from unittest.mock import patch


async def run(fixture_path,repetitions=20,*,decisions=False):
    from concurrent.futures import ThreadPoolExecutor
    from aiohttp import web,ClientSession
    from telegram.ext import Application
    from hybrid_engine.frozen_archive import FrozenArchive
    from hybrid_engine.live_nba import PreparedBayes,LiveNBAHybridService
    from hybrid_engine.test_bot import AuditedRequest,install_isolated_services
    from telegram_delivery import DeliveryJournal

    asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=1))
    fixture_path=Path(fixture_path);fixture=json.loads(fixture_path.read_text());base=fixture_path.parent
    archive=FrozenArchive(Path(__file__).parent.parent/'docs/prospective/euroleague-20261112')
    timer=patch('time.time',return_value=fixture['clock_utc']);timer.start()
    def transport(provider,url):
        item=fixture['sources'][url];path=base/item['file'];raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=item['file_sha256']:raise ValueError('RESOURCE_NATIVE_FILE_PIN')
        return json.loads(raw)
    prepared=PreparedBayes(base/fixture['prepared_file'],trusted_sha256=fixture['prepared_sha256'])
    root=Path.cwd();service=LiveNBAHybridService(root/'nba',prepared,fetcher=transport)
    targets=fixture['targets'];first=targets[0]
    command=lambda g:'/analyze NBA 2026-11-13 '+g['home']+' vs '+g['away']
    el=next(iter(archive.records.values()))['fixture']
    commands=['/nba 2026-11-13']+[command(g) for g in targets]+[command(first)]*repetitions+[
        command(first).replace('2026-11-13','2026-11-12'),'/accuracy NBA','/compare NBA '+first['id'],
        '/analyze EUROLEAGUE 2026-11-12 '+el['home_name']+' vs '+el['away_name']]
    updates=[dict(update_id=i+1,message=dict(message_id=i+1,date=fixture['clock_utc'],chat=dict(id=17,type='private'),
        **{'from':dict(id=23,is_bot=False,first_name='Synthetic input replay')},text=c,
        entities=[dict(type='bot_command',offset=0,length=len(c.split()[0]))])) for i,c in enumerate(commands)]
    received=[];polls=0;intervals=[];last=time.perf_counter()
    async def api(request):
        nonlocal polls,last
        name=request.path.rsplit('/',1)[-1]
        if name=='getMe':result=dict(id=123456,is_bot=True,first_name='Synthetic',username='zeynal_test_bot')
        elif name=='getUpdates':
            polls+=1;result=updates[:] if polls==1 else []
            if polls>1:await asyncio.sleep(.05)
        elif name=='sendMessage':
            p=dict(await request.post());now=time.perf_counter();intervals.append(now-last);last=now;received.append(p['text'])
            result=dict(message_id=1000+len(received),date=fixture['clock_utc'],chat=dict(id=17,type='private'),text=p['text'])
        else:result=True
        return web.json_response(dict(ok=True,result=result))
    http=web.Application();http.router.add_route('*','/{path:.*}',api);runner=web.AppRunner(http);await runner.setup()
    site=web.TCPSite(runner,'127.0.0.1',0);await site.start();port=site._server.sockets[0].getsockname()[1]
    os.environ['TELEGRAM_BOT_TOKEN']='123456:SYNTHETIC_LOCAL_ONLY';os.environ['API_SPORTS_KEY']='';os.environ['PORT']='0'
    os.environ['PREDICTION_LEDGER_DB']=str(root/'unused.sqlite')
    import main
    journal=DeliveryJournal(root/'telegram-delivery.sqlite')
    class Local:
        @staticmethod
        def builder():return Application.builder().base_url(f'http://127.0.0.1:{port}/bot').request(AuditedRequest(journal))
    with patch.object(main,'Application',Local):app=main.build_app()
    install_isolated_services(app,archive,root,chat_id=17,transport=transport,nba_service=service,decision_layer=decisions)
    main.PORT=0;health=await main.start_health(app)
    health_port=next(iter(health.sites))._server.sockets[0].getsockname()[1]
    began=time.perf_counter()
    try:
        with patch('hybrid_engine.models.HierarchicalStrength.fit',side_effect=AssertionError('No request training')):
            await app.initialize();await app.start();await app.updater.start_polling(poll_interval=.01,timeout=1,bootstrap_retries=0)
            async with ClientSession() as client:
                async with client.get(f'http://127.0.0.1:{health_port}/ready') as response:ready=await response.json()
            deadline=time.monotonic()+100
            while time.monotonic()<deadline:
                delivered={e['update_id'] for e in journal.read() if e.get('kind')=='DELIVERY_ACCEPTED'}
                if len(delivered)==len(commands):break
                await asyncio.sleep(.02)
        await app.update_queue.join()
        events=journal.read();errors=[e for e in events if e.get('kind') in ('HANDLER_ERROR','SEND_UNCONFIRMED')]
        from ledger_reports import LedgerReports
        report=LedgerReports(service.ledger.path).read('NBA')
        if errors or len(delivered)!=len(commands) or report['unique_fixtures']!=4:raise ValueError('LIVE_COMMAND_COUNTS_OR_HANDLER_FAILURE')
        if any('Analiz hizmeti kullanılamıyor' in s or 'hibrit analiz kaydedilmedi' in s for s in received):raise ValueError('LIVE_INFERENCE_FAILED')
        if not any('FIXTURE_LOCAL_DATE_MISMATCH' in s for s in received):raise ValueError('DATE_DIAGNOSTIC_NOT_SENT')
        if report['groups'] or report['pending']!=4:raise ValueError('INVENTED_FINAL_OR_METRIC')
        if sum('Gerçek maç öncesi tahmin' in s for s in received)!=4+repetitions:raise ValueError('LIVE_RENDER_NOT_DELIVERED')
        decision_records=app.bot_data['decision_journal'].read() if decisions else []
        if decisions:
            if len(decision_records)!=5 or any(e['selected'] for b in decision_records for e in b['evaluations']):raise ValueError('DECISION_DEDUP_OR_SELECTION_GUARD')
            if not any('ELITE KARAR VE KALİBRASYON' in s for s in received):raise ValueError('DECISION_RENDER_NOT_SENT')
        import numpy as np
        import sys
        cgroup={}
        for name in ('memory.max','memory.peak','cpu.max'):
            path=Path('/sys/fs/cgroup')/name
            if path.exists():cgroup[name]=path.read_text().strip()
        return dict(format='NBA_NATIVE_PAYLOAD_RESOURCE_REPLAY_V1',status='PASS',actual_telegram_delivery_verified=False,
            evidence_class='MOCK_CLOCK_NATIVE_SOURCE_REPLAY_NOT_NEW_PROSPECTIVE_FORECASTS',
            transport='LOCAL_HTTP_BOT_API_DOUBLE',requests=len(commands),messages=len(received),unique_nba_snapshots=4,
            original_prospective_archive_modified=False,online_training=False,native_payload_urls=len(fixture['sources']),
            address_space_limit_bytes=list(resource.getrlimit(resource.RLIMIT_AS)),cpu_affinity=sorted(os.sched_getaffinity(0)),
            peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,elapsed_seconds=time.perf_counter()-began,
            reply_interval_p95_seconds=float(np.quantile(intervals,.95)),
            native_ml_libraries_loaded=[n for n in ('scipy','sklearn','lightgbm','catboost') if n in sys.modules],
            isolated_sqlite_integrity=service.ledger.integrity(),
            decision_layer_enabled=decisions,decision_batches=len(decision_records),selected_market_lines=0,
            observed_cgroup=cgroup,
            health_ready=ready,
            source_pins={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')})
    finally:
        if app.updater.running:await app.updater.stop()
        if app.running:await app.stop()
        await app.shutdown();await health.cleanup();await runner.cleanup();timer.stop()


def unpack(packet,directory):
    """Extract only bounded regular files; never links, devices or traversal paths."""
    import tarfile
    from hybrid_engine.data import local_path
    root=local_path(directory);root.mkdir(parents=True,exist_ok=True)
    total=0
    with tarfile.open(packet,'r:gz') as archive:
        for member in archive:
            target=local_path(root/member.name)
            if not member.isfile() or target.parent!=root or member.size>5*1024*1024:raise ValueError('RESOURCE_PACKET_MEMBER_REFUSED')
            total+=member.size
            if total>128*1024*1024:raise ValueError('RESOURCE_PACKET_SIZE_BUDGET')
            raw=archive.extractfile(member).read()
            if target.exists():
                if target.read_bytes()!=raw:raise ValueError('RESOURCE_PACKET_CONFLICT')
            else:
                with target.open('xb') as f:f.write(raw)
    return root/'fixture.json'


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--packet',required=True);p.add_argument('--output-directory',required=True)
    args=p.parse_args();print(unpack(args.packet,args.output_directory))
