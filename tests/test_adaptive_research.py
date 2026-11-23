"""Synthetic native data, real fits/samplers; not provider or Telegram E2E proof."""
import asyncio
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest import TestCase,IsolatedAsyncioTestCase
from unittest.mock import patch,Mock

import numpy as np

from core.team_identity import digest
from hybrid_engine import adaptive_models
from hybrid_engine.adaptive_data import FeatureStore,native_catalog
from hybrid_engine.adaptive_research import AdaptiveResearch,POLICY,read_wrapper
from hybrid_engine.adaptive_worker import AdaptiveWorker
from hybrid_engine.boxes import checked_stats,publish_json,url_for
from hybrid_engine.data import metadata,Abstain
from hybrid_engine.intervals import prediction_intervals
from tests.test_hybrid_models import synthetic_cohort
from tests.test_hybrid_foundation import box_fixture
from tests.test_europe_integration import Source
from hybrid_engine.europe_models import prepare as prepare_europe,season_url
from hybrid_engine.europe_prematch import AutomaticEuropeanService
from tests.test_season_archive_audit import NOW


def cohort(n=80,league='NBA'):
    rows=synthetic_cohort(n)
    for versions in rows:
        r=versions[0];r['league']=league
        r['home_team_id']='1' if r['home_team_id']=='A' else '2'
        r['away_team_id']='1' if r['away_team_id']=='A' else '2'
        r['provider']='ESPN';r['provider_fixture_ids']=[str(401000000+int(r['fixture_id']))]
        for j,s in enumerate(('home','away')):r['periods'][s][-1]+=r['final_scores'][j]-sum(r['periods'][s])
        b=r['box'];b.update({k:r[k] for k in ('league','season','fixture_id','fixture_start_utc','home_team_id','away_team_id')})
        for s in ('home','away'):b['teams'][s]=checked_stats(b['teams'][s])
        b['source']['document_sha256']='b'*64
    return rows


class AdaptiveModelTests(TestCase):
    def setUp(self):
        self.rows=cohort();self.now=self.rows[60][0]['fixture_start_utc']-1800
        timer=patch('time.time',return_value=self.now);timer.start();self.addCleanup(timer.stop)
        self.target=metadata(self.rows[70][0]);self.artifact=adaptive_models.prepare(self.rows,cutoff_utc=self.now)

    def test_future_target_and_later_games_do_not_train_or_change_fit(self):
        changed=deepcopy(self.rows)
        for v in changed[60:]:v[0]['periods']['home']=[99]*4
        b=adaptive_models.prepare(changed,cutoff_utc=self.now)
        self.assertEqual(b,self.artifact)
        self.assertNotIn(self.target['fixture_id'],b['payload']['training_ids'])

    def test_three_real_components_same_box_cohort_and_10000_coherent_paths(self):
        f,blocked,cut=adaptive_models.predict(self.artifact,self.target,cutoff_utc=self.now)
        self.assertFalse(blocked)
        self.assertEqual(set(f),{'UPDATED_TEAM','TEAM_ON_BOX_COHORT','EFFICIENCY_FIXED_PACE','PACE_EFFICIENCY'})
        self.assertEqual(self.artifact['payload']['box_training_ids'],self.artifact['payload']['box_team']['training_ids'])
        for item in f.values():
            self.assertEqual(item.samples.shape,(10000,4,2));self.assertEqual(prediction_intervals(item)['scenarios'],10000)
            self.assertAlmostEqual(sum(item.probabilities()),1)
            self.assertAlmostEqual(item.quarter_means.sum(),sum(item.scores))
        self.assertTrue(f['PACE_EFFICIENCY'].metadata['same_efficiency_rates_across_pace_ablation'])
        self.assertFalse(f['PACE_EFFICIENCY'].metadata['measured_pbp'])
        self.assertFalse(f['PACE_EFFICIENCY'].metadata['parameter_uncertainty_integrated'])

    def test_recent_pace_changes_the_full_match_mean_not_only_period_allocation(self):
        changed=deepcopy(self.rows)
        for versions in changed[48:60]:
            for s in ('home','away'):
                b=versions[0]['box']['teams'][s];b['fga2']+=12;b.update(checked_stats(b))
        a=adaptive_models.prepare(changed,cutoff_utc=self.now)
        out,_,_=adaptive_models.predict(a,self.target,cutoff_utc=self.now)
        self.assertGreater(out['PACE_EFFICIENCY'].metadata['pace_mean'],out['EFFICIENCY_FIXED_PACE'].metadata['pace_mean'])
        self.assertGreater(out['PACE_EFFICIENCY'].scores.sum(),out['EFFICIENCY_FIXED_PACE'].scores.sum())

    def test_missing_boxes_abstains_instead_of_renaming_score_averages_as_pace(self):
        for v in self.rows:v[0].pop('box',None)
        with self.assertRaisesRegex(Abstain,'THIRTY_NATIVE_BOX'):adaptive_models.prepare(self.rows,cutoff_utc=self.now)

    def test_source_box_arithmetic_conflict_is_rejected(self):
        self.rows[0][0]['box']['teams']['home']['possessions_estimate']=999
        with self.assertRaisesRegex(ValueError,'BOX_ARITHMETIC'):adaptive_models.prepare(self.rows,cutoff_utc=self.now)

    def test_future_box_clock_does_not_enter_artifact(self):
        self.rows[0][0]['box']['source']['ingested_at_utc']=self.now+1
        a=adaptive_models.prepare(self.rows,cutoff_utc=self.now)
        self.assertNotIn('0',a['payload']['box_training_ids'])
        self.assertNotIn('box',a['payload']['training_rows'][0])

    def test_wrong_season_target_and_changed_artifact_are_refused(self):
        for kind in ('season','pin','training'):
            a=deepcopy(self.artifact);t=deepcopy(self.target)
            if kind=='season':t['season']='FOREIGN'
            elif kind=='training':t['fixture_id']=a['payload']['training_ids'][0]
            else:a['payload']['fixed_pace_mean']+=1
            with self.subTest(kind=kind),self.assertRaises(ValueError):adaptive_models.predict(a,t,cutoff_utc=self.now)

    def test_european_models_remain_in_their_own_40_minute_cohorts(self):
        for league in ('EuroLeague','EuroCup'):
            rows=cohort(80,league);a=adaptive_models.prepare(rows,cutoff_utc=self.now)
            out,_,_=adaptive_models.predict(a,metadata(rows[70][0]),cutoff_utc=self.now)
            self.assertEqual(a['payload']['league'],league)
            self.assertEqual(out['PACE_EFFICIENCY'].samples.shape,(10000,4,2))


class AdaptiveProtocolTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.rows=cohort();self.now=self.rows[60][0]['fixture_start_utc']-1800
        timer=patch('time.time',side_effect=lambda:self.now);timer.start();self.addCleanup(timer.stop)
        self.research=AdaptiveResearch(self.root/'adaptive-v2');self.plan=self.research.plan(create=True)
        self.target=metadata(self.rows[70][0]);self.pin='a'*64
        self.artifact,_=self.research.fit(self.rows,'NBA','SYNTHETIC')
        self.verify=Mock(side_effect=lambda t:dict(ingested_at_utc=self.now,observed_at_utc=self.now))

    def capture(self):return self.research.capture(self.target,self.pin,self.artifact,self.verify)

    def test_separate_plan_does_not_rewrite_existing_protocol_or_original(self):
        from hybrid_engine.challenger_forward import register,load_plan
        prior=self.root/'challenger-research/protocol';old,_=register(prior);f=next(prior.glob('plan-*.json'));before=f.read_bytes()
        p,new=self.capture();self.assertTrue(new)
        self.assertEqual(f.read_bytes(),before);self.assertEqual(load_plan(prior),old);self.assertFalse(p['original_ledger_changed'])
        self.assertEqual(self.plan,self.research.plan(create=True))

    def test_fixed_six_hour_fit_is_replayed_then_updated_in_a_new_slot(self):
        before={p.name:p.read_bytes() for p in self.research.models.glob('*.json')}
        changed=deepcopy(self.rows);changed[0][0]['periods']['home']=[30]*4
        with patch('hybrid_engine.adaptive_models.prepare',side_effect=AssertionError('NO INTRASLOT REFIT')):
            replay,new=self.research.fit(changed,'NBA','SYNTHETIC')
        self.assertFalse(new);self.assertEqual(replay,self.artifact)
        self.now+=21600
        later,new=self.research.fit(self.rows,'NBA','SYNTHETIC');self.assertTrue(new)
        self.assertNotEqual(later['sha256'],self.artifact['sha256'])
        for name,body in before.items():self.assertEqual((self.research.models/name).read_bytes(),body)

    def test_capture_never_fits_and_uses_post_inference_fixture_check(self):
        with patch('hybrid_engine.models.HierarchicalStrength.fit',side_effect=AssertionError('NO REQUEST FIT')):
            p,new=self.capture()
        self.assertTrue(new);self.verify.assert_called_once_with(self.target)
        self.assertEqual(p['components']['PLAYER_BAYES']['status'],'ABSTAIN')
        self.assertEqual(p['primary_comparison']['available_box_corpus_ids'],self.artifact['payload']['box_training_ids'])

    def test_new_available_games_change_scheduled_team_coefficients_without_replacing_old_fit(self):
        original=deepcopy(self.artifact);self.now+=3*86400
        newer,new=self.research.fit(self.rows,'NBA','SYNTHETIC');self.assertTrue(new)
        self.assertGreater(len(newer['payload']['training_ids']),len(original['payload']['training_ids']))
        self.assertFalse(np.allclose(newer['payload']['team']['coefficients'],original['payload']['team']['coefficients']))
        self.assertEqual(self.artifact,original)

    def test_repeated_capture_does_not_regenerate_or_refresh_timestamps(self):
        p,_=self.capture();before={f.name:f.read_bytes() for f in self.research.registry.root.iterdir() if f.is_file()}
        self.now+=30
        with patch('hybrid_engine.adaptive_models.predict',side_effect=AssertionError('NO REGENERATION')):q,new=self.capture()
        self.assertFalse(new);self.assertEqual(q,p)
        self.assertEqual(before,{f.name:f.read_bytes() for f in self.research.registry.root.iterdir() if f.is_file()})

    def test_started_and_final_5_minute_admissions_cannot_be_backfilled(self):
        self.now=self.target['fixture_start_utc']-300
        with self.assertRaisesRegex(Abstain,'LATE_ADMISSION'):self.capture()
        self.assertEqual(self.research.registry.records(),[])

    def test_crossing_cutoff_in_native_recheck_cannot_publish(self):
        def late(t):self.now=t['fixture_start_utc']-299;return dict(ingested_at_utc=self.now)
        with self.assertRaises(ValueError):self.research.capture(self.target,self.pin,self.artifact,late)
        self.assertEqual(self.research.registry.records(),[])

    def test_plan_tampering_is_not_silently_reset(self):
        path=next(self.research.root.glob('plan-*.json'));w=read_wrapper(path);w['payload']['policy']['minimum_future_games']=1
        w['sha256']=digest(w['payload']);path.write_text(json.dumps(w))
        with self.assertRaisesRegex(ValueError,'PLAN_CHANGED'):self.research.plan(create=True)
        self.assertEqual(len(list(self.research.root.glob('plan-*.json'))),1)

    def test_native_later_labels_are_paired_and_pending_not_called_success(self):
        p,_=self.capture();r=self.research.performance([]);self.assertEqual(r['pending_admissions'],1)
        self.now=self.target['fixture_start_utc']+7200
        label=dict(league='NBA',season='SYNTHETIC',fixture_id=self.target['fixture_id'],snapshot_sha256=self.pin,
            fixture_start_utc=self.target['fixture_start_utc'],label_available_utc=self.now,actual=[108,102],
            actual_periods=dict(home=[27]*4,away=[25,26,25,26]))
        r=self.research.performance([label]);g=r['groups'][0]
        self.assertEqual(g['matched'],1);self.assertEqual(g['day_clusters'],1);self.assertEqual(g['primary_coverage'],1)
        self.assertEqual(g['gate'],'NOT_PROVEN');self.assertFalse(r['automatic_promotion'])
        self.assertEqual(g['ablations']['EFFICIENCY_FIXED_PACE__PACE_EFFICIENCY']['n'],1)

    def test_failed_admission_remains_in_coverage_denominator(self):
        self.research.admit(self.target,self.pin)
        self.now=self.target['fixture_start_utc']+7200
        label=dict(league='NBA',fixture_id=self.target['fixture_id'],snapshot_sha256=self.pin,actual=[1,2],label_available_utc=self.now)
        r=self.research.performance([label]);self.assertEqual(r['settled_admissions'],1)
        self.assertEqual(r['groups'][0]['primary_coverage'],0)
        self.assertEqual(self.research.registry.records(),[])


class AdaptiveNativeDataTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.source=self.root/'original';self.source.mkdir();self.now=NOW
        timer=patch('time.time',side_effect=lambda:self.now);timer.start();self.addCleanup(timer.stop)
        self.row,self.receipt=box_fixture()
        self.receipt['document']['header']['competitions'][0]['status']['type']['name']='STATUS_FINAL'
        self.receipt['document_sha256']=digest(self.receipt['document']);self.fetch=Mock(return_value=self.receipt)
        self.store=FeatureStore(self.root/'new-data',[self.source],self.fetch)

    def ingest(self):
        f=self.source/'source-original.json';f.write_text(json.dumps(self.receipt));before=f.read_bytes()
        self.store.ingest(f,digest(self.receipt),'NBA',2026);self.assertEqual(before,f.read_bytes())
        return f

    def test_native_summary_and_box_replay_preserve_real_availability(self):
        self.ingest();c=self.store.cohort('NBA',2026,self.now)
        self.assertEqual(len(c),1);self.assertNotIn('box',c[0][0])
        r=self.store.acquire_boxes(c);self.assertEqual(r['verified'],1)
        c=self.store.cohort('NBA',2026,self.now);self.assertTrue(c[0][0]['box']['regulation_eligible'])
        self.assertEqual(c[0][0]['box']['source']['ingested_at_utc'],self.receipt['ingested_at_utc'])

    def test_untrusted_path_changed_source_and_future_receipt_are_refused(self):
        f=self.ingest();r=json.loads(f.read_text());r['document']['header']['id']='wrong';f.write_text(json.dumps(r))
        with self.assertRaisesRegex(ValueError,'REFERENCE_PIN'):self.store.cohort('NBA',2026,self.now)
        outside=self.root/'not-an-allowed-source.json';outside.write_text(json.dumps(self.receipt))
        with self.assertRaisesRegex(ValueError,'PATH_OR_BUDGET'):self.store.ingest(outside,digest(self.receipt),'NBA',2026)
        r=deepcopy(self.receipt);r['ingested_at_utc']=self.now+1
        with self.assertRaises(ValueError):native_catalog(r,'NBA',2026)

    def test_european_competition_is_not_inferred_from_a_similar_name(self):
        source=Source('EUROCUP');receipt=source('EUROLEAGUE_LIVE','https://api-live.euroleague.net/v2/competitions/U/seasons/U2026/games')
        c=native_catalog(receipt,'EUROCUP',2026);self.assertEqual(c['payload']['league'],'EuroCup')
        with self.assertRaises(ValueError):native_catalog(receipt,'EUROLEAGUE',2026)

    def test_source_failure_is_visible_and_native_rows_are_not_invented(self):
        self.ingest();self.fetch.return_value=dict(status='SOURCE_RATE_LIMITED',http_status=429,retry_after_seconds=300,provider='ESPN')
        c=self.store.cohort('NBA',2026,self.now);r=self.store.acquire_boxes(c)
        self.assertEqual(r['blocked'],1);self.assertEqual(r['verified'],0)
        self.assertEqual(r['failure_classes'],{'SOURCE_RATE_LIMITED':1})
        calls=self.fetch.call_count;self.store.acquire_boxes(c);self.assertEqual(calls,self.fetch.call_count)
        self.assertNotIn('box',self.store.cohort('NBA',2026,self.now)[0][0])

    def test_same_final_content_from_later_retrieval_does_not_duplicate_or_retime_feed(self):
        self.ingest();before={p.name:p.read_bytes() for p in self.store.root.glob('feed-*.json')}
        later=deepcopy(self.receipt);later['observed_at_utc']+=60;later['ingested_at_utc']+=60
        path=self.source/'source-later.json';path.write_text(json.dumps(later))
        self.store.ingest(path,digest(later),'NBA',2026)
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.store.root.glob('feed-*.json')})
        self.assertEqual(self.store.cohort('NBA',2026,self.now)[0][0]['ingested_at_utc'],self.receipt['ingested_at_utc'])


