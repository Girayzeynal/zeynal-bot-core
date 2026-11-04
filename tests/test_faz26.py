"""Controlled schema/rate-limit faults and a synthetic prospective end-to-end run."""
import asyncio
from copy import deepcopy
from datetime import datetime,timezone
from email.utils import formatdate
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,MagicMock,Mock,patch

from providers.espn_adapter import ESPNAdapter
from faz25 import directory_codes,BaselineUnavailable,Poller,ProviderCooldown
from faz24 import collect,report
from faz23_engine import Faz23Engine
from providers.espn_bound_results import reconcile_bound_result
from tests import test_faz24 as stage_fixtures
from tests.test_bound_result_pipeline import summary


class HttpAndSchemaTests(unittest.IsolatedAsyncioTestCase):
    def adapter(self,status,headers=None):
        response=SimpleNamespace(status=status,headers=headers or {},json=AsyncMock(return_value={}))
        context=MagicMock();context.__aenter__=AsyncMock(return_value=response)
        session=SimpleNamespace(closed=False,get=Mock(return_value=context))
        return ESPNAdapter(session),session

    async def test_403_stops_repeated_requests(self):
        adapter,session=self.adapter(403)
        with patch('providers.espn_adapter.time.time',return_value=1000):
            self.assertIsNone(await adapter._get_json('https://example.invalid'))
            self.assertIsNone(await adapter._get_json('https://example.invalid'))
        session.get.assert_called_once();self.assertEqual(adapter._blocked_until,1300)

    async def test_429_respects_numeric_and_date_retry_after(self):
        for value in ('180',formatdate(1180,usegmt=True)):
            adapter,session=self.adapter(429,{'Retry-After':value})
            with patch('providers.espn_adapter.time.time',return_value=1000):
                await adapter._get_json('https://example.invalid')
                await adapter._get_json('https://example.invalid')
            self.assertEqual(adapter._blocked_until,1180);session.get.assert_called_once()

    async def test_malformed_retry_after_uses_safe_minimum(self):
        for value in ('invalid','nan','-3'):
            adapter,_=self.adapter(429,{'Retry-After':value})
            with patch('providers.espn_adapter.time.time',return_value=1000):
                await adapter._get_json('https://example.invalid')
            self.assertEqual(adapter._blocked_until,1060)

    async def test_transport_retry_is_bounded(self):
        adapter,session=self.adapter(200);session.get.side_effect=ConnectionError('synthetic')
        with patch('providers.espn_adapter.asyncio.sleep',new=AsyncMock()):
            self.assertIsNone(await adapter._get_json('https://example.invalid'))
        self.assertEqual(session.get.call_count,3)

    async def test_reproduce_unguarded_directory_keyerror_then_fail_closed(self):
        teams=[{'team':{'id':'2'}},{'team':{'id':'18','abbreviation':'NYK'}}]
        with self.assertRaisesRegex(KeyError,'abbreviation'):
            [t['team']['abbreviation'] for t in teams if str(t['team'].get('id'))=='2']
        with self.assertRaises(BaselineUnavailable):
            directory_codes(teams,{'home_team_id':'2','away_team_id':'18'})
        self.assertEqual(directory_codes([{'team':{'id':'2','abbreviation':'BOS'}},teams[1]],
                         {'home_team_id':'2','away_team_id':'18'}),{'home':'BOS','away':'NYK'})


class ProspectiveChainTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.setup=stage_fixtures.Faz24Tests();await self.setup.asyncSetUp()
        self.addCleanup(self.setup.doCleanups)
        self.fx=self.setup.fixture
        self.addCleanup(self.fx.folder.cleanup)
        self.fx.fixture['provider_fixture_id']='99001'
        self.poller=Poller(self.fx.ledger.db_path,lead_seconds=86400)
        self.board={'events':[dict(id='99001',date=datetime.fromtimestamp(self.fx.tipoff,timezone.utc).isoformat(),
            competitions=[dict(id='99001',date=datetime.fromtimestamp(self.fx.tipoff,timezone.utc).isoformat(),
            status={'type':{'state':'pre','completed':False}},competitors=[
            {'homeAway':'home','team':{'id':'2'}},{'homeAway':'away','team':{'id':'18'}}])])]}
        self.schedule=AsyncMock(return_value=[self.board])

    async def test_dry_run_changes_no_predictions_or_attempts(self):
        before=Path(self.fx.ledger.db_path).read_bytes()
        collection=AsyncMock();reconcile=AsyncMock()
        result=await self.poller.tick(schedule=self.schedule,collect=collection,reconcile=reconcile,dry_run=True)
        self.assertEqual(result['status'],'dry_run')
        self.assertEqual(before,Path(self.fx.ledger.db_path).read_bytes())
        collection.assert_not_awaited();reconcile.assert_not_awaited()

    async def test_schedule_to_final_to_metrics_preserves_original_stages(self):
        engine=SimpleNamespace(run_prematch=AsyncMock(return_value=deepcopy(self.fx.core)))
        finalizer=Faz23Engine(str(Path(self.fx.folder.name)/'e2e.sqlite'))
        async def generate(row):
            return await collect(engine=engine,request=self.fx.request,adapter=self.fx.adapter,
                ledger=self.fx.ledger,model_version='e'*40,finalizer=finalizer,expected_fixture=row)
        await self.poller.tick(schedule=self.schedule,collect=generate,reconcile=AsyncMock())
        with self.fx.ledger._connect() as db:
            before=db.execute('SELECT payload,sha256 FROM faz24_stages').fetchall()
        final=summary(self.fx.tipoff,source_id='99001')
        final['header']['competitions'][0]['competitors'][0]['team']['id']='2'
        final['header']['competitions'][0]['competitors'][1]['team']['id']='18'
        self.fx.adapter._get_json=AsyncMock(return_value=final)
        async def reconcile(fixture):
            return await reconcile_bound_result(adapter=self.fx.adapter,ledger=self.fx.ledger,fixture_id=fixture)
        with patch('time.time',return_value=self.fx.tipoff+7200):
            await self.poller.tick(schedule=AsyncMock(return_value=[{'events':[]}]),collect=AsyncMock(),reconcile=reconcile)
            result=report(self.fx.ledger.db_path)
        self.assertEqual(result['prospective']['sample_size'],1)
        self.assertEqual(result['prospective']['metrics']['n_games'],1)
        self.assertIsNone(result['prospective']['metrics']['home_win_brier'])
        self.assertEqual(result['prospective']['calibration_status'],'NOT_ESTABLISHED')
        with self.fx.ledger._connect() as db:
            self.assertEqual(before,db.execute('SELECT payload,sha256 FROM faz24_stages').fetchall())
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(),('ok',))

    async def test_persistent_cooldown_honors_provider_delay(self):
        self.schedule.side_effect=ProviderCooldown(3600)
        await self.poller.tick(schedule=self.schedule,collect=AsyncMock(),reconcile=AsyncMock())
        with self.fx.ledger._connect() as db:
            next_utc=db.execute("SELECT next_utc FROM faz25_attempts WHERE task='schedule'").fetchone()[0]
        import time
        self.assertGreaterEqual(next_utc,int(time.time())+3599)
