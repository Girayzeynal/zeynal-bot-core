"""Timing, immutable archive, controlled failure and synthetic-final regressions."""
import asyncio
from copy import deepcopy
from datetime import datetime,timezone
import gzip
import json
from pathlib import Path
import shutil
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase,IsolatedAsyncioTestCase
from unittest.mock import AsyncMock,Mock,patch

import numpy as np

from core.team_identity import digest
from projection_integrity import assert_projection,DISPLAY_TOLERANCES
from telegram_delivery import DeliveryJournal,timeline,render_timeline,reply_analysis,tsi
from hybrid_engine.frozen_archive import FrozenArchive,FrozenHybridService
from hybrid_engine.prospective_results import ProspectiveResults,ResearchReports
from hybrid_engine.source_policy import ControlledTransport

ARCHIVE=Path(__file__).resolve().parents[1]/'docs/prospective/euroleague-20261112'


def projection():
    return dict(home=100.,away=96.,total=196.,margin=4.,home_handicap=-4.,
        quarters=[[25.,24.]]*4,halves=[[50.,48.]]*2)


class ProjectionTests(TestCase):
    def test_both_native_projection_shapes_have_identical_arithmetic(self):
        p=projection();self.assertTrue(assert_projection(p))
        p['quarters']={'home':[25.]*4,'away':[24.]*4};p['halves']={'home':[50.]*2,'away':[48.]*2}
        self.assertTrue(assert_projection(p))

    def test_inconsistent_total_half_quarter_and_handicap_fail(self):
        for key in ('home','away','total','margin','home_handicap'):
            p=projection();p[key]+=.1
            with self.assertRaisesRegex(ValueError,'ARITHMETIC'):assert_projection(p)
        p=projection();p['halves'][0]=[51,48]
        with self.assertRaises(ValueError):assert_projection(p)

    def test_rounding_bounds_are_explicit_and_not_applied_to_unrounded_predictions(self):
        self.assertEqual(DISPLAY_TOLERANCES['team_from_four_quarters'],.025)
        p=projection();p['total']+=.001
        with self.assertRaises(ValueError):assert_projection(p)

    def test_margin_bias_uses_home_minus_away(self):
        from hybrid_engine.evaluation import summarize
        p=projection();p.update(winner=None)
        row=dict(prediction=p,actual=[96,96],actual_quarters=[[24,24]]*4,seconds=0,markets={})
        self.assertEqual(summarize([row])['margin']['bias'],4)


class TimingTests(TestCase):
    def test_utc_to_tsi_has_no_clock_rewriting(self):
        stamp=int(datetime(2026,11,12,5,7,10,tzinfo=timezone.utc).timestamp())
        self.assertEqual(tsi(stamp),'12.11.2026 08:07:10 TSİ')

    def test_old_prediction_creation_is_not_reported_as_new_generation(self):
        p=dict(created_at_utc=100,league='NBA',fixture_id='x',model_digest='m')
        t=timeline(dict(snapshot=p,new_record=False),SimpleNamespace(),200)
        self.assertIsNone(t['prediction_generated_at_utc']);self.assertEqual(t['snapshot_created_at_utc'],100)
        self.assertEqual(t['response_prepared_at_utc'],200);self.assertIsNone(t['telegram_sent_at_utc'])
        text=render_timeline('Kayıtlı sonuç',t)
        self.assertIn('yeniden üretilmedi',text);self.assertEqual(p['created_at_utc'],100)

    def test_delivery_journal_is_append_only_and_retry_idempotent(self):
        with TemporaryDirectory() as tmp:
            j=DeliveryJournal(Path(tmp)/'delivery.sqlite');j.append('event',dict(a=1));j.append('event',dict(a=2))
            self.assertEqual(j.read(),[dict(a=1)])
            with sqlite3.connect(j.path) as db:
                with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM delivery_events')

    def test_delivery_path_never_uses_production_mount(self):
        with self.assertRaises(ValueError):DeliveryJournal('/data/delivery.sqlite')