class AdaptivePlayerPairTests(TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.test_player_shadow import case_for
        from tests.test_player_minutes import archive_inputs
        cls.tmp=TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup);cls.root=Path(cls.tmp.name)
        cls.rows=cohort(135);cls.players=cls.root/'player-shadow';cls.players.mkdir()
        for i,versions in enumerate(cls.rows[:100]):
            r=versions[0];data=case_for(r)
            # Native-shaped past minutes vary while still reconciling to 240.
            for b in data['boxes']:
                shift=i%3
                b['players'][0]['minutes_display']=str(30+shift)
                b['players'][1]['minutes_display']=str(30-shift)
            with patch('time.time',return_value=r['fixture_start_utc']-1800):archive_inputs(cls.players,data)
        cls.now=cls.rows[120][0]['fixture_start_utc']-1800
        with patch('time.time',return_value=cls.now):
            cls.research=AdaptiveResearch(cls.root/'adaptive-v2',player_directory=cls.players)
            cls.research.plan(create=True);cls.artifact,_=cls.research.fit(cls.rows,'NBA','SYNTHETIC')
            cls.publication=archive_inputs(cls.players,case_for(cls.rows[120][0]))

    def setUp(self):
        timer=patch('time.time',return_value=self.now);timer.start();self.addCleanup(timer.stop)

    def test_hundred_prospective_inputs_fit_joint_player_and_identical_team_control(self):
        p=self.artifact['payload'];pair=p['player_pair']
        self.assertIsNotNone(pair,p['player_readiness'])
        self.assertEqual(len(pair['payload']['candidate']['training_ids']),100)
        self.assertEqual(pair['payload']['candidate']['training_ids'],pair['payload']['baseline']['training_ids'])
        self.assertTrue(pair['payload']['candidate']['players'])
        self.assertFalse(pair['payload']['individual_defense_fitted'])

    def test_player_components_capture_only_from_fresh_verified_prospective_minutes(self):
        target=metadata(self.rows[120][0])
        with patch('hybrid_engine.models.HierarchicalStrength.fit',side_effect=AssertionError('NO FIT DURING CAPTURE')):
            p,new=self.research.capture_player(target,'a'*64,self.artifact,lambda t:dict(ingested_at_utc=self.now))
        self.assertTrue(new);self.assertEqual(p['components']['PLAYER_BAYES']['status'],'FORECAST_CREATED')
        self.assertEqual(p['components']['PLAYER_TEAM_CONTROL']['status'],'FORECAST_CREATED')
        self.assertEqual(p['components']['PLAYER_BAYES']['intervals']['scenarios'],10000)
        self.assertIsNone(p['confidence_index']);self.assertFalse(p['production_enabled'])

    def test_constant_minutes_do_not_claim_identifiable_player_effects(self):
        from tests.test_player_shadow import case_for
        from tests.test_player_minutes import archive_inputs
        with TemporaryDirectory() as tmp:
            path=Path(tmp);players=path/'player-shadow';players.mkdir()
            for versions in self.rows[:100]:
                r=versions[0]
                with patch('time.time',return_value=r['fixture_start_utc']-1800):archive_inputs(players,case_for(r))
            study=AdaptiveResearch(path/'adaptive-v2',player_directory=players);study.plan(create=True)
            a,_=study.fit(self.rows,'NBA','SYNTHETIC')
            self.assertIsNone(a['payload']['player_pair'])
            self.assertEqual(a['payload']['player_readiness']['eligible_games'],100)

    def test_minutes_from_a_different_original_snapshot_cannot_be_relinked(self):
        study=AdaptiveResearch(self.root/'wrong-original-link',player_directory=self.players);study.plan(create=True)
        with self.assertRaisesRegex(Abstain,'VERIFIED_PLAYER_MODEL_OR_FRESH'):
            study.capture_player(metadata(self.rows[120][0]),'b'*64,self.artifact,lambda t:dict(ingested_at_utc=self.now))
        self.assertEqual(study.player_registry.records(),[])

    def test_model_bundle_ready_time_follows_the_optional_player_fit(self):
        from hybrid_engine.adaptive_research import fit_pair
        clock=[self.now]
        def delayed(*args,**kwargs):
            clock[0]+=3
            return fit_pair(*args,**kwargs)
        with patch('time.time',side_effect=lambda:clock[0]),patch('hybrid_engine.adaptive_research.fit_pair',side_effect=delayed):
            study=AdaptiveResearch(self.root/'bundle-clock',player_directory=self.players);study.plan(create=True)
            a,_=study.fit(self.rows,'NBA','SYNTHETIC')
        self.assertIsNotNone(a['payload']['player_pair'])
        self.assertEqual(a['payload']['prepared_at_utc'],clock[0])
        self.assertLessEqual(a['payload']['player_pair']['payload']['prepared_at_utc'],a['payload']['prepared_at_utc'])



