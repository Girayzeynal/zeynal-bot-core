"""Synthetic prospective time travel stays in a SYNTHETIC_TEST ledger."""
import asyncio
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock,patch

from faz33 import Runner,ProviderUnavailable
from prospective_cuts import CutLedger,inspect,HORIZONS,due,validate_packet
from tests.test_faz32 import summary
from nba_research_store import ResearchStore
from nba_season_2027 import parse_scheduled,START,END,policy
from prediction_inputs import digest

BASE=int(datetime(2026,11,2,8,tzinfo=timezone.utc).timestamp())


class Clock:
    def __init__(self):self.now=BASE
    def time(self):return self.now
    async def sleep(self,seconds):self.now+=max(1,int(seconds)+1)


def event(start=BASE+86400,fixture='900000020'):
    r=summary(fixture,start);h=r['header'];c=h['competitions'][0]
    status=dict(type=dict(state='pre',completed=False,name='STATUS_SCHEDULED'))
    c['status']=deepcopy(status);h['status']=deepcopy(status);h['date']=c['date']
    return h


class CutTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup);self.root=Path(self.folder.name)
        self.clock=Clock();self.time_patch=patch('time.time',side_effect=self.clock.time);self.time_patch.start();self.addCleanup(self.time_patch.stop)
        self.sleep_patch=patch('faz33.asyncio.sleep',side_effect=self.clock.sleep);self.sleep_patch.start();self.addCleanup(self.sleep_patch.stop)
        self.store=ResearchStore(self.root/'research.sqlite',{'19','2'})
        self.clock.now=BASE-600
        for i in range(6):
            raw=summary(900000001+i,BASE-(i+2)*86400,bool(i%2))
            self.store.ingest(raw,BASE-1000,'ARCHIVED_SOURCE',dict(path='SYNTHETIC_TEST',file_sha256='a'*64))
        self.clock.now=BASE
        self.ledger=CutLedger(self.root/'cuts.sqlite','SYNTHETIC_TEST')
        self.api=AsyncMock();self.api.last_http_status=200;self.api._blocked_until=0
        self.runner=Runner(self.ledger,self.store,self.api,model_sha='a'*40,timeout=.01)
        self.runner.directory={'19':dict(abbr='ORL',name='Orlando Magic'),'2':dict(abbr='BOS',name='Boston Celtics')}
        self.runner.directory_observation=dict(teams=deepcopy(self.runner.directory),sha256=digest(self.runner.directory),source_observed_utc=BASE-10,ingested_utc=BASE-10)
        self.raw=event();self.fixture=parse_scheduled(self.raw,{'19','2'});self.item=dict(fixture=self.fixture,schedule={})
        async def recheck(fixture):
            return dict(event=deepcopy(self.raw),sha256=digest(self.raw),source_observed_utc=int(self.clock.now),ingested_utc=int(self.clock.now),source_url='SYNTHETIC_TEST')
        self.runner.recheck=AsyncMock(side_effect=recheck)

    def packet(self):
        with self.ledger.connect() as db:return json.loads(db.execute('SELECT payload FROM faz33_cuts ORDER BY recorded_utc LIMIT 1').fetchone()[0])

    async def capture(self,horizon='T24H'):return await self.runner.capture(self.item,horizon,refresh=False)

    async def test_reference_features_and_no_model_are_atomic(self):
        result=await self.capture();p=self.packet()
        self.assertEqual(result['status'],'RECORDED');self.assertEqual(p['shadow']['status'],'NO_MODEL_AVAILABLE')
        self.assertIsNone(p['shadow']['prediction']);self.assertEqual(p['features']['payload']['status'],'READY')
        self.assertEqual([x['stage'] for x in p['reference']['bundle']['stages']],['FAZ13','FAZ22','FAZ23'])
        self.assertIn('multilayer',p['reference']['bundle']);self.assertIn('UNVERIFIED_ROSTERS',p['missing_data'])
        r=inspect(self.ledger.path);self.assertEqual(r['synthetic_cuts'],1);self.assertEqual(r['prospective_cuts'],0)

    async def test_three_horizons_count_one_game_and_no_fabricated_live_performance(self):
        for horizon in HORIZONS:
            self.clock.now=self.fixture['start_ts_utc']-HORIZONS[horizon]
            await self.capture(horizon)
        before=Path(self.ledger.path).read_bytes();r=inspect(self.ledger.path)
        self.assertEqual(r['synthetic_cuts'],3);self.assertEqual(r['distinct_games'],1)
        self.assertEqual(r['eligible_training_examples'],0);self.assertEqual(r['verified_final_games'],0)
        self.assertEqual(Path(self.ledger.path).read_bytes(),before)

    async def test_repeated_tick_does_not_regenerate_or_replace_cut(self):
        await self.capture();before=Path(self.ledger.path).read_bytes()
        self.runner.recheck.reset_mock();r=await self.capture()
        self.assertEqual(r['status'],'ALREADY_RECORDED');self.runner.recheck.assert_not_awaited()
        self.assertEqual(Path(self.ledger.path).read_bytes(),before)

    async def test_early_missed_and_started_cuts_are_refused(self):
        for when in (BASE-1,BASE+301,self.fixture['start_ts_utc']):
            self.clock.now=when
            with self.assertRaises(ValueError):await self.capture()
        with self.ledger.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM faz33_cuts').fetchone()[0],0)

    async def test_live_source_sha_change_refuses_generation_before_network(self):
        self.runner.verify_source=True
        with patch('faz33.subprocess.check_output',side_effect=['b'*40+'\n','feature/nba-command-20261104\n','']):
            with self.assertRaisesRegex(ValueError,'SOURCE_VERSION_CHANGED'):await self.capture()
        self.runner.recheck.assert_not_awaited()

    async def test_rescheduled_or_postponed_precommit_check_refuses_write(self):
        first=await self.runner.recheck(self.fixture);changed=deepcopy(first)
        changed['event']['status']['type']['name']='STATUS_POSTPONED';changed['sha256']=digest(changed['event'])
        self.runner.recheck.side_effect=[first,changed]
        with self.assertRaises(ValueError):await self.capture()
        self.assertFalse(self.ledger.has(self.fixture['provider_fixture_id'],'T24H'))

    async def test_actual_recording_time_cannot_be_backdated(self):
        await self.capture();p=self.packet();self.clock.now=self.fixture['start_ts_utc']+1
        with self.assertRaisesRegex(ValueError,'chronology'):self.ledger.insert(p)

    async def test_ingestion_after_cutoff_is_refused_even_if_hashes_are_recomputed(self):
        await self.capture();p=self.packet();p['sources'][0]['ingested_utc']=p['cutoff_utc']+1
        with self.assertRaisesRegex(ValueError,'cutoff leak'):validate_packet(p,int(self.clock.now),self.ledger.mode)

    async def test_reference_numerical_tamper_cannot_be_rehashed_into_validity(self):
        await self.capture();p=self.packet();p['reference']['inputs']['payload']['expected_home']+=1
        p['reference']['inputs']['sha256']=digest(p['reference']['inputs']['payload'])
        with self.assertRaises(ValueError):validate_packet(p,int(self.clock.now),self.ledger.mode)

    async def test_insert_failure_rolls_back_fixture_and_packet(self):
        with self.ledger.connect() as db:db.execute("CREATE TRIGGER fail_cut BEFORE INSERT ON faz33_cuts BEGIN SELECT RAISE(ABORT,'SYNTHETIC_TEST_FAILURE'); END")
        with self.assertRaises(sqlite3.IntegrityError):await self.capture()
        with self.ledger.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM faz33_fixtures').fetchone()[0],0)

    async def test_final_is_separate_idempotent_and_training_horizon_is_explicit(self):
        for horizon in HORIZONS:
            self.clock.now=self.fixture['start_ts_utc']-HORIZONS[horizon];await self.capture(horizon)
        with self.ledger.connect() as db:before=db.execute('SELECT * FROM faz33_cuts').fetchall()
        self.clock.now=self.fixture['start_ts_utc']+10800
        raw=summary(self.fixture['provider_fixture_id'],self.fixture['start_ts_utc'])
        self.assertTrue(self.ledger.record_final(raw,int(self.clock.now)));self.assertFalse(self.ledger.record_final(raw,int(self.clock.now)))
        with self.ledger.connect() as db:self.assertEqual(db.execute('SELECT * FROM faz33_cuts').fetchall(),before)
        r=inspect(self.ledger.path);self.assertEqual(r['verified_final_games'],1)
        self.assertEqual(r['synthetic_eligible_examples'],1);self.assertEqual(r['eligible_training_examples'],0)
        self.assertEqual(r['ready_unique_feature_label_games'],1)

    async def test_final_unknown_id_or_nonfinal_is_not_recorded(self):
        await self.capture();self.clock.now=self.fixture['start_ts_utc']+10800
        raw=summary(900000099,self.fixture['start_ts_utc'])
        with self.assertRaises(ValueError):self.ledger.record_final(raw,int(self.clock.now))
        with self.assertRaises(ValueError):self.ledger.record_final(dict(header=self.raw),int(self.clock.now))

    async def test_mode_and_original_sql_rows_cannot_be_modified(self):
        await self.capture()
        with self.assertRaises(ValueError):CutLedger(self.ledger.path,'PROSPECTIVE')
        with self.ledger.connect() as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('INSERT OR REPLACE INTO faz33_cuts SELECT * FROM faz33_cuts')
            for sql in ('DELETE FROM faz33_cuts',"UPDATE faz33_cuts SET sha256='bad'",'DELETE FROM faz33_evaluations',"UPDATE faz33_meta SET mode='PROSPECTIVE'"):
                # Empty evaluation DELETE has no row; all populated immutable tables are guarded.
                if 'evaluations' in sql:continue
                with self.assertRaises(sqlite3.IntegrityError):db.execute(sql)

    async def test_provider_error_status_and_persistent_retry_are_explicit(self):
        for code in (403,429):
            self.api.last_http_status=code;self.api._get_json.return_value=None
            with self.assertRaises(ProviderUnavailable) as raised:await self.runner.fetch('SYNTHETIC_TEST')
            self.assertEqual(raised.exception.status,'HTTP_'+str(code))
        self.runner.discover=AsyncMock(side_effect=ProviderUnavailable('HTTP_429',BASE+60))
        r=await self.runner.tick();self.assertEqual(r['status'],'HTTP_429')
        self.runner.discover.reset_mock();r=await self.runner.tick();self.assertEqual(r['status'],'PROVIDER_COOLDOWN');self.runner.discover.assert_not_awaited()

    async def test_network_and_timeout_are_not_empty_success(self):
        self.api._get_json.side_effect=ConnectionError('synthetic disconnect')
        with self.assertRaises(ProviderUnavailable) as r:await self.runner.fetch('SYNTHETIC_TEST')
        self.assertEqual(r.exception.status,'NETWORK_UNAVAILABLE')
        self.api._get_json.side_effect=asyncio.TimeoutError()
        with self.assertRaises(ProviderUnavailable) as r:await self.runner.fetch('SYNTHETIC_TEST')
        self.assertEqual(r.exception.status,'TIMEOUT')

    async def test_dry_run_keeps_database_bytes_and_skips_generation(self):
        self.runner.discover=AsyncMock(return_value=([self.item],[]));self.runner.capture=AsyncMock()
        before=Path(self.ledger.path).read_bytes();r=await self.runner.tick(dry_run=True)
        self.assertEqual(r['status'],'DRY_RUN');self.assertEqual(r['predictions_written'],0)
        self.runner.capture.assert_not_awaited();self.assertEqual(Path(self.ledger.path).read_bytes(),before)

    async def test_bounded_development_loop_runs_automatically_and_stops(self):
        from faz33 import development_ticks
        self.runner.tick=AsyncMock(side_effect=[dict(status='HTTP_429'),dict(status='PROVIDER_COOLDOWN'),dict(status='TICK_COMPLETE')])
        results=[r async for r in development_ticks(self.runner,ticks=3,interval=60,dry_run=True)]
        self.assertEqual(len(results),3);self.assertEqual(self.runner.tick.await_count,3)
        self.assertEqual(results[1]['status'],'PROVIDER_COOLDOWN')
        with self.assertRaises(ValueError):[r async for r in development_ticks(self.runner,ticks=0)]

    async def test_recovery_replays_three_synthetic_cuts_and_final_in_clean_python_process(self):
        from research_recovery import make_bundle
        from faz33_restore_check import verify_clean_process
        for horizon in HORIZONS:
            self.clock.now=self.fixture['start_ts_utc']-HORIZONS[horizon];await self.capture(horizon)
        self.clock.now=self.fixture['start_ts_utc']+10800
        self.ledger.record_final(summary(self.fixture['provider_fixture_id'],self.fixture['start_ts_utc']),int(self.clock.now))
        bundle=self.root/'synthetic-recovery.tar.gz';make_bundle({'cuts.sqlite':self.ledger.path},bundle,'a'*40)
        result=verify_clean_process(bundle)
        self.assertFalse(result['new_codex_cloud_session_tested'])
        audited=result['verification']['files'][0]['prospective_cut_audit']
        self.assertEqual(audited['synthetic_cuts'],3);self.assertEqual(audited['verified_final_games'],1)
        self.assertEqual(audited['synthetic_eligible_examples'],1);self.assertEqual(audited['prospective_cuts'],0)

    async def test_complete_tick_refreshes_real_shape_history_records_cut_and_later_final(self):
        directory=dict(sports=[dict(leagues=[dict(teams=[dict(team=dict(id=k,abbreviation=v['abbr'],displayName=v['name'])) for k,v in self.runner.directory.items()])])])
        originals={r['payload']['facts']['event']['provider_fixture_id']:r['payload']['summary'] for r in self.store.observations()}
        schedule=[]
        for raw in originals.values():
            e=deepcopy(raw['header']);e['date']=e['competitions'][0]['date'];e['season'].pop('type',None)
            for row in e['competitions'][0]['competitors']:row['score']=dict(value=float(row['score']),displayValue=row['score'])
            schedule.append(e)
        async def provider(url):
            if url.endswith('/teams'):return directory
            if '/scoreboard?' in url:return dict(events=[self.raw])
            if '/schedule?' in url:return dict(season=dict(year=2027,type=2),events=schedule)
            fid=url.split('event=')[-1]
            if fid==self.fixture['provider_fixture_id']:
                return dict(header=self.raw) if self.clock.now<self.fixture['start_ts_utc'] else summary(fid,self.fixture['start_ts_utc'])
            return originals[fid]
        self.api._get_json.side_effect=provider
        self.runner.recheck=Runner.recheck.__get__(self.runner)
        r=await self.runner.tick();self.assertEqual(r['status'],'TICK_COMPLETE');self.assertEqual(r['predictions_written'],1)
        self.assertEqual(r['actions'][0]['shadow_status'],'NO_MODEL_AVAILABLE')
        self.clock.now=self.fixture['start_ts_utc']+10800
        r=await self.runner.tick();self.assertEqual(r['actions'][0]['status'],'FINAL_RECORDED')
        report=inspect(self.ledger.path,'T24H')
        self.assertEqual(report['synthetic_eligible_examples'],1);self.assertEqual(report['eligible_training_examples'],0)


