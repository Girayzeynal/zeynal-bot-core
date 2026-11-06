"""Synthetic only: no network, real ledger or production timer."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from prediction_inputs import digest
from faz40_research import MODEL
from faz41_adapters import capture
from faz41_evidence import REGISTRY
from faz42_schedule import seal_schedule,validate_schedule,fixture_times
from faz42_snapshot import build_snapshot,validate_snapshot,reconcile
from faz42_test_store import SyntheticSnapshotStore
from tests.test_faz42_history import NOW,history,permitted_registry
from tests.test_faz33 import event
from tests.test_faz32 import summary
from tests.test_euroleague_live import source

URL='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20261106'
START=NOW+3600


def test_model():
    p=dict(schema_version=1,model=MODEL,git_sha='a'*40,commit_utc=NOW-100,materialized_at_utc=NOW-50,
        purpose='SYNTHETIC_TEST',modules_sha256={'synthetic-model.py':'b'*64})
    return dict(payload=p,sha256=digest(p))


class ProspectiveTrackTests(TestCase):
    def setUp(self):
        self.timer=patch('time.time',return_value=NOW);self.clock=self.timer.start();self.addCleanup(self.timer.stop)
        self.registry=permitted_registry();self.pin=digest(self.registry);self.history=history(self.registry)
        self.schedule=self.seal();self.fixture=self.schedule['payload']['fixtures'][0]['fixture'];self.cid=self.fixture['canonical_id']
        self.folder=TemporaryDirectory(prefix='faz42-test-');self.addCleanup(self.folder.cleanup)
        self.store=SyntheticSnapshotStore(self.folder.name)

    def seal(self,raw=None,registry=None,provider='ESPN',league='NBA',url=URL):
        registry=registry or self.registry
        with patch('time.time',return_value=NOW-50):return seal_schedule(raw or {'events':[event(START,'900000099')]},
            provider=provider,league=league,season_end_year=2027,source_url=url,observed_at_utc=NOW-60,
            ingested_at_utc=NOW-55,usage='SYNTHETIC_TEST',registry=registry,registry_pin=digest(registry))

    def shot(self,**updates):
        opts=dict(cutoff_utc=NOW,registry=self.registry,registry_pin=self.pin,minimum_team_games=2);opts.update(updates)
        return build_snapshot(self.history,self.schedule,self.cid,test_model(),**opts)

    def insert(self,s=None,store=None):
        return (store or self.store).insert(s or self.shot(),registry=self.registry,registry_pin=self.pin)

    def final(self,*,overtime=False,changed=False,other_time=False):
        raw=summary(900000099,START+(1 if other_time else 0));raw.pop('boxscore',None)
        if overtime:
            for t in raw['header']['competitions'][0]['competitors']:
                extra=12 if t['homeAway']=='home' else 9
                t['linescores']=[dict(displayValue='25') for _ in range(4)]+[dict(displayValue=str(extra))]
                t['score']=str(100+extra)
        if changed:
            t=raw['header']['competitions'][0]['competitors'][0];t['linescores'][0]['displayValue']=str(int(t['linescores'][0]['displayValue'])+1);t['score']=str(int(t['score'])+1)
        with patch('time.time',return_value=START+10002):return capture(raw,provider='ESPN',league='NBA',season_end_year=2027,
            observed_at_utc=START+10000,ingested_at_utc=START+10001,usage='SYNTHETIC_TEST',registry=self.registry,registry_pin=self.pin)

    def test_snapshot_has_cutoff_model_source_seed_and_consistent_periods(self):
        s=self.shot();p=validate_snapshot(s,registry=self.registry,registry_pin=self.pin,recompute=True)
        self.assertEqual(p['status'],'PREDICTED_EXPERIMENTAL');self.assertEqual(p['scope'],'REGULATION_ONLY')
        self.assertEqual(p['simulation']['simulations'],10000);self.assertIsInstance(p['simulation']['seed'],int)
        self.assertEqual(p['model_manifest']['payload']['git_sha'],'a'*40)
        self.assertEqual(len(p['source_digest']),64);self.assertEqual(p['prospective_records_created'],0)
        q=p['prediction'];self.assertAlmostEqual(q['home']['first_half']+q['home']['second_half'],q['home']['total'])

    def test_schedule_utc_turkey_date_rollover_is_explicit(self):
        f=dict(self.fixture,start_utc=int(datetime(2026,11,6,22,30,tzinfo=timezone.utc).timestamp()))
        t=fixture_times(f);self.assertEqual(t['start_turkey'],'2026-11-07T01:30:00+03:00')

    def test_duplicate_schedule_aliases_count_one_fixture(self):
        a=event(START,'900000099');b=event(START,'900000100')
        s=self.seal({'events':[a,a,b]});self.assertEqual(len(s['payload']['fixtures']),1)
        self.assertEqual(s['payload']['fixtures'][0]['provider_fixture_ids'],['900000099','900000100'])

    def test_schedule_collision_rehashed_identity_and_postponed_are_refused(self):
        a=event(START,'900000099');b=event(START,'900000100');b['competitions'][0]['competitors'][1]['team']['id']='8'
        with self.assertRaisesRegex(ValueError,'SAME_TEAM_START'):self.seal({'events':[a,b]})
        s=deepcopy(self.schedule);s['payload']['fixtures'][0]['fixture']['start_utc']+=1;s['sha256']=digest(s['payload'])
        with self.assertRaisesRegex(ValueError,'CANNOT_REPLAY'):validate_schedule(s,cutoff_utc=NOW,registry=self.registry,registry_pin=self.pin)
        a['status']['type']['name']='STATUS_POSTPONED'
        self.assertEqual(self.seal({'events':[a]})['payload']['fixtures'],[])

    def test_el_ec_discovery_reuses_competition_mapping(self):
        for league,code in [('EUROLEAGUE','E'),('EUROCUP','U')]:
            g=source(league)['game'];g['played']=False;g['utcDate']=datetime.fromtimestamp(START,timezone.utc).isoformat()
            s=self.seal({'data':[g],'total':1},provider='EUROLEAGUE_LIVE',league=league,
                        url=f'https://api-live.euroleague.net/v2/competitions/{code}/seasons/{code}2026/games?limit=1000')
            self.assertEqual(s['payload']['fixtures'][0]['fixture']['league'],league)
        with self.assertRaisesRegex(ValueError,'INCOMPLETE'):self.seal({'data':[],'total':1},provider='EUROLEAGUE_LIVE',league='EUROCUP',url='https://api-live.euroleague.net/v2/competitions/U/seasons/U2026/games')

    def test_unknown_permission_abstains_without_invented_prediction(self):
        registry=deepcopy(REGISTRY);s=self.seal(registry=registry)
        out=build_snapshot([],s,s['payload']['fixtures'][0]['fixture']['canonical_id'],test_model(),cutoff_utc=NOW,registry=registry,registry_pin=digest(registry))
        self.assertEqual(out['payload']['status'],'ABSTAIN');self.assertIsNone(out['payload']['prediction'])
        self.assertEqual(out['payload']['abstain_reason'],'SCHEDULE_USAGE_NOT_ESTABLISHED')

    def test_insufficient_history_stale_schedule_and_started_game_abstain(self):
        out=build_snapshot([],self.schedule,self.cid,test_model(),cutoff_utc=NOW,registry=self.registry,registry_pin=self.pin)
        self.assertEqual(out['payload']['status'],'ABSTAIN')
        self.clock.return_value=NOW+400
        self.assertEqual(self.shot(cutoff_utc=NOW+400)['payload']['abstain_reason'],'STALE_SCHEDULE')
        self.clock.return_value=START+1
        self.assertEqual(self.shot(cutoff_utc=START+1)['payload']['status'],'ABSTAIN')

    def test_repeat_insert_and_restart_preserve_original_bytes_and_legacy_tables(self):
        s=self.shot();self.assertTrue(self.insert(s));before=self.store.path.read_bytes()
        self.assertFalse(self.insert(s));self.assertEqual(before,self.store.path.read_bytes())
        reopened=SyntheticSnapshotStore(self.folder.name);self.assertFalse(self.insert(s,store=reopened))
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM predictions').fetchone()[0],0)

    def test_concurrent_same_snapshot_creates_exactly_one_row(self):
        s=self.shot()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:self.insert(s),range(2)))
        self.assertEqual(sorted(results),[False,True]);self.assertEqual(self.store.audit(registry=self.registry,registry_pin=self.pin)['snapshots'],1)

    def test_crossing_tipoff_after_insert_rolls_back_entire_transaction(self):
        s=self.shot();at=iter([NOW,START+1]);store=SyntheticSnapshotStore(self.folder.name,guard_clock=lambda:next(at))
        with self.assertRaisesRegex(ValueError,'EXPIRED_DURING_RECORDING'):self.insert(s,store)
        with store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM faz42_snapshots').fetchone()[0],0)

    def test_sqlite_lock_failure_does_not_partially_record(self):
        s=self.shot();writer=self.store.connect();writer.execute('BEGIN IMMEDIATE')
        try:
            with self.assertRaises(sqlite3.OperationalError):self.insert(s)
        finally:writer.rollback();writer.close()
        self.assertEqual(self.store.audit(registry=self.registry,registry_pin=self.pin)['snapshots'],0)

    def test_sql_update_delete_replace_and_rehashed_prediction_tamper_fail_closed(self):
        s=self.shot();self.insert(s)
        for sql in ['UPDATE faz42_snapshots SET sha256="bad"','DELETE FROM faz42_snapshots',
                    'INSERT OR REPLACE INTO faz42_snapshots SELECT * FROM faz42_snapshots']:
            with self.subTest(sql=sql),self.assertRaises(sqlite3.IntegrityError),self.store.connect() as db:db.execute(sql)
        changed=deepcopy(s);q=changed['payload']['prediction'];q['home']['quarters'][0]+=1;q['home']['first_half']+=1;q['home']['total']+=1;q['total']+=1;q['home_margin']+=1
        changed['sha256']=digest(changed['payload'])
        with self.assertRaisesRegex(ValueError,'CANNOT_REPLAY'):self.insert(changed)

    def test_real_storage_and_legacy_paths_are_explicitly_disabled(self):
        with TemporaryDirectory() as folder,self.assertRaisesRegex(ValueError,'ISOLATED_SYNTHETIC'):SyntheticSnapshotStore(folder)
        s=self.shot();s['payload']['usage']='UNPERSISTED_DRY_RUN';s['sha256']=digest(s['payload'])
        with self.assertRaisesRegex(ValueError,'REAL_STORAGE_NOT_ACTIVATED'):self.insert(s)

    def test_final_reconciliation_is_separate_idempotent_and_immutable(self):
        s=self.shot();self.insert(s);final=self.final();before=s['sha256'];self.clock.return_value=START+10003
        args=dict(asof_utc=START+10003,registry=self.registry,registry_pin=self.pin)
        self.assertTrue(self.store.record_final(self.cid,final,**args));self.assertFalse(self.store.record_final(self.cid,final,**args))
        self.assertEqual(s['sha256'],before);r=self.store.audit(registry=self.registry,registry_pin=self.pin)
        self.assertEqual(len(r['pairs']),1);self.assertIsNone(r['cohorts'][0]['metrics']);self.assertEqual(r['prospective_records'],0)
        with self.assertRaisesRegex(ValueError,'FINAL_CONFLICT'):self.store.record_final(self.cid,self.final(changed=True),**args)

    def test_final_fixture_mismatch_and_nonfinal_result_cannot_match(self):
        s=self.shot();self.insert(s);self.clock.return_value=START+10003
        with self.assertRaisesRegex(ValueError,'BINDING'):self.store.record_final(self.cid,self.final(other_time=True),asof_utc=START+10003,registry=self.registry,registry_pin=self.pin)
        raw=summary(900000099,START);raw['header']['competitions'][0]['status']['type']['completed']=False
        with self.assertRaises(ValueError):capture(raw,provider='ESPN',league='NBA',season_end_year=2027,observed_at_utc=START+10000,ingested_at_utc=START+10001)

    def test_regulation_tie_and_overtime_final_have_distinct_scopes(self):
        s=self.shot();final=self.final(overtime=True);self.clock.return_value=START+10003
        r=reconcile(s,final,asof_utc=START+10003,registry=self.registry,registry_pin=self.pin)['payload']
        self.assertEqual(r['actual_regulation'],{'home':100,'away':100});self.assertEqual(r['actual_final'],{'home':112,'away':109})
        self.assertAlmostEqual(r['period_errors']['FULL']['total'],s['payload']['prediction']['total']-200)
        probs=s['payload']['simulation']['probabilities'];self.assertAlmostEqual(r['regulation_brier'],sum((v-(i==2))**2 for i,v in enumerate(probs)))

    def test_rehashed_wrong_schedule_endpoint_is_not_source_evidence(self):
        s=deepcopy(self.schedule);s['payload']['source_url']='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=1';s['sha256']=digest(s['payload'])
        with self.assertRaisesRegex(ValueError,'ENDPOINT_MISMATCH'):validate_schedule(s,cutoff_utc=NOW,registry=self.registry,registry_pin=self.pin)

    def test_unknown_snapshot_fields_and_fake_calibration_cannot_be_rehashed(self):
        for updates in [dict(unverified_accuracy=99),dict(calibration_status='CALIBRATED')]:
            s=self.shot();s['payload'].update(updates);s['sha256']=digest(s['payload'])
            with self.subTest(updates=updates),self.assertRaises(ValueError):validate_snapshot(s,registry=self.registry,registry_pin=self.pin)

    def test_unused_cross_league_source_cannot_be_presented_as_model_input(self):
        s=self.shot();raw=source('EUROCUP')['game']
        with patch('time.time',return_value=NOW-1000):extra=capture(raw,provider='EUROLEAGUE_LIVE',league='EUROCUP',season_end_year=2027,
            observed_at_utc=NOW-1100,ingested_at_utc=NOW-1050,usage='SYNTHETIC_TEST',registry=self.registry,registry_pin=self.pin)
        p=s['payload'];p['history'].append(extra);p['source_digest']=digest(dict(schedule=p['schedule']['sha256'],history=sorted(o['sha256'] for o in p['history'])))
        s['sha256']=digest(p)
        with self.assertRaisesRegex(ValueError,'CANNOT_REPLAY'):self.insert(s)

    def test_model_manifest_is_bound_to_clean_feature_head_and_rejects_source_race(self):
        from faz42_snapshot import model_manifest
        good=['feature/faz42-test','','a'*40,str(NOW-100),'a'*40,'']
        with patch('faz42_snapshot.subprocess.check_output',side_effect=good):
            m=model_manifest();self.assertEqual(m['payload']['git_sha'],'a'*40)
            self.assertEqual(m['sha256'],digest(m['payload']))
        bad=['feature/faz42-test','','a'*40,str(NOW-100),'b'*40]
        with patch('faz42_snapshot.subprocess.check_output',side_effect=bad),self.assertRaisesRegex(ValueError,'SOURCE_CHANGED_DURING_MANIFEST'):
            model_manifest()
