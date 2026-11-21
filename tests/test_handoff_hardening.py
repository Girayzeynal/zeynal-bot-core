"""Regression tests for real refusal root cause, settlement and isolated routing."""
import asyncio
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase,TestCase
from unittest.mock import AsyncMock,Mock,patch

from core.team_identity import digest
from hybrid_engine.fixture_rejection_diagnostic import enrich_fixture_rejection,render_fixture_rejection
from hybrid_engine.fixture_menu import nba_blocks,euroleague_blocks
from hybrid_engine.forward_validation import ForwardRegistry
from hybrid_engine.live_metrics import metrics
from hybrid_engine.nba_ledger_settlement import settle
from hybrid_engine.result_poll import poll_once
from ledger_reports import compare_command,LedgerReports
from live_analysis_ledger import LiveAnalysisLedger
from season_archive_inventory import archive_catalog
from tests.test_release_integration import live_payload
from tests.test_season_archive_audit import nba,NOW,START


def receipt(document,url,provider='ESPN',clock=NOW):
    return dict(provider=provider,source_url=url,status='DOCUMENT_RECEIVED',http_status=200,
        observed_at_utc=clock-1,ingested_at_utc=clock,document=document,document_sha256=digest(document))


def snapshot_ledger(path,events):
    ledger=LiveAnalysisLedger(path)
    with patch('time.time',return_value=NOW):
        c=archive_catalog({'events':events},provider='ESPN',observed_at_utc=NOW-1,ingested_at_utc=NOW)
    for g in c['payload']['fixtures']:
        p=live_payload(START);p.update(fixture_id=g['canonical_id'],scope='REGULATION_ONLY',
            model_digest='a'*64,prediction_generated_at_utc=START-101,
            input_clocks=[dict(observed_at_utc=START-103,ingested_at_utc=START-102)])
        p['home']['provider_id']=g['home_team_id'];p['away']['provider_id']=g['away_team_id']
        p['provider_fixture_ids']=g['provider_fixture_ids']
        with patch('time.time',return_value=START-100):ledger.commit(p)
    return ledger


class FixtureDiagnostics(IsolatedAsyncioTestCase):
    def source(self,*,reverse=True,late=False):
        event=nba();event['date']='2026-11-15T18:00:00Z'
        event['status']=event['competitions'][0]['status']={'type':dict(name='STATUS_FINAL' if late else 'STATUS_SCHEDULED',state='post' if late else 'pre',completed=late)}
        for t in event['competitions'][0]['competitors']:
            t['team']['displayName']='Philadelphia 76ers' if t['homeAway']=='home' else 'Indiana Pacers'
        report=dict(reason='FIXTURE_NOT_UNIQUELY_VERIFIED',season_id='2026/2027',home={'provider_id':'2' if reverse else '1'},away={'provider_id':'1' if reverse else '2'})
        now=int(datetime(2026,11,15,11,tzinfo=timezone.utc).timestamp())
        return event,report,now

    async def test_reversed_home_away_suggests_correct_command_without_retry(self):
        e,r,now=self.source()
        with patch('time.time',return_value=now):
            result=await enrich_fixture_rejection(r,'2026-11-15',lambda p,u:receipt({'events':[e]},u,clock=now))
        d=result['fixture_diagnostic'];self.assertFalse(d['prediction_allowed']);self.assertEqual(d['matched_count'],0)
        text=render_fixture_rejection(result)
        self.assertIn('sırası ters',text);self.assertIn('/analyze NBA 2026-11-15 Philadelphia 76ers vs Indiana Pacers',text)
        self.assertIn('21:00',text);self.assertIn('18:00',text)

    async def test_started_fixture_never_suggests_prematch(self):
        e,r,now=self.source(late=True);now+=86400
        with patch('time.time',return_value=now):
            result=await enrich_fixture_rejection(r,'2026-11-15',lambda p,u:receipt({'events':[e]},u,clock=now))
        self.assertIsNone(result['fixture_diagnostic']['nearby'][0]['suggested_command'])

    async def test_wrong_date_suggests_turkey_calendar_day_only(self):
        e,r,now=self.source(reverse=False);e['date']='2026-11-16T00:00:00Z'
        with patch('time.time',return_value=now):
            result=await enrich_fixture_rejection(r,'2026-11-15',lambda p,u:receipt({'events':[e]},u,clock=now))
        self.assertIn('/analyze NBA 2026-11-16',render_fixture_rejection(result))
        self.assertFalse(result['fixture_diagnostic']['prediction_allowed'])

    async def test_bad_source_is_not_presented_as_no_matching_fixture(self):
        e,r,now=self.source()
        with patch('time.time',return_value=now):
            result=await enrich_fixture_rejection(r,'2026-11-15',lambda p,u:receipt({'events':[e]},'https://wrong',clock=now))
        self.assertEqual(result['fixture_diagnostic']['status'],'SOURCE_UNAVAILABLE')
        self.assertNotIn('/analyze NBA',render_fixture_rejection(result))

    async def test_non_fixture_error_never_downloads(self):
        fetch=Mock(side_effect=AssertionError('download'))
        r={'reason':'HISTORICAL_PIT_SNAPSHOT_REQUIRED'}
        self.assertEqual(await enrich_fixture_rejection(r,'2026-11-15',fetch),r)

    def test_phone_fixture_list_only_recommends_future_scheduled_matches(self):
        start=datetime.fromtimestamp(NOW+3600,timezone.utc)
        games=[dict(start=start,home='Home <A>',away='Away',status='Başlamadı',id='123')]
        with patch('time.time',return_value=NOW):text='\n'.join(nba_blocks(games,'2026-11-11'))
        self.assertIn('ESPN 123',text);self.assertIn('/analyze NBA',text);self.assertIn('&lt;A&gt;',text)
        games[0]['status']='Canlı'
        self.assertNotIn('/analyze NBA','\n'.join(nba_blocks(games,'2026-11-11')))


