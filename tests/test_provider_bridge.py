"""Synthetic HTTP/schema tests and frozen-model integration; not real API/E2E."""
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from core.team_identity import digest
from hybrid_engine.provider_access import credentials, ProviderAccess, get_document, NoRedirect, MAX_BYTES
from hybrid_engine.provider_bridge import ProviderBridge, odds_observations, matches, render
from hybrid_engine.market_views import assess
from tests.test_market_observations import setup_native

ROOT = Path(__file__).resolve().parents[1]
PACKET = next((ROOT/'docs/prospective/handoff-20261115').glob('nba-*.json'))
SNAPSHOT = json.loads(PACKET.read_text())['payload']
NOW = SNAPSHOT['prediction_generated_at_utc']+2
SECRET = 'SYNTHETIC_SECRET_DO_NOT_USE_123456789'


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace('+00:00', 'Z')


def event():
    return dict(id='synthetic-event', sport_key='basketball_nba',
                home_team=SNAPSHOT['home']['official_name'], away_team=SNAPSHOT['away']['official_name'],
                commence_time=iso(SNAPSHOT['fixture_start_utc']))


def market(key='totals', line=221.5, *, last_update=None):
    return dict(key=key, last_update=last_update or iso(NOW-5),
                outcomes=[dict(name='Under', point=line, price=1.91), dict(name='Over', point=line, price=1.95)])


def priced_event():
    return dict(event(), bookmakers=[dict(key='synthetic-book', title='SYNTHETIC ONLY',
                                          last_update=iso(NOW-5), markets=[market()])])


def receipt(document, provider='THE_ODDS_API', url='https://api.the-odds-api.com/v4/synthetic'):
    return dict(status='DOCUMENT_RECEIVED', http_status=200, document=document,
                provider=provider, source_url=url, observed_at_utc=NOW, ingested_at_utc=NOW,
                document_sha256=digest(document), quota={'x-requests-remaining': 50})


class FakeProvider:
    def __init__(self):
        self.calls = []
        self.document = priced_event()
        self.fail = None
        self.games = [dict(id=123, date=iso(SNAPSHOT['fixture_start_utc']),
                           league=dict(id=12, season='2026-2027'), status=dict(short='NS'),
                           teams=dict(home=dict(id=20, name=SNAPSHOT['home']['official_name']),
                                      away=dict(id=11, name=SNAPSHOT['away']['official_name'])))]

    def __call__(self, provider, url, key, *, timeout):
        self.calls.append((provider, url))
        if self.fail:
            return dict(status=self.fail, retry_after_seconds=600)
        path = urlsplit(url).path
        if provider == 'THE_ODDS_API':
            document = ([dict(key='basketball_nba', active=True)] if path.endswith('/sports/') else
                        [event()] if path.endswith('/events') else self.document)
        else:
            document = (dict(errors=[], response=[dict(id=12, name='NBA')]) if path == '/leagues' else
                        dict(errors=[], response=self.games) if path == '/games' else
                        dict(errors=[], response=dict(games=dict(played=dict(all=10)),
                            team=dict(id=int(parse_qs(urlsplit(url).query)['team'][0])),
                            league=dict(id=12, season='2026-2027'))))
        return receipt(document, provider, url)


