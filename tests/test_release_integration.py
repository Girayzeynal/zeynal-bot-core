"""Release behavior with synthetic native sources and isolated legacy ledgers."""
import asyncio
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime,timezone
import importlib
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase,TestCase
from unittest.mock import AsyncMock,Mock,patch

from core.team_identity import digest
from live_analysis_ledger import LiveAnalysisLedger
from prediction_ledger import PredictionLedger,PredictionRecord,OutcomeRecord
from verified_analysis import VerifiedAnalyzeService,project_scores,MODEL_DIGEST
from verified_history import nba_history
from season_archive_inventory import archive_catalog
from tests.test_season_archive_audit import nba,euro,NOW
from tests.test_universal_analysis import fetcher,games,response


def live_payload(start=NOW+3600):
    return dict(record_type='LIVE_PREMATCH_PREDICTION',evaluation_class='LIVE_RECORDED',actual=None,
        league='NBA',season='2026/2027',fixture_id='CANONICAL',provider_fixture_ids=['401000123'],fixture_start_utc=start,
        model_version='SYNTHETIC_ONLY',model_digest=MODEL_DIGEST,prediction={'home':110,'away':100,'tuple':(1,2)},
        input_clocks=[dict(observed_at_utc=NOW-2,ingested_at_utc=NOW-1)],
        home=dict(provider_id='1'),away=dict(provider_id='2'))


def nba_fetcher():
    base=fetcher('NBA')
    def fetch(provider,url):
        if '/schedule?' in url:
            tid=url.split('/teams/')[1].split('/')[0];events=[]
            for i in range(8):
                e=nba(str(401000000+i));e['competitions'][0]['id']=e['id'];e['date']=f'2026-10-{10+i:02d}T18:00:00Z'
                e['seasonType']={'type':2}
                for t in e['competitions'][0]['competitors']:
                    t['score']={'value':int(t['score']),'displayValue':t['score']};t.pop('linescores')
                events.append(e)
            return response(provider,url,dict(team={'id':tid},season={'year':2027,'type':2},events=events))
        if '/summary?' in url:
            pid=url.split('event=')[1];i=int(pid)-401000000;e=nba(pid);e['competitions'][0]['id']=pid
            e['date']=f'2026-10-{10+i:02d}T18:00:00Z';e['competitions'][0]['date']=e['date']
            # Keep variation real in the synthetic source, not a fixed SD fallback.
            for t in e['competitions'][0]['competitors']:
                t['linescores'][0]['value']+=i;t['score']=str(int(t['score'])+i)
                t['linescores']=[dict(displayValue=str(p['value'])) for p in t['linescores']]
            return response(provider,url,{'header':e})
        return base(provider,url)
    # Schedule scores must agree with the same synthetic summary observations.
    def consistent(provider,url):
        r=fetch(provider,url)
        if '/schedule?' in url:
            for i,e in enumerate(r['document']['events']):
                for t in e['competitions'][0]['competitors']:
                    v=int(t['score']['value'])+i;t['score']={'value':v,'displayValue':str(v)}
            r['document_sha256']=digest(r['document'])
        return r
    return Mock(side_effect=consistent)