class DeliveryTests(IsolatedAsyncioTestCase):
    async def test_real_server_date_and_ack_are_separate_from_original_snapshot(self):
        with TemporaryDirectory() as tmp:
            journal=DeliveryJournal(Path(tmp)/'delivery.sqlite');stamp=datetime.now(timezone.utc)
            update=SimpleNamespace(update_id=1,effective_chat=SimpleNamespace(id=17),
                message=SimpleNamespace(reply_text=AsyncMock(return_value=SimpleNamespace(date=stamp,message_id=9))))
            context=SimpleNamespace(application=SimpleNamespace(bot_data={'delivery_journal':journal}))
            p=dict(created_at_utc=100,league='NBA',fixture_id='x',model_digest='m')
            await reply_analysis(update,context,dict(html='saved',snapshot=p,new_record=False),SimpleNamespace())
            events=journal.read();sent=events[-1]
            self.assertEqual(sent['telegram_sent_at_utc'],int(stamp.timestamp()))
            self.assertIsNone(sent['timeline']['prediction_generated_at_utc'])
            self.assertEqual(sent['timeline']['snapshot_created_at_utc'],100)
            self.assertEqual(p['created_at_utc'],100)

    async def test_timeout_does_not_claim_actual_delivery(self):
        with TemporaryDirectory() as tmp:
            journal=DeliveryJournal(Path(tmp)/'d.sqlite')
            update=SimpleNamespace(update_id=2,effective_chat=SimpleNamespace(id=17),message=SimpleNamespace(reply_text=AsyncMock(side_effect=TimeoutError())))
            ctx=SimpleNamespace(application=SimpleNamespace(bot_data={'delivery_journal':journal}))
            with self.assertRaises(TimeoutError):await reply_analysis(update,ctx,dict(html='x'),SimpleNamespace())
            self.assertEqual(journal.read()[-1]['status'],'NOT_CONFIRMED');self.assertIsNone(journal.read()[-1]['telegram_sent_at_utc'])


class FrozenTests(TestCase):
    @classmethod
    def setUpClass(cls):cls.archive=FrozenArchive(ARCHIVE)

    def test_all_twenty_pre_tipoff_outputs_and_inputs_validate(self):
        self.assertEqual(len(self.archive.records),5)
        self.assertEqual(sum(len(r['models']) for r in self.archive.records.values()),20)

    def test_frozen_bayes_replay_does_not_fit_or_change_bytes(self):
        r=next(iter(self.archive.records.values()));before={f:f.read_bytes() for f in ARCHIVE.iterdir()}
        with patch('hybrid_engine.models.HierarchicalStrength.fit',side_effect=AssertionError('No online fit')):
            actual=self.archive.replay(r)
        self.assertAlmostEqual(actual.scores[0],r['models']['BAYES_QMC']['prediction']['home'])
        self.assertTrue(all(p.read_bytes()==b for p,b in before.items()))

    def test_tampered_record_is_not_accepted_after_local_rehash(self):
        with TemporaryDirectory() as tmp:
            dest=Path(tmp)/'archive';shutil.copytree(ARCHIVE,dest)
            p=next(f for f in dest.glob('*.json') if 'payload' in json.loads(f.read_text()))
            d=json.loads(p.read_text());d['payload']['created_at_utc']+=1;p.chmod(0o644);p.write_text(json.dumps(d))
            with self.assertRaises(ValueError):FrozenArchive(dest)

    def test_actual_five_game_capture_has_no_invented_bookmaker_lines(self):
        for r in self.archive.records.values():
            self.assertEqual(r['verified_bookmaker_lines'],[]);self.assertIsNone(r['market_line_probabilities'])
            self.assertLess(r['created_at_utc'],r['fixture']['start_ts_utc'])


