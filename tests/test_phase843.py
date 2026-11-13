"""Native fixture regression receipts and synthetic live inference mechanics."""
import asyncio
from copy import deepcopy
from datetime import datetime,timezone
import gzip
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import time
from unittest import TestCase,IsolatedAsyncioTestCase
from unittest.mock import AsyncMock,Mock,patch

import numpy as np

from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import STRICT
from hybrid_engine.live_nba import prepare_rows,PreparedBayes,LiveNBAHybridService
from projection_integrity import assert_projection
from telegram_delivery import timeline
from universal_analysis import UniversalAnalyzeService,render_preflight
from tests.test_hybrid_models import synthetic_cohort
from tests.test_release_integration import nba_fetcher
from tests.test_season_archive_audit import NOW

ROOT=Path(__file__).resolve().parents[1]
RECEIPTS=ROOT/'docs/evidence/nba-phase843-date-fixtures-20261113.json.gz'


def synthetic_prepared(path,cutoff=NOW-5):
    rows=[]
    for i,versions in enumerate(synthetic_cohort(30)):
        r=deepcopy(versions[0]);r['season']='2026/2027';r['fixture_id']='training-'+str(i)
        r['home_team_id']='1' if i%2 else '2';r['away_team_id']='2' if i%2 else '1'
        r['fixture_start_utc']=cutoff-(40-i)*86400
        r['observed_at_utc']=r['fixture_start_utc']+12000;r['ingested_at_utc']=r['observed_at_utc']+1
        rows.append(r)
    a=prepare_rows(rows,cutoff=cutoff,provenance={'fixture_kind':'SYNTHETIC_NOT_ACCURACY_EVIDENCE'})
    publish_json(path,a)
    return PreparedBayes(path,trusted_sha256=a['sha256'])


class NativeDateTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.sources=json.loads(gzip.decompress(RECEIPTS.read_bytes()))
        self.at=max(r['ingested_at_utc'] for r in self.sources.values())
        timer=patch('time.time',return_value=self.at);timer.start();self.addCleanup(timer.stop)
        self.fetch=Mock(side_effect=lambda provider,url:deepcopy(self.sources[url]))
        self.events=next(r['document']['events'] for u,r in self.sources.items() if 'dates=20261112' in u)

    async def test_all_four_native_espn_us_day_entries_require_tsi_november_13(self):
        expected={'401909976':0,'401909977':0,'401909978':1,'401909979':2}
        for e in self.events:
            c={v['homeAway']:v['team']['displayName'] for v in e['competitions'][0]['competitors']}
            report=await UniversalAnalyzeService(fetcher=self.fetch).preflight('NBA','2026-11-12',c['home'],c['away'])
            with self.subTest(id=e['id']):
                self.assertEqual(report['reason'],'FIXTURE_LOCAL_DATE_MISMATCH');self.assertNotIn('fixture',report)
                d=report['date_diagnostic'];self.assertEqual(d['expected_day'],'2026-11-13')
                self.assertEqual(d['provider_fixture_ids'],[e['id']])
                utc=datetime.fromtimestamp(d['tipoff_utc'],timezone.utc)
                self.assertEqual(utc.hour,expected[e['id']]);self.assertEqual(utc.day,13)
                self.assertIn('/analyze NBA 2026-11-13',d['suggested_command'])
                self.assertIn('ESPN maç kimliği',render_preflight(report));self.assertEqual(report['prospective_records_created'],0)

    async def test_explicit_correct_day_resolves_each_same_id_without_remapping(self):
        for e in self.events:
            c={v['homeAway']:v['team']['displayName'] for v in e['competitions'][0]['competitors']}
            report=await UniversalAnalyzeService(fetcher=self.fetch).preflight('NBA','2026-11-13',c['home'],c['away'])
            self.assertEqual(report['status'],'VERIFIED_NBA_FIXTURE');self.assertEqual(report['fixture']['provider_fixture_ids'],[e['id']])

    async def test_older_historical_request_still_refuses_before_network(self):
        out=await UniversalAnalyzeService(fetcher=self.fetch).preflight('NBA','2026-11-10','Philadelphia 76ers','Toronto Raptors')
        self.assertEqual(out['reason'],'HISTORICAL_PIT_SNAPSHOT_REQUIRED');self.fetch.assert_not_called()

    async def test_wrong_home_away_is_not_guessed(self):
        r=await UniversalAnalyzeService(fetcher=self.fetch).preflight('NBA','2026-11-12','Toronto Raptors','Philadelphia 76ers')
        self.assertEqual(r['reason'],'FIXTURE_NOT_UNIQUELY_VERIFIED');self.assertNotIn('date_diagnostic',r)

    async def test_started_adjacent_fixture_has_no_retry_suggestion(self):
        for source in self.sources.values():
            if '/scoreboard?' not in source['source_url']:continue
            for e in source['document']['events']:
                if e['id']=='401909976':e['competitions'][0]['status']['type']['name']='STATUS_POSTPONED'
            source['document_sha256']=digest(source['document'])
        r=await UniversalAnalyzeService(fetcher=self.fetch).preflight('NBA','2026-11-12','Philadelphia 76ers','Toronto Raptors')
        self.assertEqual(r['reason'],'FIXTURE_LOCAL_DATE_MISMATCH');self.assertIsNone(r['date_diagnostic']['suggested_command'])

    async def test_exact_tipoff_is_never_accepted_with_current_date(self):
        tip=int(datetime(2026,11,13,tzinfo=timezone.utc).timestamp())
        for r in self.sources.values():r.update(observed_at_utc=tip,ingested_at_utc=tip)
        with patch('time.time',return_value=tip):
            r=await UniversalAnalyzeService(fetcher=self.fetch).preflight('NBA','2026-11-13','Philadelphia 76ers','Toronto Raptors')
        self.assertEqual(r['reason'],'FIXTURE_ALREADY_STARTED_OR_COMPLETED')

    async def test_utc_previous_day_and_tsi_midnight_are_distinct_calendar_days(self):
        from nba_command import parse_espn_scoreboard
        # Explicit synthetic boundary case; original native receipt is untouched.
        e=deepcopy(self.events[0]);e['date']='2026-11-12T21:30:00Z'
        e['competitions'][0]['date']=e['date'];document={'events':[e]}
        self.assertEqual(parse_espn_scoreboard(document,'2026-11-12'),[])
        rows=parse_espn_scoreboard(document,'2026-11-13');self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['start'].hour,0);self.assertEqual(rows[0]['start'].minute,30)


