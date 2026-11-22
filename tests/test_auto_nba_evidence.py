"""One Telegram /analyze drives an automatic, bounded, source-labeled sidecar.

Manufactured fixtures and stubbed source/Telegram calls: NEVER real results.
"""
import asyncio
from tempfile import TemporaryDirectory
import time
from unittest import IsolatedAsyncioTestCase,TestCase
from unittest.mock import AsyncMock

from core.team_identity import digest
from hybrid_engine.auto_nba_evidence import (
    admission,collect_auto,render_auto,send_auto,schedule_auto)


def fixture(start):
    return dict(league='NBA',season='2026/2027',fixture_id='TEST-ONLY-FIXTURE',
        provider_fixture_ids=['401000111'],fixture_start_utc=start,
        prediction_generated_at_utc=start-3600,model_digest='c'*64,
        home=dict(provider_id='1',official_name='Test Home'),
        away=dict(provider_id='2',official_name='Test Away'),
        prediction=dict(home=100,away=95))


class FakeReviewer:
    def __init__(self):
        self.calls=0
    def review(self,ctx):
        self.calls+=1
        return dict(fixture_id=ctx['fixture_id'],
            fixture_start_utc=ctx['fixture_start_utc'],
            original_snapshot_sha256=ctx['original_snapshot_sha256'],
            observed_at_utc=int(time.time()),status='CURRENT_SOURCE_OBSERVATIONS',
            records=[],sources=[],warnings=[],official_code='ROSTER_SOURCE_UNAVAILABLE')


class AutonomousEvidenceTests(IsolatedAsyncioTestCase):
    async def test_one_command_drives_reviewer_and_actual_input_collector(self):
        snap=fixture(int(time.time())+3600)
        reviewer=FakeReviewer();calls=[]
        def collector(snapshot,assets,directory,*,reviewer):
            calls.append((snapshot['fixture_id'],str(directory),reviewer.calls))
            return dict(status='BLOCKED',reason='ABSENCE_REQUIRES_BOTH_SOURCE_OBSERVATIONS',
                        forecast_changed=False,production_changed=False,projection=None)
        with TemporaryDirectory() as tmp:
            result=await collect_auto(snap,reviewer,tmp,tmp,input_call=collector)
            self.assertEqual(reviewer.calls,1)
            self.assertEqual(len(calls),1)
            self.assertEqual(result['player_input_status'],'BLOCKED')
            self.assertEqual(result['player_input_reason'],
                             'ABSENCE_REQUIRES_BOTH_SOURCE_OBSERVATIONS')
            self.assertEqual(result['status'],'ROSTER_OBSERVED')
            self.assertFalse(result['model_coefficients_applied'])
            self.assertFalse(result['forecast_changed'])
            self.assertIn('BU ANALİZDE AKTİF DEĞİL',render_auto(result))
            bot=type('Bot',(),{'send_message':AsyncMock()})()
            await send_auto(bot,123,result)
            self.assertGreaterEqual(bot.send_message.await_count,2)
            self.assertTrue(all(k.kwargs['chat_id']==123
                                for k in bot.send_message.await_args_list))

    async def test_no_pretipoff_backfill_and_no_fetch_after_tipoff(self):
        snap=fixture(int(time.time())-20)
        reviewer=FakeReviewer()
        result=await collect_auto(snap,reviewer,None,None)
        self.assertEqual(result['reason'],'MATCH_ALREADY_STARTED_NO_PREMATCH_BACKFILL')
        self.assertEqual(reviewer.calls,0)
        self.assertEqual(result['player_input_status'],'NOT_ATTEMPTED')

    async def test_missing_review_keeps_player_evidence_separately_unverified(self):
        snap=fixture(int(time.time())+3600)
        def bad(ctx): raise ValueError('secret never echoed')
        def blocked(snapshot,assets,directory,*,reviewer):
            return dict(status='BLOCKED',reason='CURRENT_ROSTER_SOURCE_REVIEW_REQUIRED',
                        forecast_changed=False,production_changed=False,projection=None)
        with TemporaryDirectory() as tmp:
            value=await collect_auto(snap,FakeReviewer(),tmp,tmp,
                                     review_call=bad,input_call=blocked)
        self.assertEqual(value['status'],'ROSTER_UNAVAILABLE')
        self.assertEqual(value['player_input_status'],'BLOCKED')
        self.assertNotIn('secret',render_auto(value))

    async def test_automated_post_delivery_followup_deduplicates_without_global_ban(self):
        snap=fixture(int(time.time())+3600)
        reviewer=FakeReviewer()
        class App:
            def __init__(self):
                self.bot_data=dict(auto_nba_player_pipeline=dict(
                    reviewer=reviewer,assets=None,directory=None,chat_id=123,
                    cooldown_seconds=300))
                self.bot=type('Bot',(),{'send_message':AsyncMock()})()
                self.tasks=[]
            def create_task(self,coroutine):
                task=asyncio.create_task(coroutine)
                self.tasks.append(task)
                return task
        app=App()
        report=dict(status='ANALYSIS_OK',snapshot=snap,new_record=True)
        self.assertTrue(schedule_auto(app,'NBA',report,123))
        self.assertFalse(schedule_auto(app,'NBA',report,123))
        await asyncio.gather(*app.tasks)
        self.assertEqual(reviewer.calls,1)
        self.assertGreaterEqual(app.bot.send_message.await_count,1)
        self.assertFalse(schedule_auto(app,'EUROLEAGUE',report,123))
        self.assertFalse(schedule_auto(app,'NBA',report,999))
        self.assertFalse(schedule_auto(app,'NBA',dict(status='ABSTAIN'),123))
        self.assertFalse(schedule_auto(app,'NBA',
            dict(status='ANALYSIS_OK',snapshot=fixture(int(time.time())-10)),123))

    async def test_snapshot_binding_conflict_cannot_be_presented_as_verified_roster(self):
        snap=fixture(int(time.time())+3600)
        def wrong(ctx):
            return dict(fixture_id=ctx['fixture_id'],
                original_snapshot_sha256='f'*64,fixture_start_utc=ctx['fixture_start_utc'])
        with TemporaryDirectory() as tmp:
            result=await collect_auto(snap,FakeReviewer(),tmp,tmp,
                                      review_call=wrong,input_call=lambda *a,**k:dict(
                                      status='BLOCKED',reason='SOURCE_UNAVAILABLE',
                                      forecast_changed=False,production_changed=False))
        self.assertEqual(result['status'],'ROSTER_UNAVAILABLE')
        self.assertIsNone(result['roster_report'])


class AdmissionTests(TestCase):
    def test_strict_fixture_identity(self):
        self.assertEqual(admission(fixture(int(time.time())+3600),int(time.time())),
                         'FUTURE_FIXTURE_VERIFIED_CONTEXT')
        invalid=fixture(int(time.time())+3600)
        invalid['provider_fixture_ids']=['bad-id']
        self.assertEqual(admission(invalid,int(time.time())),
                         'SNAPSHOT_OR_SOURCE_IDENTITY_UNVERIFIED')