class CredentialsTests(unittest.TestCase):
    def test_missing_keys_no_fly_or_generic_env_import(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(credentials({}, Path(tmp)/'missing'), {})

    def test_aliases_work_and_private_file_is_literal_not_shell(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp)/'private.env'
            path.write_text('THE_ODDS_API_KEY="'+SECRET+'"\nAPI_SPORTS_KEY=literal$(not-executed)\n')
            path.chmod(0o600)
            result = credentials({}, path)
            self.assertEqual(result['THE_ODDS_API'], SECRET)
            self.assertEqual(result['API_BASKETBALL'], 'literal$(not-executed)')

    def test_private_file_permissions_and_unknown_keys_refused(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp)/'private.env'; path.write_text('TELEGRAM_BOT_TOKEN=not-allowed\n')
            path.chmod(0o644)
            with self.assertRaisesRegex(ValueError, 'OWNER_MODE'): credentials({}, path)
            path.chmod(0o600)
            with self.assertRaisesRegex(ValueError, 'ALLOWLIST'): credentials({}, path)

    def test_symlink_refused(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp)/'real'; target.write_text('ODDS_API_KEY='+SECRET); target.chmod(0o600)
            link = Path(tmp)/'link'; link.symlink_to(target)
            with self.assertRaises(ValueError): credentials({}, link)

    def test_conflicting_aliases_refused_without_values_in_error(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as error:
                credentials(dict(ODDS_API_KEY=SECRET, THE_ODDS_API_KEY='other'), Path(tmp)/'none')
            self.assertNotIn(SECRET, str(error.exception))


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch('time.time', return_value=NOW); self.clock.start(); self.addCleanup(self.clock.stop)
        self.fake = FakeProvider()
        self.access = ProviderAccess({'THE_ODDS_API': SECRET, 'API_BASKETBALL': SECRET}, getter=self.fake,
                                     clock=lambda: NOW)

    def test_key_absence_never_calls_network(self):
        getter = Mock()
        access = ProviderAccess({}, getter=getter)
        self.assertEqual(access.get('THE_ODDS_API', '/v4/sports/')['status'], 'KEY_NOT_AVAILABLE_IN_TEST_PROCESS')
        getter.assert_not_called()

    def test_positive_cache_preserves_clock_and_secrets_absent(self):
        first = self.access.get('THE_ODDS_API', '/v4/sports/')
        second = self.access.get('THE_ODDS_API', '/v4/sports/')
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(first['observed_at_utc'], second['observed_at_utc'])
        self.assertNotIn(SECRET, json.dumps(second)+repr(self.access))
        second['document'].clear()
        self.assertTrue(self.access.get('THE_ODDS_API', '/v4/sports/')['document'])

    def test_auth_quota_and_network_failures_have_cooldown(self):
        for state in ('AUTHENTICATION_FAILED', 'RATE_LIMITED', 'PROVIDER_NETWORK_OR_RESPONSE_ERROR'):
            fake = FakeProvider(); fake.fail = state
            access = ProviderAccess({'THE_ODDS_API': SECRET}, getter=fake, clock=lambda: NOW)
            self.assertEqual(access.get('THE_ODDS_API', '/v4/sports/')['status'], state)
            self.assertEqual(access.get('THE_ODDS_API', '/v4/sports/other')['status'], 'PROVIDER_COOLDOWN')
            self.assertEqual(len(fake.calls), 1)

    def test_daily_local_budget(self):
        self.access.max_calls = 1
        self.access.get('THE_ODDS_API', '/v4/sports/')
        self.assertEqual(self.access.get('THE_ODDS_API', '/v4/other')['status'], 'LOCAL_DAILY_REQUEST_BUDGET')

    def test_exhausted_provider_quota(self):
        def getter(p, u, k, **kw):
            return dict(receipt([], p, u), quota={'x-requests-remaining': 0})
        access = ProviderAccess({'THE_ODDS_API': SECRET}, getter=getter, clock=lambda: NOW)
        access.get('THE_ODDS_API', '/one')
        self.assertEqual(access.get('THE_ODDS_API', '/two')['status'], 'PROVIDER_QUOTA_EXHAUSTED')

    def test_bad_receipt_or_secret_query_refused(self):
        self.assertEqual(self.access.get('THE_ODDS_API', '/one', dict(apiKey=SECRET))['status'], 'CREDENTIAL_QUERY_FORBIDDEN')
        self.access.getter = lambda *a, **kw: dict(receipt([]), source_url='https://other.invalid')
        self.assertEqual(self.access.get('THE_ODDS_API', '/one')['status'], 'PROVIDER_RECEIPT_INVALID')

    def test_deadline_refuses_request(self):
        self.assertEqual(self.access.get('THE_ODDS_API', '/one', deadline=NOW)['status'], 'PROVIDER_TIME_BUDGET')
        self.assertFalse(self.fake.calls)

    def test_transport_headers_and_no_secret_url(self):
        response = Mock(); response.read.return_value = b'[]'; response.status = 200; response.headers = {}
        context = Mock(); context.__enter__ = Mock(return_value=response); context.__exit__ = Mock(return_value=False)
        opener = Mock(); opener.open.return_value = context
        with patch('hybrid_engine.provider_access.build_opener', return_value=opener):
            result = get_document('THE_ODDS_API', 'https://api.the-odds-api.com/v4/sports/', SECRET, timeout=1)
        req = opener.open.call_args.args[0]
        self.assertEqual(req.get_header('X-api-key'), SECRET)
        self.assertNotIn(SECRET, req.full_url+json.dumps(result))
        self.assertEqual(result['status'], 'DOCUMENT_RECEIVED')

    def test_http_error_does_not_echo_body_or_url(self):
        for code, status in [(401, 'AUTHENTICATION_FAILED'), (403, 'ACCESS_OR_PLAN_DENIED'), (429, 'RATE_LIMITED')]:
            err = HTTPError('https://invalid/?apiKey='+SECRET, code, SECRET, {}, io.BytesIO(SECRET.encode()))
            opener = Mock(); opener.open.side_effect = err
            with patch('hybrid_engine.provider_access.build_opener', return_value=opener):
                r = get_document('THE_ODDS_API', 'https://api.the-odds-api.com/v4/sports/', SECRET, timeout=1)
            self.assertEqual(r['status'], status)
            self.assertNotIn(SECRET, json.dumps(r))

    def test_wrong_origin_and_redirect_refused(self):
        self.assertEqual(get_document('THE_ODDS_API', 'https://evil.invalid/', SECRET, timeout=1)['status'], 'PROVIDER_ORIGIN_REFUSED')
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.invalid'))

    def test_oversize_and_secret_echo_responses_are_not_archived(self):
        for raw, expected in [(b'x'*(MAX_BYTES+1), 'PROVIDER_RESPONSE_SIZE_LIMIT'),
                              (json.dumps(dict(echo=SECRET)).encode(), 'PROVIDER_SECRET_ECHO_REFUSED')]:
            response=Mock(); response.read.return_value=raw; response.status=200; response.headers={}
            context=Mock(); context.__enter__=Mock(return_value=response); context.__exit__=Mock(return_value=False)
            opener=Mock(); opener.open.return_value=context
            with patch('hybrid_engine.provider_access.build_opener',return_value=opener):
                r=get_document('THE_ODDS_API','https://api.the-odds-api.com/v4/sports/',SECRET,timeout=1)
            self.assertEqual(r['status'],expected); self.assertNotIn(SECRET,json.dumps(r))


class OddsParserTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch('time.time', return_value=NOW); self.clock.start(); self.addCleanup(self.clock.stop)

    def parse(self, doc):
        return odds_observations(receipt(doc), SNAPSHOT)

    def test_alternatives_are_not_collapsed(self):
        e = priced_event(); e['bookmakers'][0]['markets'] = [dict(market('alternate_totals'), outcomes=[
            *market(line=220.5)['outcomes'], *market(line=221.5)['outcomes']])]
        rows, rejected = self.parse(e)
        self.assertEqual(rejected, 0)
        self.assertEqual([q['line'] for q in rows[0]['payload']['quotes']], [220.5, 221.5])
        self.assertEqual(rows[0]['payload']['source']['published_at_utc'], NOW-5)
        self.assertEqual(rows[0]['payload']['available_at_utc'], NOW)
        self.assertEqual(rows[0]['payload']['calibration_status'], 'NOT_CALIBRATED')

    def test_quarters_halves_and_team_totals(self):
        e = priced_event()
        for key, expected in [('totals_q1', '1Q'), ('totals_q4', '4Q'), ('totals_h1', '1H'), ('totals_h2', '2H')]:
            e['bookmakers'][0]['markets'] = [market(key)]
            rows, _ = self.parse(e)
            self.assertEqual(rows[0]['payload']['quotes'][0]['period'], expected)
        team = market('team_totals')
        for o in team['outcomes']: o['description'] = SNAPSHOT['away']['official_name']
        e['bookmakers'][0]['markets'] = [team]
        self.assertEqual(self.parse(e)[0][0]['payload']['quotes'][0]['market'], 'AWAY')

    def test_spread_signs_match_home_handicap(self):
        e = priced_event(); m = market('spreads')
        m['outcomes'] = [dict(name=e['home_team'], point=-3.5, price=1.9),
                         dict(name=e['away_team'], point=3.5, price=1.9)]
        e['bookmakers'][0]['markets'] = [m]
        rows, _ = self.parse(e)
        self.assertEqual(rows[0]['payload']['quotes'][0]['line'], -3.5)
        m['outcomes'][1]['point'] = -3.5
        self.assertEqual(self.parse(e)[0], [])

    def test_wrong_identity_tipoff_or_league_rejected(self):
        for field, value in [('away_team', 'Wrong team'), ('commence_time', iso(SNAPSHOT['fixture_start_utc']+86400)), ('sport_key', 'basketball_euroleague')]:
            e = priced_event(); e[field] = value
            with self.assertRaisesRegex(ValueError, 'IDENTITY'): self.parse(e)

    def test_no_naive_timezone_or_swapped_teams(self):
        e = event(); e['commence_time'] = e['commence_time'].removesuffix('Z')
        self.assertFalse(matches(e, SNAPSHOT))
        e = event(); e['home_team'], e['away_team'] = e['away_team'], e['home_team']
        self.assertFalse(matches(e, SNAPSHOT))

    def test_stale_future_missing_clock_and_invalid_prices_rejected(self):
        for value in [iso(NOW-301), iso(NOW+1), 'not-a-clock']:
            e = priced_event(); e['bookmakers'][0]['markets'][0]['last_update'] = value
            rows, rejected = self.parse(e); self.assertFalse(rows); self.assertEqual(rejected, 1)
        for price in [True, 1, -2, float('inf')]:
            e = priced_event(); e['bookmakers'][0]['markets'][0]['outcomes'][0]['price'] = price
            with self.subTest(price=price):
                # Non-finite documents cannot acquire a canonical hash.
                if price == float('inf'):
                    with self.assertRaises(ValueError): self.parse(e)
                else:self.assertFalse(self.parse(e)[0])

    def test_mutated_native_document_refused(self):
        r = receipt(priced_event()); r['document']['id'] = 'mutated'
        with self.assertRaisesRegex(ValueError, 'PIN'): odds_observations(r, SNAPSHOT)

    def test_current_quotes_do_not_become_historical_or_calibrated(self):
        r, native, batch, distribution = setup_native()
        # Use the pinned synthetic decision trace; no actual market or confidence.
        batch['payload']['available_at_utc'] = distribution.trace['prediction_utc']+1
        batch['payload']['source']['captured_at_utc'] = distribution.trace['prediction_utc']+1
        batch['sha256'] = digest(batch['payload'])
        with patch('time.time', return_value=distribution.trace['prediction_utc']+2):
            view = assess(batch, distribution, asof_utc=distribution.trace['prediction_utc']+2)
        self.assertIn('SOURCE_AVAILABLE_AFTER_ORIGINAL_FORECAST', view['reasons'])
        self.assertIsNone(view['rows'][0]['expected_value'])
        self.assertIsNone(view['rows'][0]['confidence_index'])


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch('time.time', return_value=NOW); self.clock.start(); self.addCleanup(self.clock.stop)
        self.tmp = TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.fake = FakeProvider()
        access = ProviderAccess({'THE_ODDS_API': SECRET, 'API_BASKETBALL': SECRET}, getter=self.fake, clock=lambda: NOW)
        self.bridge = ProviderBridge(access, self.root/'provider-evidence', clock=lambda: NOW)

    def test_both_providers_integrated_and_forecast_unchanged(self):
        snap = deepcopy(SNAPSHOT); before = digest(snap)
        report = self.bridge.collect(snap)
        self.assertEqual(report['providers']['THE_ODDS_API']['status'], 'OBSERVED_RULES_AND_CALIBRATION_PENDING')
        b = report['providers']['API_BASKETBALL']
        self.assertEqual(b['status'], 'PREMATCH_FIXTURE_CROSSCHECKED')
        self.assertEqual(len(b['statistics']), 2)
        self.assertFalse(b['injuries_verified']); self.assertFalse(b['forecast_inputs_changed'])
        self.assertEqual(digest(snap), before)
        self.assertNotIn(SECRET, json.dumps(report))
        for path in self.bridge.root.glob('*.json'):
            wrapper = json.loads(path.read_text())
            self.assertEqual(wrapper['sha256'], digest(wrapper['payload']))
            self.assertNotIn(SECRET, path.read_text())

    def test_no_keys_no_network_and_clear_status_not_no_edge(self):
        bridge = ProviderBridge(ProviderAccess({}, getter=self.fake), self.root/'empty', clock=lambda: NOW)
        r = bridge.collect(SNAPSHOT)
        self.assertFalse(self.fake.calls)
        self.assertEqual(r['providers']['THE_ODDS_API']['status'], 'KEY_NOT_AVAILABLE_IN_TEST_PROCESS')
        self.assertIn('NO EDGE anlamına gelmez', render(r))

    def test_finished_fixture_never_fetches_or_backfills(self):
        self.bridge.clock = lambda: SNAPSHOT['fixture_start_utc']
        r = self.bridge.collect(SNAPSHOT)
        self.assertEqual(r['status'], 'POST_TIPOFF_NO_CURRENT_API_BACKFILL')
        self.assertFalse(self.fake.calls)
        self.assertFalse(self.bridge.root.exists())

    def test_auth_failure_reports_not_advantage(self):
        self.fake.fail = 'AUTHENTICATION_FAILED'
        r = self.bridge.collect(SNAPSHOT)
        self.assertEqual(r['providers']['THE_ODDS_API']['status'], 'AUTHENTICATION_FAILED')
        self.assertNotIn('NO_EDGE', json.dumps(r))

    def test_ambiguous_fixture_is_not_matched_by_similarity(self):
        self.fake.games *= 2
        r = self.bridge.collect(SNAPSHOT)
        self.assertEqual(r['providers']['API_BASKETBALL']['status'], 'EXACT_FIXTURE_MATCH_REQUIRED')

    def test_only_explicit_extra_market_optin_increases_request(self):
        self.bridge.collect(SNAPSHOT)
        url = next(u for p,u in self.fake.calls if '/odds?' in u)
        self.assertEqual(parse_qs(urlsplit(url).query)['markets'], ['h2h,spreads,totals'])
        self.assertNotIn('apiKey', url)
        self.bridge.extended = True
        self.bridge.collect(SNAPSHOT)
        url = [u for p,u in self.fake.calls if '/odds?' in u][-1]
        self.assertIn('alternate_totals', url)

    def test_fresh_cached_receipts_are_not_retimed(self):
        a = self.bridge.collect(SNAPSHOT)
        count = len(self.fake.calls)
        b = self.bridge.collect(SNAPSHOT)
        self.assertEqual(len(self.fake.calls), count)
        self.assertEqual(a['providers']['THE_ODDS_API']['observations'], b['providers']['THE_ODDS_API']['observations'])

    def test_provider_call_in_progress_is_visible(self):
        self.bridge.lock.acquire()
        try:self.assertEqual(self.bridge.collect(SNAPSHOT)['status'], 'PROVIDER_REVIEW_ALREADY_RUNNING')
        finally:self.bridge.lock.release()

    def test_archive_directory_not_production_volume(self):
        with self.assertRaises(ValueError): ProviderBridge(self.bridge.access, '/data/provider-evidence')

    def test_statistics_wrong_team_are_not_marked_verified(self):
        original=self.bridge.access.getter
        def getter(provider,url,key,**kwargs):
            r=original(provider,url,key,**kwargs)
            if '/statistics?' in url:
                r['document']['response']['team']['id']=9999
                r['document_sha256']=digest(r['document'])
            return r
        self.bridge.access.getter=getter
        r=self.bridge.collect(SNAPSHOT)
        self.assertTrue(all(x['status']=='STATISTICS_TEAM_LEAGUE_SEASON_NOT_VERIFIED'
                            for x in r['providers']['API_BASKETBALL']['statistics']))


class ProviderTelegramTests(unittest.IsolatedAsyncioTestCase):
    async def test_ptb_analyze_and_market_callback_use_provider_without_altering_forecast(self):
        import importlib
        from types import SimpleNamespace
        from aiohttp import web
        from telegram import Update
        from telegram.ext import Application
        from unittest.mock import AsyncMock
        from tests.test_phase90 import FrozenPhiladelphiaAudit
        from hybrid_engine.live_nba import PreparedBayes
        from hybrid_engine.frozen_archive import FrozenArchive
        from hybrid_engine.test_bot import AuditedRequest, install_isolated_services
        from live_analysis_ledger import LiveAnalysisLedger
        from telegram_delivery import DeliveryJournal
        audit = FrozenPhiladelphiaAudit('runTest'); audit.setUp(); self.addCleanup(audit.doCleanups)
        snap = audit.p; before = digest(snap)
        with TemporaryDirectory() as tmp, patch('time.time', return_value=NOW):
            root = Path(tmp); sent = []; edits = []
            async def api(request):
                method = request.path.rsplit('/', 1)[-1]
                if method == 'getMe':
                    result = dict(id=123456, is_bot=True, first_name='Synthetic', username='zeynal_test_bot')
                elif method in ('sendMessage', 'editMessageText'):
                    value = dict(await request.post()); (sent if method == 'sendMessage' else edits).append(value['text'])
                    result = dict(message_id=100+len(sent), date=NOW, chat=dict(id=17,type='private'), text=value['text'])
                else:result = True
                return web.json_response(dict(ok=True, result=result))
            server = web.Application(); server.router.add_route('*', '/{path:.*}', api)
            runner = web.AppRunner(server); await runner.setup()
            site = web.TCPSite(runner, '127.0.0.1', 0); await site.start()
            port = site._server.sockets[0].getsockname()[1]
            journal = DeliveryJournal(root/'mock-http.sqlite')
            with patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN':'123456:SYNTHETIC_LOCAL_ONLY',
                                        'API_SPORTS_KEY':'', 'PREDICTION_LEDGER_DB':str(root/'unused.sqlite')}):
                main = importlib.import_module('main'); engine = main.Faz23Engine
                class Local:
                    @staticmethod
                    def builder():
                        return Application.builder().base_url(f'http://127.0.0.1:{port}/bot').request(AuditedRequest(journal))
                with patch.object(main, 'Application', Local), patch.object(main, 'Faz23Engine', lambda:engine(str(root/'faz23.sqlite'))):
                    app = main.build_app()
            service = SimpleNamespace(assets=audit.assets,
                prepared=PreparedBayes(audit.assets/snap['prepared_asset']['file'], trusted_sha256=snap['prepared_artifact_sha256']),
                ledger=LiveAnalysisLedger(root/'nba.sqlite'),
                analyze=AsyncMock(return_value=dict(status='ANALYSIS_OK', snapshot=snap, new_record=False, html='ARŞİV',
                    html_parts=['<b>TAHMİN ARALIKLARI</b>', '<b>PERİYOT ANALİZİ</b>', '<b>PİYASA KARŞILAŞTIRMASI</b>', '<b>MODEL DENETİMİ</b>'])))
            fake = FakeProvider()
            access = ProviderAccess({'THE_ODDS_API':SECRET,'API_BASKETBALL':SECRET}, getter=fake, clock=lambda:NOW)
            bridge = ProviderBridge(access, root/'provider-evidence', clock=lambda:NOW)
            archive = FrozenArchive(ROOT/'docs/prospective/euroleague-20261112')
            installed, _ = install_isolated_services(app, archive, root/'isolated', chat_id=17,
                                                     nba_service=service, provider_bridge=bridge)
            # This integration test verifies market/callback/score invariants.
            # Suppress the independent async player-source continuation here:
            # it has separate fake-source tests, and must not hit real URLs.
            app.bot_data.pop('auto_nba_player_pipeline', None)
            await app.initialize()
            try:
                command = '/analyze NBA 2026-11-15 Philadelphia 76ers vs Indiana Pacers'
                update = Update.de_json(dict(update_id=1, message=dict(message_id=1,date=NOW,chat=dict(id=17,type='private'),
                    **{'from':dict(id=23,is_bot=False,first_name='Synthetic')},text=command,
                    entities=[dict(type='bot_command',offset=0,length=8)])), app.bot)
                await app.process_update(update)
                self.assertTrue(any('112.5' in s and '221.8' in s for s in sent))
                self.assertTrue(fake.calls)
                token = next(iter(app.bot_data['premium_reports']))
                callback = Update.de_json(dict(update_id=2, callback_query=dict(id='synthetic-provider-callback',chat_instance='mock',
                    data='zui:'+token+':market', **{'from':dict(id=23,is_bot=False,first_name='Synthetic')},
                    message=dict(message_id=101,date=NOW,chat=dict(id=17,type='private'),text=sent[0]))), app.bot)
                await app.process_update(callback)
                entry=app.bot_data['premium_reports'][token]
                calls_before=len(fake.calls)
                # Inspect the actual paginated callback route, including the
                # provider audit moved out of the compact market card.
                for section in ('market','audit'):
                    for page in range(len(entry['section_pages'][section])):
                        detail = Update.de_json(dict(update_id=10+page,callback_query=dict(
                            id='detail-'+section+str(page),chat_instance='mock',
                            data=f'zui:{token}:{section}:{page}',
                            **{'from':dict(id=23,is_bot=False,first_name='Synthetic')},
                            message=dict(message_id=101,date=NOW,chat=dict(id=17,type='private'),text=sent[0]))),app.bot)
                        await app.process_update(detail)
                self.assertEqual(len(fake.calls),calls_before)
                # Synthetic market/Telegram integration is isolated from the
                # async player worker. One command emits one primary score.
                # Live async sidecar delivery is tested separately with stubs.
                self.assertEqual(len(sent),1)
                self.assertNotIn('OTOMATİK NBA OYUNCU',sent[0])
                self.assertIn('Yönün güvenilirliği',edits[0])
                self.assertIn('Henüz yeterince doğrulanmadı',edits[0])
                body = '\n'.join(sent+edits)
                self.assertIn('The Odds API: Gerçek fiyatlar alındı; ödeme kuralı ve kalibrasyon bekleniyor', body)
                self.assertIn('API-Basketball: Başlamamış maç ikinci kaynaktan doğrulandı', body)
                self.assertIn('GÜNCEL PİYASA DEĞERLENDİRMESİ',body)
                self.assertIn('Karar SHA:',body)
                self.assertTrue(list((root/'current-market-reviews').glob('review-*.json')))
                self.assertIn('221,5', body); self.assertIn('Ham normal süre', body)
                self.assertIn('NOT_CALIBRATED', body); self.assertNotIn(SECRET, body)
                self.assertTrue(all(len(x.encode('utf-16-le'))//2 <= 4096 for x in sent+edits))
                self.assertFalse(any(e.get('kind') == 'HANDLER_ERROR' for e in installed.read()))
                self.assertEqual(digest(snap), before)
                # Real incident regression (23 Nov Miami-OKC): a second, later
                # research market model was presented as the first forecast.
                # It must not turn a valid /analyze into a ValueError at
                # telegram_premium_ui.py:26. Original score remains unchanged.
                from hybrid_engine import market_direction_ui as mdi
                original_cards=mdi.cards
                changed=[0]
                def new_assessment_cards(*args,**kwargs):
                    values=original_cards(*args,**kwargs)
                    result=[]
                    for card in values:
                        if card['period']=='FULL' and card['market']=='TOTAL':
                            changed[0]+=1
                            result.append(dict(card,current=True,
                                valid_until_utc=NOW+300,model_digest='f'*64))
                        else:result.append(card)
                    return result
                with patch.object(mdi,'cards',side_effect=new_assessment_cards):
                    reanalyze=Update.de_json(dict(update_id=81,message=dict(
                        message_id=81,date=NOW,chat=dict(id=17,type='private'),
                        **{'from':dict(id=23,is_bot=False,first_name='Synthetic')},
                        text=command,entities=[dict(type='bot_command',offset=0,length=8)])),app.bot)
                    await app.process_update(reanalyze)
                self.assertGreater(changed[0],0)
                self.assertEqual(len(sent),2)
                self.assertIn('ZEYNAL | NBA ANALİZ',sent[1])
                self.assertIn('Güncel doğrulanmış barem yok',sent[1])
                self.assertNotIn('ANALYZE_VALIDATION_ERROR',sent[1])
                self.assertEqual(digest(snap),before)
            finally:
                await app.shutdown(); await runner.cleanup()


if __name__ == '__main__':
    unittest.main()