class SettlementSafety(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.events=[nba('401000123'),nba('401000124')]
        for i,t in enumerate(self.events[1]['competitions'][0]['competitors']):t['team']['id']=str(i+3)
        self.ledger=snapshot_ledger(Path(self.tmp.name)/'nba.sqlite',self.events)
        self.clock=patch('time.time',return_value=NOW);self.clock.start();self.addCleanup(self.clock.stop)

    def fetch(self,p,u):return receipt({'events':self.events},u)

    def test_multiple_games_and_repeated_polls_preserve_forecasts(self):
        before=self.ledger.commit_proofs()
        self.assertEqual(settle(self.ledger,fetcher=self.fetch)['settled'],2)
        self.assertEqual(settle(self.ledger,fetcher=self.fetch)['settled'],0)
        self.assertEqual(self.ledger.commit_proofs(),before)
        self.assertEqual(self.ledger.integrity()['verified_results'],2)

    def test_bad_provider_url_digest_and_stale_clock_refused_before_write(self):
        for change in ({'source_url':'wrong'},{'provider':'OTHER'},{'document_sha256':'0'*64},{'observed_at_utc':NOW-500}):
            with self.subTest(change=change):
                def fetch(p,u):return dict(self.fetch(p,u),**change)
                with self.assertRaises(ValueError):settle(self.ledger,fetcher=fetch)
                self.assertEqual(self.ledger.integrity()['verified_results'],0)

    def test_wrong_home_away_conflict_does_not_write(self):
        self.events[0]['competitions'][0]['competitors'].reverse()
        for t in self.events[0]['competitions'][0]['competitors']:
            t['homeAway']='away' if t['homeAway']=='home' else 'home'
        # Identity produces a different canonical fixture, so no false match.
        settle(self.ledger,fetcher=self.fetch)
        self.assertEqual(self.ledger.integrity()['verified_results'],1)

    def test_missing_periods_stay_pending(self):
        for e in self.events:
            for t in e['competitions'][0]['competitors']:t.pop('linescores')
        settle(self.ledger,fetcher=self.fetch)
        self.assertEqual(self.ledger.integrity()['verified_results'],0)

    def test_future_snapshots_trigger_no_network_requests(self):
        fetch=Mock(side_effect=AssertionError('network'))
        with patch('time.time',return_value=START-1):r=settle(self.ledger,fetcher=fetch)
        self.assertEqual(r['due'],0);fetch.assert_not_called()

    def test_source_failures_are_visible_as_incomplete(self):
        r=settle(self.ledger,fetcher=lambda p,u:dict(status='SOURCE_NETWORK_ERROR'))
        self.assertEqual(r['status'],'SOURCE_INCOMPLETE');self.assertEqual(r['pending'],2)

    def test_overtime_is_excluded_from_regulation_performance(self):
        for e in self.events:
            for t in e['competitions'][0]['competitors']:
                t['linescores']=[dict(value=25)]*4+[dict(value=8 if t['homeAway']=='home' else 5)]
                t['score']='108' if t['homeAway']=='home' else '105'
        settle(self.ledger,fetcher=self.fetch)
        r=LedgerReports(self.ledger.path).read('NBA')
        self.assertTrue(all(row['actual']==[100,100] for row in r['forecasts']))
        self.assertTrue(all(row['final_with_ot']==[108,105] for row in r['forecasts']))


class PollAndCompare(IsolatedAsyncioTestCase):
    async def test_euroleague_failure_does_not_starve_nba_or_leak_exception(self):
        journal=SimpleNamespace(append=Mock())
        failed=Mock(side_effect=ValueError('secret/token'));nba_job=Mock(return_value={'settled':1})
        r=await poll_once([('EUROLEAGUE',failed),('NBA',nba_job)],journal)
        self.assertEqual(r['EUROLEAGUE']['status'],'FAILED');self.assertEqual(r['NBA']['result']['settled'],1)
        self.assertNotIn('secret',str(journal.append.call_args))

    async def test_compare_database_failure_returns_controlled_response(self):
        message=SimpleNamespace(reply_text=AsyncMock())
        service=SimpleNamespace(read=Mock(side_effect=sqlite3.OperationalError('locked')))
        ctx=SimpleNamespace(args=['NBA'],application=SimpleNamespace(bot_data={'ledger_reports':service}))
        await compare_command(SimpleNamespace(effective_message=message),ctx)
        self.assertIn('Arşiv doğrulanamadı',message.reply_text.call_args.args[0])


class LiveMetricTests(TestCase):
    def row(self):
        q=[[25,25]]*4
        return dict(actual=[100,100],prediction=[104,96],predicted_quarters=[[26,24]]*4,
            actual_periods={'home':[25]*4+[9],'away':[25]*4+[6]},winner=[.4,.2,.4],
            fixture_start_utc=START,intervals=None)

    def test_raw_probabilities_treat_regulation_tie_as_separate_outcome(self):
        r=metrics([self.row()]);self.assertAlmostEqual(r['winner']['brier'],.96)
        self.assertAlmostEqual(r['winner']['log_loss'],-__import__('math').log(.2))
        self.assertEqual(r['periods']['1Q']['mae'],1);self.assertEqual(r['halves']['1H']['mae'],2)
        self.assertEqual(r['total']['mae'],0);self.assertEqual(r['team_scores']['mae'],4)
        self.assertIsNone(r['confidence_index']);self.assertFalse(r['calibration_fit'])

    def test_incoherent_periods_and_invalid_probabilities_fail_closed(self):
        for changes in ({'predicted_quarters':[[26,26]]*4},{'winner':[.8,.1,.5]}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):metrics([dict(self.row(),**changes)])

    def test_missing_probabilities_are_not_filled(self):
        r=metrics([dict(self.row(),winner=None,predicted_quarters=None)])
        self.assertNotIn('winner',r);self.assertEqual(r['periods'],{})

class RecordedNativeEvidenceTests(TestCase):
    def test_real_indiana_philadelphia_refusal_is_explained_by_reversed_venue(self):
        import gzip
        root=Path(__file__).resolve().parents[1]
        with gzip.open(root/'docs/evidence/handoff-native-20261115.json.gz','rt') as f:w=json.load(f)
        self.assertEqual(digest(w['payload']),w['sha256'])
        r=next(r for r in w['payload']['receipts'] if 'dates=20261115' in r['source_url'])
        e=next(e for e in r['document']['events'] if e['id']=='401909985')
        comp=e['competitions'][0];teams={t['homeAway']:t['team']['displayName'] for t in comp['competitors']}
        self.assertEqual(teams,{'home':'Philadelphia 76ers','away':'Indiana Pacers'})
        start=datetime.fromisoformat(e['date'].replace('Z','+00:00'))
        self.assertEqual(start.isoformat(),'2026-11-15T18:00:00+00:00')
        self.assertEqual(start.astimezone(__import__('zoneinfo').ZoneInfo('Europe/Istanbul')).hour,21)

    def test_real_new_capture_has_original_clock_proof_and_coherent_periods(self):
        root=Path(__file__).resolve().parents[1]
        w=json.loads(next((root/'docs/prospective/handoff-20261115').glob('nba-*.json')).read_text());p=w['payload']
        self.assertEqual(digest(p),w['sha256']);self.assertEqual(p['prediction']['calibration_status'],'NOT_CALIBRATED')
        self.assertLess(p['prediction_generated_at_utc'],p['fixture_start_utc'])
        self.assertEqual(p['prediction']['metadata']['scenarios'],10000)
        for j,side in enumerate(('home','away')):
            self.assertAlmostEqual(sum(q[j] for q in p['prediction']['quarters']),p['prediction'][side],places=9)
        self.assertTrue(all(pin['ingested_at_utc']<=p['prediction_generated_at_utc'] for pin in p['input_clocks']))
