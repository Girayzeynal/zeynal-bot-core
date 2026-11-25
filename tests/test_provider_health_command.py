"""Real PTB diagnostic routing with synthetic credentials/transport only."""
import asyncio
import json
import threading
import time
from unittest import IsolatedAsyncioTestCase,TestCase
from unittest.mock import Mock,patch

from hybrid_engine.provider_access import ProviderAccess
from hybrid_engine.isolated_execution import IsolatedExecutor
from tests import test_europe_premium_ui as ui
from tests import test_integrated_features as integration
from tests.test_provider_bridge import receipt,SECRET


class ProviderStatusContentionTests(TestCase):
    def test_runtime_diagnostic_never_waits_for_a_network_request_lock(self):
        access=ProviderAccess({'THE_ODDS_API':'SYNTHETIC_ONLY'})
        access.lock.acquire()
        release=threading.Timer(.2,access.lock.release);release.start()
        try:
            start=time.monotonic();status=access.runtime_status()
            self.assertLess(time.monotonic()-start,.1)
            self.assertEqual(status['THE_ODDS_API']['snapshot_status'],'BUSY')
            self.assertIsNone(status['THE_ODDS_API']['local_calls_today'])
            self.assertEqual(status['THE_ODDS_API']['configuration'],'CONFIGURED_NOT_TESTED')
            self.assertNotIn('SYNTHETIC_ONLY',json.dumps(status))
        finally:release.join()