class SeasonTests(unittest.TestCase):
    def test_official_nba_boundaries_include_final_us_night_and_exclude_preseason(self):
        self.assertEqual(policy()['payload']['regular_start_local'],'2026-10-20')
        for start in (START,END-1):self.assertEqual(parse_scheduled(event(start),{'19','2'})['start_ts_utc'],start)
        for start in (START-1,END):
            with self.assertRaises(ValueError):parse_scheduled(event(start),{'19','2'})

    def test_wrong_season_type_unknown_team_and_contradictory_status_are_refused(self):
        for mutate in (lambda e:e['season'].update(type=1),lambda e:e['season'].update(year=2026),lambda e:e['status']['type'].update(name='STATUS_POSTPONED'),lambda e:e['competitions'][0].update(timeValid=False)):
            e=event();mutate(e)
            with self.assertRaises(ValueError):parse_scheduled(e,{'19','2'})
        with self.assertRaises(ValueError):parse_scheduled(event(),{'2'})


class HistoryContractTests(unittest.TestCase):
    def payload(self):
        raw=summary(900000001,BASE-86400);event=deepcopy(raw['header']);event['date']=event['competitions'][0]['date']
        event['season'].pop('type',None)
        for row in event['competitions'][0]['competitors']:
            row['score']=dict(value=float(row['score']),displayValue=row['score'])
        return dict(season=dict(year=2027,type=2),events=[event])

    def test_real_provider_score_object_and_response_level_type_are_normalized(self):
        from nba_history_contract import completed_history
        p=self.payload();before=deepcopy(p);rows=completed_history(p,BASE,'19')
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['provider_fixture_id'],'900000001');self.assertEqual(p,before)

    def test_score_object_contradiction_and_unknown_scope_are_refused(self):
        from nba_history_contract import completed_history
        p=self.payload();p['events'][0]['competitions'][0]['competitors'][0]['score']['value']+=1
        with self.assertRaises(ValueError):completed_history(p,BASE,'19')
        p=self.payload();p['season'].pop('type')
        with self.assertRaises(ValueError):completed_history(p,BASE,'19')

    def test_wrong_team_and_duplicate_conflicting_history_are_refused(self):
        from nba_history_contract import completed_history
        with self.assertRaises(ValueError):completed_history(self.payload(),BASE,'999')
        p=self.payload();p['events']*=2
        self.assertEqual(len(completed_history(p,BASE,'19')),1)


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup);root=Path(self.folder.name)
        self.store=ResearchStore(root/'history.sqlite',{'19','2'});self.ledger=CutLedger(root/'cuts.sqlite','SYNTHETIC_TEST')
        self.api=AsyncMock();self.api.last_http_status=200
        self.runner=Runner(self.ledger,self.store,self.api,model_sha='a'*40)
        self.directory=dict(sports=[dict(leagues=[dict(teams=[dict(team=dict(id=k,abbreviation=k,displayName=k)) for k in ('19','2')])])])

    async def test_dynamic_discovery_deduplicates_days_and_quarantines_postponed(self):
        e=event();bad=deepcopy(e);bad['id']=bad['competitions'][0]['id']='900000099'
        bad['status']['type']['name']='STATUS_POSTPONED';bad['competitions'][0]['status']['type']['name']='STATUS_POSTPONED'
        with patch('time.time',return_value=BASE):
            self.api._get_json.side_effect=[self.directory,dict(events=[e,bad]),dict(events=[deepcopy(e)]),dict(events=[])]
            rows,rejected=await self.runner.discover()
        self.assertEqual(len(rows),1);self.assertEqual(len(rejected),1)
        self.assertEqual(rows[0]['schedule']['sha256'],digest(rows[0]['schedule']['event']))
        self.assertEqual(self.api._get_json.await_count,4)

    async def test_provider_alias_conflict_rejects_whole_schedule(self):
        e=event();alias=deepcopy(e);alias['id']=alias['competitions'][0]['id']='900000099'
        with patch('time.time',return_value=BASE):
            self.api._get_json.side_effect=[self.directory,dict(events=[e,alias])]
            with self.assertRaisesRegex(ValueError,'SAME_TEAM_START_ALIAS'):await self.runner.discover()

    async def test_future_summary_recheck_uses_explicit_status_and_identity(self):
        e=event();fixture=parse_scheduled(e,{'19','2'})
        self.api._get_json.return_value=dict(header=e)
        observation=await self.runner.recheck(fixture)
        self.assertEqual(parse_scheduled(observation['event'],{'19','2'}),fixture)
        self.api._get_json.return_value=dict(header=event(BASE+86400+60))
        with self.assertRaises(ValueError):await self.runner.recheck(fixture)