class AtomicLiveLedgerTests(TestCase):
    def setUp(self):
        clock=patch('time.time',return_value=NOW);clock.start();self.addCleanup(clock.stop)
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'ledger.sqlite';self.ledger=LiveAnalysisLedger(self.path)

    def test_json_stable_first_commit_retry_and_sql_immutability(self):
        first,new=self.ledger.commit(live_payload());second,created=self.ledger.commit(live_payload())
        self.assertTrue(new);self.assertFalse(created);self.assertEqual(first,second)
        self.assertEqual(first['prediction']['tuple'],[1,2])
        with sqlite3.connect(self.path) as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM live_analysis_snapshots')
        self.assertEqual(self.ledger.integrity()['snapshots'],1)

    def test_exact_tipoff_and_clock_crossing_transaction_rollback(self):
        with self.assertRaisesRegex(ValueError,'BEFORE_ATOMIC'):self.ledger.commit(live_payload(NOW))
        with patch('time.time',side_effect=[NOW,NOW,NOW+1]):
            with self.assertRaisesRegex(ValueError,'DURING_ATOMIC'):self.ledger.commit(live_payload(NOW+1))
        self.assertEqual(self.ledger.integrity()['snapshots'],0)

    def test_locked_database_fails_without_any_partial_prediction(self):
        db=sqlite3.connect(self.path);db.execute('BEGIN IMMEDIATE')
        try:
            with self.assertRaises(sqlite3.OperationalError):self.ledger.commit(live_payload())
        finally:db.rollback();db.close()
        self.assertEqual(self.ledger.integrity()['snapshots'],0)

    def test_production_mode_never_creates_a_replacement_or_accepts_foreign_schema(self):
        missing=Path(self.tmp.name)/'missing.sqlite'
        with self.assertRaises(sqlite3.OperationalError):LiveAnalysisLedger(missing,require_legacy=True)
        self.assertFalse(missing.exists())
        foreign=Path(self.tmp.name)/'foreign.sqlite'
        with sqlite3.connect(foreign) as db:db.execute('CREATE TABLE unrelated(x)')
        before=foreign.read_bytes()
        with self.assertRaisesRegex(ValueError,'PRODUCTION_LEDGER_SCHEMA'):LiveAnalysisLedger(foreign,require_legacy=True)
        self.assertEqual(before,foreign.read_bytes())

    def test_research_record_cannot_be_written_to_live_archive(self):
        p=live_payload();p['record_type']='BACKTEST_SIMULATION'
        with self.assertRaisesRegex(ValueError,'TYPE_BINDING'):self.ledger.commit(p)
        self.assertEqual(self.ledger.integrity()['snapshots'],0)

    def test_200444_start_200512_commit_is_missed_cut_not_live_success(self):
        base=int(datetime(2026,11,5,20,tzinfo=timezone.utc).timestamp())
        p=live_payload(base+6*3600);p['record_deadline_utc']=base+300
        p['input_clocks']=[dict(observed_at_utc=base+280,ingested_at_utc=base+281)]
        confirm=self.ledger._confirm_commit
        def slow_commit(saved):
            with patch('time.time',return_value=base+312):return confirm(saved)
        with patch('time.time',return_value=base+284),patch.object(self.ledger,'_confirm_commit',side_effect=slow_commit):
            with self.assertRaisesRegex(ValueError,'MISSED_CUT'):self.ledger.commit(p)
        audit=self.ledger.integrity()
        self.assertEqual(audit['snapshots'],0);self.assertEqual(audit['unconfirmed_snapshots'],1)
        self.assertEqual(self.ledger.commit_proofs(),[])

    def test_restart_confirms_only_before_original_deadline_without_rewriting_prediction(self):
        p=live_payload()
        with patch.object(self.ledger,'_confirm_commit',side_effect=OSError('crash after durable snapshot')):
            with self.assertRaises(OSError):self.ledger.commit(p)
        self.assertEqual(self.ledger.integrity()['unconfirmed_snapshots'],1)
        with patch('time.time',return_value=NOW+10):saved=self.ledger.get(p['league'],p['fixture_id'],p['model_digest'])
        self.assertEqual(saved['created_at_utc'],NOW)
        self.assertEqual(self.ledger.integrity()['snapshots'],1)
        self.assertEqual(self.ledger.commit_proofs()[0]['completed_utc'],NOW+10)

    def test_concurrent_same_match_records_exactly_once(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as pool:values=list(pool.map(lambda _:self.ledger.commit(live_payload()),range(4)))
        self.assertEqual(sum(new for p,new in values),1)
        self.assertTrue(all(p==values[0][0] for p,new in values))

    def test_legacy_rows_and_schemas_remain_unchanged_after_additive_tables(self):
        p=Path(self.tmp.name)/'legacy.sqlite';legacy=PredictionLedger(str(p))
        legacy.record_prediction(PredictionRecord('old','NBA',NOW-10000,110,100,None))
        legacy.record_outcome(OutcomeRecord('old','NBA',NOW-1000,112,102))
        with sqlite3.connect(p) as db:
            before=[db.execute('SELECT * FROM '+table).fetchall() for table in ('predictions','outcomes')]
            schema=[db.execute("SELECT sql FROM sqlite_master WHERE name=?",(table,)).fetchone() for table in ('predictions','outcomes')]
        added=LiveAnalysisLedger(p);added.commit(live_payload())
        with sqlite3.connect(p) as db:
            self.assertEqual(before,[db.execute('SELECT * FROM '+table).fetchall() for table in ('predictions','outcomes')])
            self.assertEqual(schema,[db.execute("SELECT sql FROM sqlite_master WHERE name=?",(table,)).fetchone() for table in ('predictions','outcomes')])

    def test_final_results_separate_idempotent_and_no_future_or_nonfinal_result(self):
        e=nba();e['date']='2026-11-11T17:00:00Z'
        # Snapshot is genuinely before its future fixture; final observed later.
        p=live_payload(NOW+3600)
        with patch('time.time',return_value=NOW+10000):
            b=archive_catalog({'events':[e]},provider='ESPN',observed_at_utc=NOW+7200,ingested_at_utc=NOW+7200)
        p['fixture_id']=b['payload']['fixtures'][0]['canonical_id']
        saved,_=self.ledger.commit(p)
        with patch('time.time',return_value=NOW+10000):
            unfinished=deepcopy(e)
            for status in (unfinished['status'],unfinished['competitions'][0]['status']):
                status['type'].update(state='pre',completed=False,name='STATUS_SCHEDULED')
            pending=archive_catalog({'events':[unfinished]},provider='ESPN',observed_at_utc=NOW+7200,ingested_at_utc=NOW+7200)
            self.assertEqual(self.ledger.reconcile(pending,trusted_sha256=pending['sha256']),0)
            self.assertEqual(self.ledger.reconcile(b,trusted_sha256=b['sha256']),1)
            self.assertEqual(self.ledger.reconcile(b,trusted_sha256=b['sha256']),0)
        self.assertEqual(self.ledger.get('NBA',p['fixture_id'],MODEL_DIGEST),saved)


class ReleaseCommandTests(IsolatedAsyncioTestCase):
    def setUp(self):
        clock=patch('time.time',return_value=NOW);clock.start();self.addCleanup(clock.stop)
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.ledger=LiveAnalysisLedger(Path(self.tmp.name)/'live.sqlite')

    async def test_euroleague_produces_scores_without_espn_or_fabricated_pace(self):
        fetch=fetcher();s=VerifiedAnalyzeService(self.ledger,fetch)
        r=await s.analyze('EUROLEAGUE','2026-11-11','Paris Basketball','Fenerbahçe Beko')
        self.assertEqual(r['status'],'ANALYSIS_OK');self.assertIn('40 dk',r['html'])
        self.assertIn('Tempo, kadro',r['html']);self.assertNotIn('48 dk',r['html'])
        p=r['snapshot']['prediction'];self.assertAlmostEqual(sum(p['quarters']['home']),p['home'])
        self.assertTrue(all(c.args[0]=='EUROLEAGUE_LIVE' for c in fetch.call_args_list))
        again=await s.analyze('EL','2026-11-11','Paris Basketball','Fenerbahce Beko')
        self.assertEqual(r['snapshot'],again['snapshot']);self.assertFalse(again['new_record'])

    async def test_nba_native_schedule_summary_and_10000_simulations(self):
        s=VerifiedAnalyzeService(self.ledger,nba_fetcher())
        r=await s.analyze('NBA','2026-11-11','SH','Synthetic Bears')
        self.assertEqual(r['status'],'ANALYSIS_OK',r.get('html'))
        self.assertEqual(r['snapshot']['prediction']['simulation']['simulations'],10000)
        self.assertIn('48 dk',r['html']);self.assertIn('10,000',r['html'])

    async def test_official_fixture_changed_or_started_while_model_runs_never_archives(self):
        source=fetcher();calls=0
        def moving(provider,url):
            nonlocal calls
            r=source(provider,url)
            if url.endswith('/games'):
                calls+=1
                if calls>1:
                    for g in r['document']['data']:
                        if not g['played']:g['utcDate']='2026-11-12T20:00:00Z'
                    r['document_sha256']=digest(r['document'])
            return r
        r=await VerifiedAnalyzeService(self.ledger,moving).analyze('EL','2026-11-11','Paris Basketball','Fenerbahce Beko')
        self.assertEqual(r['status'],'ABSTAIN');self.assertEqual(self.ledger.integrity()['snapshots'],0)

    async def test_source_403_and_missing_archive_and_unsupported_league_do_not_make_forecast(self):
        r=await VerifiedAnalyzeService(self.ledger,Mock(return_value={'status':'SOURCE_ACCESS_DENIED'})).analyze('EL','2026-11-11','Paris Basketball','Baskonia')
        self.assertEqual(r['status'],'ABSTAIN');self.assertIn('SOURCE_ACCESS_DENIED',r['html'])
        r=await VerifiedAnalyzeService(None,fetcher()).analyze('EL','2026-11-11','Paris Basketball','Fenerbahce Beko')
        self.assertIn('ARCHIVE_UNAVAILABLE',r['html'])
        fetch=Mock(side_effect=AssertionError('NO_WRONG_PROVIDER'))
        r=await VerifiedAnalyzeService(self.ledger,fetch).analyze('EUROCUP','2026-11-11','Any','Other')
        self.assertIn('LEAGUE_MODEL_NOT_CONFIGURED',r['html']);fetch.assert_not_called()

    async def test_actual_analyze_handler_format_and_free_nba_handler_route(self):
        with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'123456:SYNTHETIC','API_SPORTS_KEY':''}):app=importlib.import_module('main')
        s=VerifiedAnalyzeService(self.ledger,fetcher());reply=AsyncMock()
        msg=SimpleNamespace(text='/analyze EUROLEAGUE 2026-11-11 Paris Basketball vs Fenerbahçe Beko',reply_text=reply)
        ctx=SimpleNamespace(application=SimpleNamespace(bot_data={'verified_analysis_service':s}))
        await app.analyze_command(SimpleNamespace(message=msg),ctx)
        self.assertIn('MAÇ ÖNCESİ ANALİZ',reply.call_args.args[0]);self.assertEqual(reply.call_args.kwargs['parse_mode'],'HTML')
        self.assertLess(len(reply.call_args.args[0]),4096)
        from nba_command import nba_command
        loader=AsyncMock(return_value=[])
        ctx=SimpleNamespace(args=[],application=SimpleNamespace(bot_data={'nba_fixture_loader':loader}))
        with patch('nba_command.load_nba_games',side_effect=AssertionError('PAID_PROVIDER_NOT_ALLOWED')):
            await nba_command(SimpleNamespace(effective_message=msg),ctx)
        loader.assert_awaited_once()

    async def test_default_runtime_never_enables_legacy_paid_scheduler(self):
        with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'123456:SYNTHETIC','ENABLE_LEGACY_SCHEDULER':'0'}):
            app=importlib.import_module('main')
            with patch('dynamic_scheduler.scheduler_loop',new_callable=AsyncMock) as legacy:
                with self.assertRaises(asyncio.TimeoutError):await asyncio.wait_for(app.scheduler_loop({}),timeout=.01)
                legacy.assert_not_awaited()

    async def test_unknown_production_release_sha_never_opens_database_or_calls_source(self):
        from verified_analysis import production_service
        with patch.dict(os.environ,{'ZEYNAL_RELEASE_SHA':'UNKNOWN'}),patch('verified_analysis.LiveAnalysisLedger',side_effect=AssertionError('NO_DATABASE')):
            s=production_service()
            r=await s.analyze('NBA','2026-11-11','Any','Other')
        self.assertEqual(r['status'],'ABSTAIN');self.assertIn('RELEASE_SHA_NOT_CONFIGURED',r['html'])

    async def test_source_cache_is_bounded_and_expired_documents_are_not_reused(self):
        source=Mock(side_effect=lambda provider,url:response(provider,url,{'data':'x'*100}))
        s=VerifiedAnalyzeService(self.ledger,source)
        for i in range(40):s.fetch('ESPN','https://example.invalid/'+str(i))
        self.assertLessEqual(len(s.cache),32);self.assertLessEqual(sum(s.cache_sizes.values()),16*1024*1024)
        before=source.call_count
        with patch('time.time',return_value=NOW+241):s.fetch('ESPN','https://example.invalid/39')
        self.assertEqual(source.call_count,before+1)
