"""Synthetic research-clock fixtures, never evidence of real prediction accuracy."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tarfile
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from historical_research import reconstruct, validate_research_example
from nba_research_store import ResearchStore, validate_summary
from prediction_inputs import digest
from research_recovery import make_bundle, verify_bundle
from shadow_features import replay_features
from shadow_ridge import train, predict
from faz32_collect import collect, import_downloads, write_json


def summary(fixture, start, reverse=False):
    raw=json.loads((Path(__file__).parent/'fixtures/espn-summary-401909903.json').read_text())
    h=raw['header'];c=h['competitions'][0];h['id']=c['id']=str(fixture)
    dt=datetime.fromtimestamp(start,timezone.utc);c['date']=dt.isoformat()
    h['season']['year']=dt.year+int(dt.month>=7)
    if reverse:
        for row in c['competitors']+raw['boxscore']['teams']:
            row['homeAway']='away' if row['homeAway']=='home' else 'home'
    return raw


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name);self.now=int(time.time())
        self.cutoff=int(datetime(2026,11,1,tzinfo=timezone.utc).timestamp())
        self.store=ResearchStore(self.root/'research.sqlite',{'19','2'})
        self.source=summary(900000001,self.cutoff-86400)
        self.ref=dict(path='SYNTHETIC_TEST_ARCHIVE',file_sha256='a'*64)

    def ingest(self, raw=None, observed=None):
        return self.store.ingest(raw or self.source,observed or self.cutoff-1000,'ARCHIVED_SOURCE',self.ref)

    def ready_example(self):
        for i in range(6):self.ingest(summary(900000001+i,self.cutoff-(i+1)*86400,bool(i%2)))
        target=dict(provider='ESPN',provider_fixture_id='900000020',start_ts_utc=self.cutoff+3600,home_team_id='19',away_team_id='2')
        f=reconstruct(self.store,target,self.cutoff)
        label=dict(summary=summary(900000020,target['start_ts_utc']),observed_utc=self.now)
        return dict(features=f,label=label,label_sha256=digest(label))

    def test_duplicate_keeps_original_ingestion_and_does_not_increase_games(self):
        self.assertTrue(self.ingest());before=self.store.observations()
        self.assertFalse(self.ingest());self.assertEqual(before,self.store.observations())
        self.ingest(observed=self.cutoff-500)
        self.assertEqual(self.store.coverage()['observations'],2)
        self.assertEqual(self.store.coverage()['distinct_games'],1)

    def test_archive_source_and_actual_ingestion_clocks_are_distinct(self):
        self.ingest();p=self.store.observations()[0]['payload']
        self.assertLess(p['source_observed_utc'],self.cutoff)
        self.assertGreater(p['ingested_utc'],self.cutoff)
        self.assertEqual(self.store.select(self.cutoff),[])
        self.assertEqual(len(self.store.select(self.cutoff,'RESEARCH_SOURCE_CLOCK')),1)

    def test_equal_cutoff_and_later_observations_are_excluded(self):
        self.ingest(observed=self.cutoff)
        self.assertEqual(self.store.select(self.cutoff,'RESEARCH_SOURCE_CLOCK'),[])
        self.assertEqual(len(self.store.select(self.cutoff+1,'RESEARCH_SOURCE_CLOCK')),1)

    def test_select_uses_only_latest_pre_cutoff_source(self):
        self.ingest();self.ingest(observed=self.cutoff-500);self.ingest(observed=self.now)
        rows=self.store.select(self.cutoff,'RESEARCH_SOURCE_CLOCK')
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['payload']['source_observed_utc'],self.cutoff-500)

    def test_same_team_same_start_different_provider_id_is_rejected(self):
        self.ingest();raw=deepcopy(self.source);h=raw['header'];h['id']=h['competitions'][0]['id']='900000002'
        with self.assertRaisesRegex(ValueError,'alias conflict'):self.ingest(raw)

    def test_inconsistent_season_team_final_and_periods_are_rejected(self):
        cases=[]
        r=deepcopy(self.source);r['header']['season']['year']+=1;cases.append(r)
        r=deepcopy(self.source);r['header']['competitions'][0]['competitors'][0]['team']['id']='999';cases.append(r)
        r=deepcopy(self.source);r['header']['competitions'][0]['competitors'][0]['linescores'][0]['displayValue']='1';cases.append(r)
        r=deepcopy(self.source);r['header']['competitions'][0]['status']['type']['completed']=False;cases.append(r)
        for raw in cases:
            with self.subTest(raw=raw['header']['id']),self.assertRaises((ValueError,KeyError)):self.ingest(raw)
        self.assertEqual(self.store.coverage()['distinct_games'],0)

    def test_future_time_and_unproven_archive_are_rejected(self):
        with self.assertRaises(ValueError):self.ingest(observed=self.now+100)
        with self.assertRaises(ValueError):self.store.ingest(self.source,self.cutoff,'ARCHIVED_SOURCE',{})
        with self.assertRaises(ValueError):self.store.ingest(self.source,self.cutoff,'NEW_DOWNLOAD',{})

    def test_sql_updates_and_deletes_are_blocked(self):
        self.ingest()
        with sqlite3.connect(self.store.path) as db:
            for sql in ('DELETE FROM observations','UPDATE observations SET ingested_utc=1'):
                with self.assertRaises(sqlite3.IntegrityError):db.execute(sql)

    def test_missing_pace_is_not_filled_and_conflicting_same_clock_is_rejected(self):
        raw=deepcopy(self.source);del raw['boxscore']
        self.ingest(raw)
        self.assertEqual(self.store.coverage()['pace_supported_observations'],0)
        with self.assertRaisesRegex(ValueError,'same-clock'):self.ingest(self.source)

    def test_changed_index_is_detected_independently_of_payload_digest(self):
        self.ingest()
        with sqlite3.connect(self.store.path) as db:
            db.execute('DROP TRIGGER research_no_UPDATE')
            db.execute("UPDATE observations SET fixture_id='999'")
        with self.assertRaisesRegex(ValueError,'index/payload'):self.store.observations()

    def test_rehashed_payload_does_not_bypass_semantic_validation(self):
        self.ingest()
        with sqlite3.connect(self.store.path) as db:
            db.execute('DROP TRIGGER research_no_UPDATE')
            raw=json.loads(db.execute('SELECT payload FROM observations').fetchone()[0]);raw['facts']['periods']['home'][0]+=1
            db.execute('UPDATE observations SET payload=?,sha256=?',(json.dumps(raw),digest(raw)))
        with self.assertRaises(ValueError):self.store.observations()

    def test_research_reconstruction_is_ready_but_never_original_live_snapshot(self):
        e=self.ready_example();f,p=validate_research_example(e)
        self.assertEqual(f['status'],'READY');self.assertEqual(len(f['source_records']),6)
        self.assertGreater(f['created_utc'],f['cutoff_utc'])
        with self.assertRaises(ValueError):replay_features(e['features'])
        self.assertEqual(train([e],'a'*40,research=True)['status'],'NOT_TRAINED')

    def test_features_are_replayed_and_late_labels_are_not_source_features(self):
        e=self.ready_example();f=e['features']['payload'];f['values']['home_offense']+=1
        e['features']['sha256']=digest(f)
        with self.assertRaisesRegex(ValueError,'changed retrospective'):validate_research_example(e)

    def test_same_time_source_order_has_canonical_semantic_replay(self):
        e=self.ready_example()
        # Different teams may legitimately play concurrently; insertion order
        # cannot change the source replay digest.
        raw=summary(900000009,self.cutoff-86400)
        for row in raw['header']['competitions'][0]['competitors']+raw['boxscore']['teams']:
            row['team']['id']={'19':'4','2':'5'}[row['team']['id']]
        other=ResearchStore(self.root/'other.sqlite',{'19','2','4','5'})
        for r in self.store.observations():other.ingest(r['payload']['summary'],r['payload']['source_observed_utc'],'ARCHIVED_SOURCE',self.ref)
        other.ingest(raw,self.cutoff-1000,'ARCHIVED_SOURCE',self.ref)
        e['features']=reconstruct(other,e['features']['payload']['target'],self.cutoff)
        self.assertEqual(validate_research_example(e)[0]['status'],'READY')

    def test_new_download_clock_is_retained_on_delayed_import(self):
        ref=dict(file_sha256='a'*64,collection_started_utc=self.cutoff-100)
        self.store.ingest(self.source,self.cutoff,'NEW_DOWNLOAD',ref)
        self.assertEqual(self.store.observations()[0]['payload']['source_observed_utc'],self.cutoff)
        self.assertEqual(self.store.select(self.cutoff,'RESEARCH_SOURCE_CLOCK'),[])

    def test_research_training_and_prospective_training_are_separate(self):
        # Synthetic numeric IDs and archived clocks, explicitly not real results.
        examples=[]
        # Stay inside a single NBA season; July is deliberately a season guard.
        start=int(datetime(2025,11,15,tzinfo=timezone.utc).timestamp())
        for i in range(100):
            cutoff=start+i*86400
            local=ResearchStore(self.root/f'synthetic-{i}.sqlite',{'19','2'})
            for j in range(6):
                raw=summary(800000000+i*10+j,cutoff-(j+1)*86400,bool(j%2))
                local.ingest(raw,cutoff-1000,'ARCHIVED_SOURCE',self.ref)
            target=dict(provider='ESPN',provider_fixture_id=str(700000000+i),start_ts_utc=cutoff+3600,home_team_id='19',away_team_id='2')
            label=dict(summary=summary(target['provider_fixture_id'],target['start_ts_utc']),observed_utc=cutoff+10800)
            examples.append(dict(features=reconstruct(local,target,cutoff),label=label,label_sha256=digest(label)))
        r=train(examples,'a'*40,research=True)
        self.assertEqual(r['status'],'TRAINED_EXPERIMENTAL')
        self.assertTrue(r['artifact']['payload']['research_only'])
        with self.assertRaises(ValueError):train(examples,'a'*40)
        with patch('shadow_ridge.replay_features',return_value={}):
            with self.assertRaisesRegex(ValueError,'research artifact'):predict(r['artifact'],{})
        # A result not observed by the validation boundary must be purged.
        examples[59]['label']['observed_utc']=examples[60]['features']['payload']['cutoff_utc']
        examples[59]['label_sha256']=digest(examples[59]['label'])
        self.assertEqual(train(examples,'a'*40,research=True)['status'],'NOT_TRAINED')

    def test_recovery_preserves_source_bytes_and_replays_sqlite_data(self):
        self.ingest();before=Path(self.store.path).read_bytes();path=self.root/'bundle.tar.gz'
        info=make_bundle({'research.sqlite':self.store.path},path,'a'*40)
        self.assertFalse(info['external_uploaded']);self.assertEqual(path.stat().st_mode & 0o777,0o600)
        result=verify_bundle(path)
        self.assertEqual(result['files'][0]['research_coverage']['distinct_games'],1)
        self.assertFalse(result['cloud_session_replacement_tested'])
        self.assertEqual(Path(self.store.path).read_bytes(),before)
        with self.assertRaises(FileExistsError):make_bundle({'research.sqlite':self.store.path},path,'a'*40)

    def test_live_export_keeps_actual_materialization_clock_and_source_read_only(self):
        from faz32 import export_live_periods
        with patch('time.time',return_value=self.now-1):self.ready_example()
        before=Path(self.store.path).read_bytes();path=self.root/'periods.json'
        r=export_live_periods(self.store.path,path)
        self.assertEqual(r['distinct_games'],6);self.assertEqual(r['predictions_created'],0)
        self.assertEqual(path.stat().st_mode & 0o777,0o600)
        self.assertEqual(Path(self.store.path).read_bytes(),before)
        records=json.loads(path.read_text())
        self.assertTrue(all(x['payload']['materialized_utc']>=self.now for x in records))
        from period_feature_layer import select_available
        self.assertEqual(select_available(records,self.cutoff),[])
        with self.assertRaises(FileExistsError):export_live_periods(self.store.path,path)

    def test_recovery_rejects_path_traversal_and_bad_checksum(self):
        for filename,data in (('../escape.sqlite',b'bad'),('data.sqlite',b'corrupt')):
            path=self.root/('bad'+str(len(filename))+'.tar.gz')
            with tarfile.open(path,'w:gz') as tar:
                raw=json.dumps(dict(files={filename:'a'*64},source_version='a'*40)).encode()
                for name,body in [('manifest.json',raw),(filename,data)]:
                    info=tarfile.TarInfo(name);info.size=len(body);tar.addfile(info,io.BytesIO(body))
            with self.assertRaises(ValueError):verify_bundle(path)


class CollectorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup);self.root=Path(self.folder.name)
        self.api=AsyncMock();self.api.last_http_status=403
        self.api._load_teams.return_value=[dict(team=dict(id=k,displayName=k,abbreviation=k)) for k in ('19','2')]

    async def test_blocked_provider_is_not_successful_empty_history(self):
        self.api._get_json.return_value=None
        m=await collect(['20261102'],self.root/'collect',self.api)
        self.assertEqual(m['days'][0]['status'],'PROVIDER_UNAVAILABLE');self.assertEqual(m['summaries'],[])
        self.assertEqual(m['days'][0]['http_status'],403)

    async def test_rate_limit_stops_date_collection_and_is_recorded(self):
        self.api.last_http_status=429;self.api._get_json.return_value=None
        m=await collect(['20261101','20261102'],self.root/'collect',self.api)
        self.assertEqual(len(m['days']),1);self.assertEqual(m['days'][0]['http_status'],429)
        self.api._get_json.assert_awaited_once()

    async def test_incomplete_event_is_not_requested_as_final_summary(self):
        raw=summary(900000001,int(time.time())-3600);h=raw['header'];c=h['competitions'][0]
        c['status']['type']['completed']=False
        self.api._get_json.return_value=dict(events=[dict(h,date=c['date'])])
        m=await collect(['20261102'],self.root/'collect',self.api)
        self.assertEqual(m['days'][0]['not_final_or_invalid'],1)
        self.assertEqual(m['summaries'],[]);self.api._get_json.assert_awaited_once()

    async def test_manifest_identity_and_file_hash_are_verified_on_import(self):
        now=int(time.time());raw=summary(900000001,now-86400);path=self.root/'summary.json'
        sha=write_json(path,raw);event=validate_summary(raw,now,{'19','2'})['event']
        manifest=dict(directory=dict(teams={'19':{},'2':{}},observed_utc=now-1),summaries=[dict(path=str(path),file_sha256=sha,observed_utc=now,scoreboard_final=event,fixture_id='900000001')])
        mp=self.root/'manifest.json';mp.write_text(json.dumps(manifest));db=self.root/'research.sqlite'
        self.assertEqual(import_downloads(mp,db)['inserted'],1)
        self.assertEqual(import_downloads(mp,db)['idempotent'],1)
        path.write_text('{}')
        result=import_downloads(mp,db);self.assertEqual(len(result['rejected']),1)
        self.assertEqual(result['coverage']['distinct_games'],1)

    async def test_scoreboard_and_summary_conflict_is_quarantined(self):
        now=int(time.time());raw=summary(900000001,now-86400)
        h=raw['header'];event=dict(h,date=h['competitions'][0]['date'])
        bad=deepcopy(raw);bad['header']['competitions'][0]['competitors'][0]['score']='1'
        self.api._get_json.side_effect=[dict(events=[event]),bad]
        m=await collect(['20261102'],self.root/'collect',self.api)
        self.assertEqual(m['summaries'][0]['status'],'REJECTED')
        self.assertEqual(list((self.root/'collect').glob('900000001.json')),[])