class PreparedTests(TestCase):
    def setUp(self):
        p=patch('time.time',return_value=NOW);p.start();self.addCleanup(p.stop)

    def test_hash_and_source_mutation_are_rejected(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'model.json';prepared=synthetic_prepared(path)
            with self.assertRaisesRegex(ValueError,'TRUSTED_PIN'):PreparedBayes(path,trusted_sha256='0'*64)
            w=json.loads(path.read_text());w['payload']['source_code_pins']['live_nba.py']='0'*64
            w['sha256']=digest(w['payload']);path.write_text(json.dumps(w))
            with self.assertRaisesRegex(ValueError,'SOURCE_OR_FORMAT'):PreparedBayes(path,trusted_sha256=w['sha256'])

    def test_no_production_directory_can_be_initialized(self):
        with self.assertRaises(ValueError):LiveNBAHybridService('/data/new',None)

    def test_offline_training_rejects_future_local_availability(self):
        row=synthetic_cohort(1)[0][0];row.update(season='2026/2027',ingested_at_utc=NOW+1)
        with self.assertRaisesRegex(ValueError,'PAST_LABELS'):prepare_rows([row],cutoff=NOW,provenance={})


class ProspectiveArchiveTests(TestCase):
    def test_eight_immutable_variants_are_four_real_pregame_fixtures_not_eight_samples(self):
        root=ROOT/'docs/prospective/nba-20261113'
        index=json.loads((root/'index-b59c2c465800bbddd0a1c133ada2150500ec9b7390ef9bd5a82d012fd0d4255b.json').read_text())
        p=index['payload'];self.assertEqual(digest(p),index['sha256'])
        self.assertEqual(p['snapshots'],8);self.assertEqual(p['unique_fixtures'],4)
        grouped={}
        for entry in p['records']:
            w=json.loads((root/entry['file']).read_text());r=w['payload']
            self.assertEqual(digest(r),entry['sha256']);self.assertEqual(w['sha256'],entry['sha256'])
            self.assertTrue(assert_projection(r['prediction']));self.assertLess(r['created_at_utc'],r['fixture_start_utc'])
            self.assertLessEqual(r['prediction_generated_at_utc'],r['created_at_utc']);self.assertIsNone(r['actual'])
            self.assertEqual(len(r['intervals']['markets']),11)
            grouped.setdefault(r['fixture_id'],[]).append(r['intervals']['sample_sha256'])
        self.assertEqual(len(grouped),4)
        self.assertTrue(all(len(hashes)==2 and hashes[0]==hashes[1] for hashes in grouped.values()))


class LiveNBATests(IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        from hybrid_engine.frozen_archive import FrozenArchive
        cls.frozen_archive=FrozenArchive(ROOT/'docs/prospective/euroleague-20261112')

    async def asyncSetUp(self):
        p=patch('time.time',return_value=NOW);p.start();self.addCleanup(p.stop)
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.prepared=synthetic_prepared(self.root/'model.json');self.fetch=nba_fetcher()
        self.service=LiveNBAHybridService(self.root/'live',self.prepared,fetcher=self.fetch)

    async def analyze(self):return await self.service.analyze('NBA','2026-11-11','Synthetic Hawks','Synthetic Bears')

    async def test_new_current_nba_uses_offline_parameters_and_actual_10000_paths(self):
        with patch('hybrid_engine.models.HierarchicalStrength.fit',side_effect=AssertionError('No online training')):
            r=await self.analyze()
        self.assertEqual(r['status'],'ANALYSIS_OK',r);self.assertTrue(r['new_record'])
        p=r['snapshot'];self.assertEqual(p['intervals']['scenarios'],10000);self.assertEqual(len(p['intervals']['markets']),11)
        self.assertTrue(assert_projection(p['prediction']));self.assertAlmostEqual(sum(p['prediction']['winner']),1)
        self.assertTrue(all(0<=v<=1 for v in p['prediction']['winner']));self.assertIsNone(p['confidence']['value'])
        text='\n'.join(r['html_parts']);self.assertIn('NBA',text);self.assertIn('Ham model olasılığı',text)
        self.assertIn('kalibre edilmedi',text);self.assertNotIn('PREMATCH tahmini değildir',text)
        self.assertIn('Piyasa verisi doğrulanamadı',text)
        self.assertLessEqual(p['parameter_fit_cutoff_utc'],p['prediction_generated_at_utc'])
        self.assertTrue(all(pin['ingested_at_utc']<=p['created_at_utc']<p['fixture_start_utc'] for pin in p['input_clocks']))

    async def test_repeated_and_concurrent_requests_reuse_identical_snapshot(self):
        a,b=await asyncio.gather(self.analyze(),self.analyze())
        self.assertEqual(a['status'],'ANALYSIS_OK',a);self.assertEqual(a['snapshot'],b['snapshot'])
        self.assertTrue(a['new_record']);self.assertFalse(b['new_record'])
        with sqlite3.connect(self.service.ledger.path) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM live_analysis_snapshots').fetchone()[0],1)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    async def test_prediction_archive_tipoff_and_reply_clocks_are_separate(self):
        r=await self.analyze();self.assertEqual(r['status'],'ANALYSIS_OK',r)
        t=timeline(r,self.service,NOW+10)
        self.assertEqual(t['prediction_generated_at_utc'],NOW);self.assertEqual(t['snapshot_created_at_utc'],NOW)
        self.assertEqual(t['archive_published_at_utc'],NOW);self.assertEqual(t['response_prepared_at_utc'],NOW+10)
        self.assertGreater(t['tipoff_utc'],NOW);self.assertIsNone(t['telegram_reply_at_utc'])

    async def test_inference_is_reproducible_and_mc_qmc_samples_are_distinct(self):
        report=await self.service.collector.identity.preflight('NBA','2026-11-11','Synthetic Hawks','Synthetic Bears')
        cut,_,_=await asyncio.to_thread(self.service._inputs,report)
        a,b,mc=self.service._predict(cut);c,d,_=self.service._predict(cut)
        self.assertEqual(b,d);self.assertNotEqual(b['sample_sha256'],mc['mc_bands']['sample_sha256'])
        self.assertEqual(a.summary(),c.summary() | {'metadata':a.summary()['metadata']})

    async def test_fixture_change_during_inference_stops_durable_commit(self):
        original=self.service._predict
        def delayed(cut):
            result=original(cut)
            self.service.collector.identity.preflight=AsyncMock(return_value={'status':'ABSTAIN','reason':'TIPOFF_DURING_PREFLIGHT'})
            return result
        with patch.object(self.service,'_predict',side_effect=delayed):r=await self.analyze()
        self.assertEqual(r['status'],'ABSTAIN');self.assertIn('FIXTURE_CHANGED',r['html'])
        with sqlite3.connect(self.service.ledger.path) as db:self.assertEqual(db.execute('SELECT count(*) FROM live_analysis_snapshots').fetchone()[0],0)

    async def test_history_source_failure_does_not_create_forecast(self):
        original=self.fetch.side_effect
        self.fetch.side_effect=lambda provider,url:dict(status='SOURCE_RATE_LIMITED',http_status=429) if '/schedule?' in url else original(provider,url)
        r=await self.analyze();self.assertEqual(r['status'],'ABSTAIN');self.assertIn('SOURCE_RATE_LIMITED',r['html'])

    async def test_archive_disk_failure_does_not_claim_success(self):
        with patch.object(self.service,'_asset',side_effect=OSError('synthetic disk full')):r=await self.analyze()
        self.assertEqual(r['status'],'ABSTAIN');self.assertNotIn('synthetic disk full',r['html'])

    async def test_offline_target_contamination_is_rejected(self):
        report=await self.service.collector.identity.preflight('NBA','2026-11-11','Synthetic Hawks','Synthetic Bears')
        self.prepared.model.training_ids.append(report['fixture']['canonical_id'])
        r=await self.analyze();self.assertEqual(r['status'],'ABSTAIN');self.assertIn('TARGET_IN_OFFLINE_TRAINING',r['html'])

    async def test_changed_source_asset_cannot_be_silently_replayed(self):
        r=await self.analyze();self.assertEqual(r['status'],'ANALYSIS_OK',r)
        asset=r['snapshot']['input_asset'];path=self.service.assets/asset['file']
        data=json.loads(path.read_text());data['cutoff_utc']+=1;path.write_text(json.dumps(data))
        r=await self.analyze();self.assertEqual(r['status'],'ABSTAIN');self.assertIn('ASSET_PIN_CONFLICT',r['html'])

    async def test_total_request_budget_stops_before_commit(self):
        with patch.object(self.service,'_check_budget',side_effect=ValueError('LIVE_REQUEST_TIME_BUDGET')):r=await self.analyze()
        self.assertEqual(r['status'],'ABSTAIN');self.assertIn('TIME_BUDGET',r['html'])

    async def test_large_document_cache_policy_is_bounded_without_losing_source_receipts(self):
        r=await self.analyze();self.assertEqual(r['status'],'ANALYSIS_OK',r)
        self.assertLessEqual(len(self.service.collector.cache),1)
        self.assertLessEqual(sum(size for value,size in self.service.transport.cache.values()),1024*1024)
        self.assertNotIn('fixture_knowledge',self.prepared.payload['provenance'])
        urls={json.loads((self.service.assets/ref['file']).read_text())['source_url'] for ref in r['snapshot']['source_assets']}
        self.assertTrue(any('/seasons/2027/teams?' in u for u in urls));self.assertTrue(any('/nba/teams?' in u for u in urls))

    async def test_live_routing_preserves_el_frozen_replay_and_nba_reports(self):
        from hybrid_engine.frozen_archive import FrozenArchive
        from hybrid_engine.test_bot import install_isolated_services
        app=SimpleNamespace(bot_data={},add_handler=Mock(),add_error_handler=Mock())
        archive=self.frozen_archive
        install_isolated_services(app,archive,self.root/'test',chat_id=17,transport=self.fetch,nba_service=self.service)
        live=await app.bot_data['verified_analysis_service'].analyze('NBA','2026-11-11','Synthetic Hawks','Synthetic Bears')
        self.assertEqual(live['status'],'ANALYSIS_OK',live)
        reports=app.bot_data['ledger_reports'];r=reports.read('NBA')
        self.assertEqual(r['report']['unique_fixtures'],1);self.assertIn('ÜRETİM DEĞİL',reports.render_accuracy(r))
        self.assertIn('ELITE_HYBRID',reports.render_compare(reports.read('NBA','401000123')))
        self.assertEqual(reports.read('EUROLEAGUE')['report']['comparison']['pending_games'],5)