class ProviderHealthCommandTests(IsolatedAsyncioTestCase):
    asyncSetUp=ui.EuropeanButtonTests.asyncSetUp
    command=integration.IntegratedCommandTests.command

    async def test_data_reply_uses_actual_segmented_storage_contract(self):
        bridge=self.app.bot_data['europe_data_review'].bridge
        usage=bridge.storage_status()
        self.assertNotIn('maximum_files',usage)
        before=self.nba.ledger.path.read_bytes()
        with patch.object(bridge,'collect',side_effect=AssertionError('NO_PROVIDER_QUERY')):
            for command in ('/test data','/test all','/test'):
                self.api.sent.clear()
                await self.command(command)
                self.assertTrue(self.api.sent,command+' silently failed before sending a reply')
        self.assertTrue(self.api.sent,'/test data silently failed before sending a reply')
        text='\n'.join(self.api.sent)
        self.assertIn('THE_ODDS_API',text);self.assertIn('API_BASKETBALL',text)
        self.assertIn('256',text);self.assertIn('bölüm',text)
        self.assertIn('KEY_NOT_AVAILABLE_IN_TEST_PROCESS',text)
        self.assertEqual(before,self.nba.ledger.path.read_bytes())
        self.nba.analyze.assert_not_awaited()

    async def test_provider_diagnostics_are_not_accessible_from_other_chats(self):
        await self.command('/test data',chat=99)
        await self.command('/test providers check',chat=99)
        self.assertEqual(self.api.sent,[])

    def access(self,getter,keys=None,**kwargs):
        bridge=self.app.bot_data['europe_data_review'].bridge
        bridge.access=ProviderAccess(keys if keys is not None else {'THE_ODDS_API':SECRET,'API_BASKETBALL':SECRET},
            getter=getter,clock=lambda:self.clock,**kwargs)
        return bridge

    def receipt(self,document,provider,url):
        r=receipt(document,provider,url)
        # Use the command fixture's actual source clock, not the different
        # market fixture's later day. Keep receipt-future rejection intact.
        r.update(observed_at_utc=self.clock,ingested_at_utc=self.clock)
        return r

    async def test_running_process_keys_are_visible_without_api_or_disk_scan(self):
        getter=Mock(side_effect=AssertionError('NO_API_QUERY'))
        bridge=self.access(getter,keys={'THE_ODDS_API':SECRET})
        with patch.object(bridge,'storage_status',side_effect=AssertionError('NO_DISK_SCAN')):
            await self.command('/test providers')
        text='\n'.join(self.api.sent)
        self.assertIn('THE_ODDS_API: CONFIGURED_NOT_TESTED',text)
        self.assertIn('API_BASKETBALL: KEY_NOT_AVAILABLE_IN_TEST_PROCESS',text)
        self.assertIn('API isteği yapmadı',text);self.assertNotIn(SECRET,text)
        getter.assert_not_called()

    async def test_explicit_check_uses_exact_existing_endpoints_and_sanitizes_errors(self):
        urls=[]
        def getter(provider,url,key,**kwargs):
            urls.append(url)
            doc=[] if provider=='THE_ODDS_API' else dict(errors={'plan':'Free plan subscription restriction '+SECRET},response={})
            return self.receipt(doc,provider,url)
        bridge=self.access(getter)
        before=self.nba.ledger.path.read_bytes()
        with patch.object(bridge,'storage_status',side_effect=AssertionError('NO_DISK_SCAN')):
            await self.command('/test providers check')
        self.assertEqual(urls,['https://api.the-odds-api.com/v4/sports/','https://v1.basketball.api-sports.io/status'])
        text='\n'.join(self.api.sent)
        self.assertIn('kontrolü başladı',text)
        self.assertIn('SPORTS_CATALOG_RECEIVED',text)
        self.assertIn('PROVIDER_REPORTED_ERROR',text)
        self.assertIn('PLAN_OR_SUBSCRIPTION_RESTRICTION_REPORTED',text)
        self.assertNotIn(SECRET,text);self.assertNotIn('Free plan subscription',text)
        self.assertFalse(self.app.bot_data['last_provider_health']['actual_market_coverage_verified'])
        self.assertEqual(before,self.nba.ledger.path.read_bytes())

    async def test_explicit_check_respects_local_budget_and_invalid_usage_never_queries(self):
        getter=Mock(side_effect=AssertionError('NO_API_QUERY'))
        self.access(getter,max_calls=0)
        await self.command('/test providers check')
        self.assertIn('LOCAL_DAILY_REQUEST_BUDGET','\n'.join(self.api.sent))
        self.api.sent.clear()
        await self.command('/test providers unexpected')
        self.assertIn('Kullanım:','\n'.join(self.api.sent));getter.assert_not_called()

    async def test_slow_storage_times_out_without_starving_next_runtime_command(self):
        asyncio.get_running_loop().set_default_executor(IsolatedExecutor())
        bridge=self.app.bot_data['europe_data_review'].bridge
        release=threading.Event();entered=threading.Event()
        def slow():entered.set();release.wait(3);return {'status':'AVAILABLE','files':0}
        try:
            with (patch.object(bridge,'storage_status',side_effect=slow),
                  patch('hybrid_engine.provider_health.STORAGE_SECONDS',.03)):
                await asyncio.wait_for(self.command('/test data'),1.)
                self.assertTrue(entered.is_set())
                self.assertIn('STORAGE_READ_TIMEOUT','\n'.join(self.api.sent))
                await asyncio.wait_for(self.command('/test runtime'),1.)
                self.assertIn('READ_ONLY_ANALYSIS_RUNTIME_IDENTITY','\n'.join(self.api.sent))
                self.assertFalse(release.is_set())
        finally:release.set()

    async def test_unreadable_or_invalid_storage_preserves_configuration_reply(self):
        bridge=self.access(Mock(side_effect=AssertionError('NO_API_QUERY')))
        for result in (OSError(SECRET),None,dict(status=SECRET,files=3)):
            self.api.sent.clear()
            with patch.object(bridge,'storage_status',side_effect=result if isinstance(result,Exception) else None,
                              return_value=None if isinstance(result,Exception) else result):
                await self.command('/test data')
            text='\n'.join(self.api.sent)
            self.assertIn('THE_ODDS_API: CONFIGURED_NOT_TESTED',text)
            self.assertIn('STORAGE_',text);self.assertNotIn(SECRET,text)

    async def test_probe_timeout_never_starts_next_provider_after_expiration(self):
        release=threading.Event();entered=threading.Event();returned=threading.Event();calls=[]
        def getter(provider,url,key,**kwargs):
            calls.append(provider);entered.set();release.wait(3);returned.set()
            return self.receipt([],provider,url)
        self.access(getter)
        try:
            # Leave the real 50 ms minimum source-call reserve in place;
            # first enter the transport, then prove total-probe cancellation.
            with patch('hybrid_engine.provider_health.PROBE_SECONDS',.2):
                await asyncio.wait_for(self.command('/test providers check'),1.)
            self.assertTrue(entered.is_set())
            self.assertIn('PROBE_TIMEOUT_NOT_VERIFIED','\n'.join(self.api.sent))
            release.set()
            await asyncio.wait_for(asyncio.to_thread(returned.wait,.5),1.)
            await asyncio.sleep(.03)
            self.assertEqual(calls,['THE_ODDS_API'])
        finally:release.set()