class SourcePolicyTests(TestCase):
    def test_server_outage_has_bounded_backoff_without_hammering_source(self):
        source=Mock(return_value=dict(status='SOURCE_HTTP_ERROR',http_status=503));service=ControlledTransport(source)
        with patch('time.time',return_value=100):self.assertEqual(service('TEST','https://test.invalid')['status'],'SOURCE_HTTP_ERROR')
        with patch('time.time',return_value=101):self.assertEqual(service('TEST','https://test.invalid')['status'],'SOURCE_COOLDOWN')
        self.assertEqual(source.call_count,1)

    def receipt(self):
        d={'native':'synthetic'}
        return dict(provider='TEST',source_url='https://test.invalid',status='DOCUMENT_RECEIVED',http_status=200,
            document=d,document_sha256=digest(d),observed_at_utc=100,ingested_at_utc=100)

    def test_fresh_cache_fallback_preserves_original_clock_and_rate_limit_cooldown(self):
        calls=[]
        def primary(*a):
            calls.append(a);return self.receipt() if len(calls)==1 else dict(status='SOURCE_RATE_LIMITED',http_status=429,retry_after_seconds=10)
        service=ControlledTransport(primary,max_age=240)
        with patch('time.time',return_value=100):service('TEST','https://test.invalid')
        with patch('time.time',return_value=101):r=service('TEST','https://test.invalid')
        with patch('time.time',return_value=102):q=service('TEST','https://test.invalid')
        self.assertEqual(len(calls),2);self.assertEqual(r['observed_at_utc'],100);self.assertEqual(q['observed_at_utc'],100)

    def test_stale_cache_and_invalid_source_hash_fail_closed(self):
        r=self.receipt();service=ControlledTransport(lambda *a:r,max_age=10)
        with patch('time.time',return_value=200):self.assertNotEqual(service('TEST','https://test.invalid')['status'],'DOCUMENT_RECEIVED')
        r['document_sha256']='bad'
        with patch('time.time',return_value=100):self.assertNotEqual(service('TEST','https://test.invalid')['status'],'DOCUMENT_RECEIVED')


class ResultTests(TestCase):
    @classmethod
    def setUpClass(cls):cls.archive=FrozenArchive(ARCHIVE)

    def synthetic_final(self):
        receipt=json.loads(gzip.decompress(next(ARCHIVE.glob('official-*.gz')).read_bytes()))
        receipt=deepcopy(receipt);ids={p['fixture']['provider_fixture_id'] for p in self.archive.records.values()}
        stamp=max(p['fixture']['start_ts_utc'] for p in self.archive.records.values())+4*3600
        for g in receipt['document']['data']:
            if g['identifier'] not in ids:continue
            g['played']=True
            for side,points in [('local',25),('road',24)]:
                g[side]['score']=4*points;g[side]['partials']={**{'partials'+str(i):points for i in range(1,5)},'extraPeriods':{}}
        receipt['document_sha256']=digest(receipt['document']);receipt['observed_at_utc']=stamp;receipt['ingested_at_utc']=stamp
        return receipt,stamp

    def test_pending_official_games_do_not_generate_final_scores(self):
        r=json.loads(gzip.decompress(next(ARCHIVE.glob('official-*.gz')).read_bytes()))
        with TemporaryDirectory() as tmp:
            results=ProspectiveResults(self.archive,tmp);out=results.ingest(r)
            self.assertEqual(out['inserted'],[]);self.assertEqual(results.comparison()['settled_games'],0)

    def test_synthetic_finals_append_separately_and_duplicate_ingestion_is_idempotent(self):
        r,now=self.synthetic_final()
        with TemporaryDirectory() as tmp,patch('time.time',return_value=now):
            service=ProspectiveResults(self.archive,tmp)
            self.assertEqual(len(service.ingest(r)['inserted']),5);self.assertEqual(service.ingest(r)['inserted'],[])
            c=service.comparison();self.assertEqual(c['settled_games'],5);self.assertEqual(len(c['models']),4)
            self.assertTrue(all(m['n']==5 for m in c['models'].values()));self.assertFalse(c['calibration_fit_performed'])
            self.assertIn('periods',c['models']['BAYES_QMC']);self.assertIn('winner',c['models']['BAYES_QMC'])

    def test_wrong_provider_or_future_final_observation_is_rejected(self):
        r,now=self.synthetic_final()
        with TemporaryDirectory() as tmp,patch('time.time',return_value=now-1):
            with self.assertRaises(ValueError):ProspectiveResults(self.archive,tmp).ingest(r)

    def test_research_reports_are_explicitly_separate_from_live_performance(self):
        with TemporaryDirectory() as tmp:
            service=ResearchReports(ProspectiveResults(self.archive,tmp));r=service.read('EUROLEAGUE','E2026_103')
            self.assertEqual(len(r['rows']),4);self.assertIn('Araştırma',service.render_compare(r))
            self.assertEqual(service.read('NBA')['comparison']['models'],{})
