"""Full Telegram polling/HTTP/legacy startup + frozen ML inference under RLIMIT_AS.

Only a loopback Telegram API double and synthetic source fixtures are used. No real
token, external Telegram delivery, production database or online training is involved.
"""
import argparse
import json
import os
from pathlib import Path
import resource
import sys
import tempfile
import time


async def run(fixture_path, mode, repetitions):
    import asyncio
    import hashlib
    from datetime import datetime, timezone
    from unittest.mock import patch
    from aiohttp import web, ClientSession
    import numpy as np
    from telegram.ext import Application
    from core.team_identity import digest
    from hybrid_engine.data import Cut
    from hybrid_engine.markets import market_grid, render_research
    from hybrid_engine.portable import PortableBoostedScores
    from hybrid_engine.models import HierarchicalStrength
    from hybrid_engine.possession import PossessionModel
    from hybrid_engine.evaluation import v1_forecast

    if mode == 'native-import-control':
        import lightgbm, catboost  # Expected to need more address space than the portable runtime.
    document = json.loads(Path(fixture_path).read_text())
    if document['data_class'] != 'SYNTHETIC_RESOURCE_ONLY': raise ValueError('RESOURCE_FIXTURE_NOT_ACCURACY_EVIDENCE')
    cut = Cut(**document['cut'])
    models = {n: PortableBoostedScores.load(v['path'], trusted_sha256=v['sha256']) for n, v in document['models'].items()}
    p = document['bayes']['payload']
    if digest(p) != document['bayes']['sha256']: raise ValueError('BAYES_FIXTURE_PIN')
    bayes = HierarchicalStrength(); bayes.identity = tuple(p['identity']); bayes.mode = p['mode']; bayes.cutoff = p['cutoff_utc']
    bayes.teams = p['teams']; bayes.team_index = {v: i for i, v in enumerate(p['teams'])}
    bayes.players = p['players']; bayes.player_index = {v: i for i, v in enumerate(p['players'])}
    bayes.duration = 48; bayes.coefficients = np.asarray(p['coefficients']); bayes.covariance = np.asarray(p['covariance'])
    bayes.noise_variance = p['noise_variance']; bayes.training_ids = p['training_ids']; bayes.artifact_digest = document['bayes']['sha256']; bayes.fitted = True
    received = []; latencies = []; polls = 0
    commands = ['/nba']+['/analyze NBA 2025-01-01 Synthetic Home vs Synthetic Away']*repetitions
    updates = [dict(update_id=i+1, message=dict(message_id=i+1, date=int(time.time()),
        chat=dict(id=17, type='private'), **{'from': dict(id=23, is_bot=False, first_name='Audit')}, text=text,
        entities=[dict(type='bot_command', offset=0, length=len(text.split()[0]))])) for i, text in enumerate(commands)]
    async def telegram_api(request):
        nonlocal polls
        method = request.path.rsplit('/', 1)[-1]
        if method == 'getMe': result = dict(id=123456, is_bot=True, first_name='Audit', username='zeynal_audit_bot')
        elif method == 'getUpdates':
            polls += 1; result = updates[:] if polls == 1 else []
            if polls != 1: await asyncio.sleep(.05)
        elif method == 'sendMessage':
            value = dict(await request.post()); received.append(value['text'])
            result = dict(message_id=1000+len(received), date=int(time.time()), chat=dict(id=17, type='private'), text=value['text'])
        else: result = True
        return web.json_response(dict(ok=True, result=result))
    api = web.Application(); api.router.add_route('*', '/{path:.*}', telegram_api)
    api_runner = web.AppRunner(api); await api_runner.setup()
    site = web.TCPSite(api_runner, '127.0.0.1', 0); await site.start(); port = site._server.sockets[0].getsockname()[1]
    original_builder = Application.builder
    class LocalApplication:
        @staticmethod
        def builder(): return original_builder().base_url(f'http://127.0.0.1:{port}/bot').base_file_url(f'http://127.0.0.1:{port}/file/bot')
    os.environ['TELEGRAM_BOT_TOKEN'] = '123456:SYNTHETIC_LOCAL_ONLY'
    os.environ['API_SPORTS_KEY'] = ''; os.environ['PORT'] = '0'
    os.environ['PREDICTION_LEDGER_DB'] = str(Path.cwd()/'isolated-ledger.sqlite')
    import main
    with patch.object(main, 'Application', LocalApplication): app = main.build_app()
    main.PORT = 0
    cache_service = app.bot_data['verified_analysis_service']
    cache_sources = document.get('cache_source_documents', [])
    def resource_transport(provider, url):
        source = cache_sources[int(url.rsplit('/', 1)[-1]) % len(cache_sources)]
        raw = Path(source['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != source['file_sha256']: raise ValueError('NATIVE_CACHE_PAYLOAD_PIN_MISMATCH')
        body = json.loads(raw)['document']
        # New *synthetic memory replay* receipt; never a historical availability claim.
        return dict(status='DOCUMENT_RECEIVED', provider='SYNTHETIC_MEMORY_REPLAY', document=body,
            observed_at_utc=int(time.time()), ingested_at_utc=int(time.time()), record_type='SYNTHETIC_RESOURCE_REPLAY')
    cache_service.transport = resource_transport
    for i in range(len(cache_sources)): cache_service.fetch('SYNTHETIC_MEMORY_REPLAY', 'http://local.fixture/'+str(i))
    app.bot_data['resource_v1_cache_resident'] = cache_service
    class ShadowService:
        async def analyze(self, *args):
            began = time.perf_counter()
            if cache_sources:
                cache_service.fetch('SYNTHETIC_MEMORY_REPLAY', 'http://local.fixture/'+str(32+len(latencies)))
            forecasts = [m.predict(cut, method='RQMC_HALTON') for m in models.values()]
            forecasts += [bayes.predict(cut, method='RQMC_HALTON'), PossessionModel().predict(cut), v1_forecast(cut)]
            # No verified calibration/roster => no confidence percentage in Telegram.
            forecast = forecasts[0]
            grid = market_grid(forecast, {'1Q': [50.5], '1H': [100.5], 'TOTAL': [200.5], 'HOME': [100.5], 'AWAY': [100.5], 'HOME_HANDICAP': [-5.5]},
                model_digest='SYNTHETIC_RESOURCE', prediction_utc=cut.cutoff_utc)
            trace = dict(model_version=forecast.model, data_time_utc=cut.cutoff_utc-1,
                prediction_utc=cut.cutoff_utc, source='SYNTHETIC_RESOURCE_FIXTURE', inputs_digest=cut.inputs_digest)
            latencies.append(time.perf_counter()-began)
            return dict(html=render_research(grid, trace))
    async def nba_loader(day):
        return [dict(id=str(i), start=datetime.now(timezone.utc), home='Synthetic Home '+str(i), away='Synthetic Away '+str(i), status='Scheduled') for i in range(10)]
    app.bot_data['verified_analysis_service'] = ShadowService(); app.bot_data['nba_fixture_loader'] = nba_loader
    health = await main.start_health(app); health_port = next(iter(health.sites))._server.sockets[0].getsockname()[1]
    try:
        await app.initialize(); await app.start(); await app.updater.start_polling(poll_interval=.01, timeout=1, bootstrap_retries=0)
        async with ClientSession() as client:
            async with client.get(f'http://127.0.0.1:{health_port}/ready') as response:
                ready = await response.json()
                if response.status != 200 or not ready['ready']: raise ValueError('TELEGRAM_POLLING_NOT_READY')
        deadline = time.monotonic()+30
        while len(received) < len(commands) and time.monotonic() < deadline: await asyncio.sleep(.01)
        if len(received) != len(commands): raise ValueError('LOCAL_TELEGRAM_REPLY_COUNT_MISMATCH')
        if any('Güven endeksi' in value or '%' in value for value in received[1:]): raise ValueError('UNVERIFIED_CONFIDENCE_DISPLAYED')
        report = dict(format='TELEGRAM_PORTABLE_ML_RUNTIME_PROBE_V1', status='PASS', mode=mode,
            resource_fixture='SYNTHETIC_NOT_MODEL_PERFORMANCE_EVIDENCE', transport='REAL_HTTP_LOCAL_TELEGRAM_API_DOUBLE',
            actual_telegram_delivery_verified=False, production_default_changed=False,
            python_version=sys.version.split()[0], numpy_version=np.__version__,
            native_ml_libraries_loaded=sorted(n for n in ('scipy', 'sklearn', 'lightgbm', 'catboost') if n in sys.modules),
            address_space_limit_bytes=list(resource.getrlimit(resource.RLIMIT_AS)),
            cpu_affinity=sorted(os.sched_getaffinity(0)), peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
            requests=len(commands), analyze_replies=len(latencies), nba_replies=1, health_ready=ready,
            latency_p95_seconds=float(np.quantile(latencies, .95)),
            models_resident=['LIGHTGBM_PORTABLE', 'CATBOOST_PORTABLE', 'BAYES', 'POSSESSION', 'FAZ13_MC'],
            v1_cache_entries=len(cache_service.cache), v1_cache_serialized_bytes=sum(cache_service.cache_sizes.values()),
            cache_stress='NATIVE_PAYLOAD_MEMORY_REPLAY_NOT_HISTORICAL_OR_LIVE_EVIDENCE',
            source_pins=document['native_portable_checks'], message_example=received[-1])
        report['runtime_source_pins'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')}
        for name in ('main.py', 'historical_research.py', 'prematch_monte_carlo.py', 'verified_analysis.py'):
            report['runtime_source_pins']['../'+name] = hashlib.sha256((Path(__file__).parent.parent/name).read_bytes()).hexdigest()
        return report
    finally:
        if app.updater.running: await app.updater.stop()
        if app.running: await app.stop()
        await app.shutdown(); await health.cleanup(); await api_runner.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', required=True); parser.add_argument('--mode', choices=['portable', 'native-import-control'], default='portable')
    parser.add_argument('--repetitions', type=int, default=20); args = parser.parse_args()
    if not 1 <= args.repetitions <= 50: raise ValueError('BOUNDED_REPETITIONS_REQUIRED')
    resource.setrlimit(resource.RLIMIT_AS, (256*1024*1024, 256*1024*1024))
    os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    original = Path.cwd()
    try:
        import asyncio
        with tempfile.TemporaryDirectory(prefix='zeynal-telegram-memory-') as directory:
            os.chdir(directory)
            report = asyncio.run(run(args.fixture, args.mode, args.repetitions))
        print(json.dumps(report, allow_nan=False))
    except Exception as exc:
        print(json.dumps(dict(status='FAILED', mode=args.mode, error_type=type(exc).__name__, reason=str(exc)[:300],
            address_space_limit_bytes=list(resource.getrlimit(resource.RLIMIT_AS)),
            peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024)))
        raise SystemExit(2)
    finally: os.chdir(original)


if __name__ == '__main__': main()