class AdaptiveWorkerTests(IsolatedAsyncioTestCase):
    async def test_native_eurocup_worker_collects_refits_captures_and_pairs_later_finals(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);now=[NOW];source=Source('EUROCUP',lambda:now[0])
            def fetch(provider,url):
                if url.endswith('/stats'):
                    game=next(g for g in source.raw['data'] if g['gameCode']==int(url.split('/')[-2]))
                    doc={}
                    for side in ('local','road'):
                        score=game[side]['score'];ft=10+score%2;made=(score-30-ft)//2
                        doc[side]=dict(total=dict(fieldGoalsMade2=made,fieldGoalsAttempted2=made+20,
                            fieldGoalsMade3=10,fieldGoalsAttempted3=25,freeThrowsMade=ft,freeThrowsAttempted=ft+4,
                            offensiveRebounds=10,defensiveRebounds=30,turnovers=12,foulsCommited=18,points=score),players=[])
                    return source.receipt(url,doc)
                return source(provider,url)
            with patch('time.time',side_effect=lambda:now[0]):
                prepare_europe(root/'models','EUROCUP',2026,fetch('EUROLEAGUE_LIVE',season_url('EUROCUP',2026)))
                service=AutomaticEuropeanService('EUROCUP',root/'original',root/'models',fetch)
                from hybrid_engine.live_euroleague import names
                pairs=names(source.raw)
                for g in source.raw['data']:
                    if not g['played']:
                        h,a=pairs[g['identifier']]
                        r=await service.analyze('EUROCUP','2026-11-11',h,a);self.assertEqual(r['status'],'EUROPE_HYBRID_OK',r)
                original={p.name:p.read_bytes() for p in service.registry.root.glob('*.json')}
                worker=AdaptiveWorker(root/'adaptive-v2',europe={'EUROCUP':service},fetcher=fetch)
                for _ in range(9):report=await worker.tick()
                self.assertEqual(report['groups']['EUROCUP']['status'],'SCHEDULED_MODEL_AVAILABLE',report)
                records=worker.research.registry.records();self.assertEqual(len(records),2)
                self.assertTrue(all(r['payload']['components']['PACE_EFFICIENCY']['status']=='FORECAST_CREATED' for r in records))
                self.assertIn('Box-score',worker.render('EUROCUP'))
                self.assertIn('PACE_EFFICIENCY:',worker.render('EUROCUP','U2026_1'))
                for name,raw in original.items():self.assertEqual((service.registry.root/name).read_bytes(),raw)
                before={p.name:p.read_bytes() for p in worker.research.registry.root.glob('*.json')}
                with patch('hybrid_engine.adaptive_models.predict',side_effect=AssertionError('NO RECALCULATION')):
                    await worker.tick()
                self.assertEqual(before,{p.name:p.read_bytes() for p in worker.research.registry.root.glob('*.json')})
                now[0]+=6*3600
                for g in source.raw['data']:
                    if not g['played']:
                        g['played']=True
                        for side in ('local','road'):
                            parts=[20,21,22,23] if side=='local' else [19,20,21,22]
                            g[side].update(score=sum(parts),partials={**{f'partials{i+1}':v for i,v in enumerate(parts)},'extraPeriods':{}})
                service.collect_results();result=worker.research.performance(worker.labels())
                self.assertEqual(result['settled_admissions'],2)
                self.assertEqual(result['groups'][0]['matched'],2)
                self.assertEqual(result['groups'][0]['gate'],'NOT_PROVEN')

    async def test_background_failure_is_safe_and_loop_cancels(self):
        with TemporaryDirectory() as tmp:
            worker=AdaptiveWorker(Path(tmp)/'adaptive-v2')
            with patch.object(worker,'cases',side_effect=ValueError('SYNTHETIC_PRIVATE_ERROR')):
                r=await worker.tick()
            self.assertEqual(r['status'],'ABSTAIN');self.assertNotIn('SYNTHETIC_PRIVATE_ERROR',json.dumps(r))
            app=type('App',(),{'bot_data':{}})();task=asyncio.create_task(worker.run(app))
            for _ in range(100):
                if 'last_adaptive_v2_poll' in app.bot_data:break
                await asyncio.sleep(.01)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task

    async def test_overlapping_ticks_cannot_collect_or_fit_twice(self):
        with TemporaryDirectory() as tmp:
            w=AdaptiveWorker(Path(tmp)/'adaptive-v2');w.running=True
            with patch.object(w.research,'fit',side_effect=AssertionError('NO FIT')):r=await w.tick()
            self.assertEqual(r['status'],'ABSTAIN');self.assertEqual(r['reason'],'ADAPTIVE_ALREADY_RUNNING')
