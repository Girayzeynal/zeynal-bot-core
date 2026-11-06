"""Synthetic bundles and temporary files; no real prediction storage or network."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import errno
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase,TestCase
from unittest.mock import Mock,patch

from prediction_inputs import digest
from faz43_development import DevelopmentAnalysisService
from faz44_inputs import make_bundle,IndexedInputsBackend,read_development_inputs,publish_local_bundle,collect_schedules,derive_history
from nba_research_store import ResearchStore
from faz40_archive_audit import file_sha
from tests.test_faz42_history import NOW,permitted_registry
from tests.test_faz44_runtime import inputs
from tests.test_faz32 import summary
from faz42_schedule import seal_schedule
from tests.test_faz33 import event

DAY='2026-11-06'


class IndexedBundleTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.timer=patch('time.time',return_value=NOW);self.timer.start();self.addCleanup(self.timer.stop)
        self.registry=permitted_registry();self.pin=digest(self.registry);self.i=inputs(self.registry)
        self.b=make_bundle(self.i['history'],self.i['schedules'],self.i['model'],days=[DAY,'2026-11-07'],registry=self.registry,registry_pin=self.pin)

    def backend(self,b=None,**updates):
        b=b or self.b;args=dict(trusted_sha256=b['sha256'],registry=self.registry,registry_pin=self.pin);args.update(updates)
        return IndexedInputsBackend(b,**args)

    def rehash(self,b):b['sha256']=digest(b['payload']);return b

    async def test_indexed_sources_are_deduplicated_and_positive_path_is_synthetic(self):
        p=self.b['payload'];self.assertEqual(len(p['sources']),10);self.assertEqual(len(p['schedules']),1);self.assertEqual(len(p['partitions']),6)
        backend=self.backend();service=DevelopmentAnalysisService(backend,allow_synthetic=True,registry=self.registry,registry_pin=self.pin)
        r=await service.analyze('/analyze NBA '+DAY+' 19 vs 2')
        self.assertEqual(r['status'],'PREDICTED_EXPERIMENTAL');self.assertEqual(r['prospective_records_created'],0)
        data=await backend.load_inputs('NBA',DAY);data['history'].clear()
        self.assertEqual(len((await backend.load_inputs('NBA',DAY))['history']),10)

    async def test_independent_pin_and_policy_binding_are_required(self):
        with self.assertRaisesRegex(ValueError,'PIN_MISMATCH'):self.backend(trusted_sha256='0'*64)
        with self.assertRaisesRegex(ValueError,'POLICY_BINDING'):self.backend(policy_bundle_sha256='a'*64)
        b=deepcopy(self.b);b['payload']['sources'].clear();self.rehash(b)
        with self.assertRaisesRegex(ValueError,'REFERENCE'):self.backend(b)

    async def test_cross_league_day_and_missing_references_are_refused(self):
        for kind in ('league','day','missing'):
            b=deepcopy(self.b);refs=b['payload']['partitions']['NBA:'+DAY]
            if kind=='league':b['payload']['partitions']['EUROLEAGUE:'+DAY]=deepcopy(refs)
            if kind=='day':b['payload']['partitions']['NBA:2026-11-07']=deepcopy(refs)
            if kind=='missing':refs['history_sha256'].append('a'*64)
            self.rehash(b)
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.backend(b)

    async def test_duplicate_reference_and_future_materialization_are_refused(self):
        b=deepcopy(self.b);refs=b['payload']['partitions']['NBA:'+DAY]['history_sha256'];refs.append(refs[0]);self.rehash(b)
        with self.assertRaisesRegex(ValueError,'DUPLICATE'):self.backend(b)
        b=deepcopy(self.b);b['payload']['materialized_at_utc']=NOW+1;self.rehash(b)
        with self.assertRaisesRegex(ValueError,'CLOCK'):self.backend(b)

    async def test_mixed_synthetic_and_real_history_is_refused(self):
        b=deepcopy(self.b);h=next(iter(b['payload']['sources']));o=b['payload']['sources'].pop(h)
        o['payload']['usage']='RETROSPECTIVE_RESEARCH';o['sha256']=digest(o['payload']);b['payload']['sources'][o['sha256']]=o
        for refs in b['payload']['partitions'].values():refs['history_sha256']=[o['sha256'] if v==h else v for v in refs['history_sha256']]
        self.rehash(b)
        with self.assertRaisesRegex(ValueError,'MIXED'):self.backend(b)

    async def test_file_load_is_readonly_and_old_bundle_format_still_loads(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'faz44-inputs-test.json';publish_local_bundle(path,self.b);before=path.read_bytes()
            backend=read_development_inputs(path,trusted_sha256=self.b['sha256'],registry=self.registry,registry_pin=self.pin)
            self.assertEqual(len((await backend.load_inputs('NBA',DAY))['history']),10);self.assertEqual(path.read_bytes(),before)
            p=dict(format='FAZ43_DEVELOPMENT_INPUT_BUNDLE_V1',partitions={'NBA:'+DAY:self.i});old=dict(payload=p,sha256=digest(p))
            path2=Path(folder)/'legacy.json';path2.write_text(json.dumps(old))
            backend=read_development_inputs(path2,trusted_sha256=old['sha256'])
            self.assertEqual(len((await backend.load_inputs('NBA',DAY))['history']),10)

    async def test_atomic_publication_idempotency_conflict_and_mode_600(self):
        with TemporaryDirectory() as folder:
            p=Path(folder)/'faz44-inputs-test.json'
            self.assertTrue(publish_local_bundle(p,self.b));before=p.read_bytes()
            self.assertFalse(publish_local_bundle(p,self.b));self.assertEqual(p.read_bytes(),before);self.assertEqual(p.stat().st_mode&0o777,0o600)
            b=deepcopy(self.b);b['payload']['materialized_at_utc']=NOW-1;self.rehash(b)
            with self.assertRaisesRegex(ValueError,'IMMUTABLE'):publish_local_bundle(p,b)
            self.assertEqual(p.read_bytes(),before)

    async def test_two_writers_publish_one_complete_file(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'faz44-inputs-race.json'
            with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:publish_local_bundle(path,self.b),range(2)))
            self.assertEqual(sorted(results),[False,True]);self.assertEqual(json.loads(path.read_text())['sha256'],self.b['sha256'])
            self.assertEqual(list(Path(folder).glob('.faz44-*')),[])

    async def test_disk_full_and_permission_error_leave_no_partial_target(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'faz44-inputs-errors.json'
            for target,error in [('faz44_inputs.os.fsync',OSError(errno.ENOSPC,'disk full')),('faz44_inputs.os.link',PermissionError('denied'))]:
                with self.subTest(target=target),patch(target,side_effect=error),self.assertRaises(OSError):publish_local_bundle(path,self.b)
                self.assertFalse(path.exists());self.assertEqual(list(Path(folder).glob('.faz44-*')),[])

    async def test_wrong_output_namespace_and_symlink_are_refused(self):
        with TemporaryDirectory() as folder:
            p=Path(folder)/'ordinary.json'
            with self.assertRaises(ValueError):publish_local_bundle(p,self.b)
            p.write_text('existing');link=Path(folder)/'faz44-inputs-link.json';link.symlink_to(p)
            with self.assertRaises(ValueError):publish_local_bundle(link,self.b)
            self.assertEqual(p.read_text(),'existing')

    async def test_cross_document_provider_id_and_team_slot_conflicts_are_refused(self):
        first=self.i['schedules'][0]['payload'];start=first['fixtures'][0]['fixture']['start_utc']
        for kind,reason in [('provider','PROVIDER_ID_CONFLICT'),('team','TEAM_START_CONFLICT')]:
            raw=event(start+60 if kind=='provider' else start,'900000099' if kind=='provider' else '900000100')
            if kind=='team':
                for team in raw['competitions'][0]['competitors']:
                    if team['homeAway']=='away':team['team']['id']='1';team['team']['abbreviation']='ATL'
            with patch('time.time',return_value=NOW-30):
                conflicting=seal_schedule({'events':[raw]},provider='ESPN',league='NBA',season_end_year=2027,
                    source_url=first['source_url'],observed_at_utc=NOW-40,ingested_at_utc=NOW-35,usage='SYNTHETIC_TEST',registry=self.registry,registry_pin=self.pin)
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,reason):
                make_bundle(self.i['history'],self.i['schedules']+[conflicting],self.i['model'],days=[DAY],registry=self.registry,registry_pin=self.pin)

    async def test_partial_collection_failure_is_not_an_empty_successful_calendar(self):
        for statuses in [('HTTP_403',),('DOCUMENT_RECEIVED','HTTP_429'),('ABSTAIN_INVALID_SCHEDULE',)]:
            b=deepcopy(self.b);b['payload']['collection']={'schedule_collection':{'sources':[dict(league='NBA',status=s) for s in statuses]}};self.rehash(b)
            with self.subTest(statuses=statuses),self.assertRaisesRegex(ValueError,'SOURCE_COLLECTION_UNAVAILABLE'):
                await self.backend(b).load_inputs('NBA','2026-11-07')

    async def test_verified_empty_catalog_remains_distinct_from_network_failure(self):
        b=deepcopy(self.b);b['payload']['collection']={'schedule_collection':{'sources':[dict(league='NBA',status='DOCUMENT_RECEIVED')]}};self.rehash(b)
        self.assertEqual((await self.backend(b).load_inputs('NBA','2026-11-07'))['schedules'],[])


class DerivationAndCollectionTests(TestCase):
    def test_sqlite_derivation_preserves_original_and_uses_new_real_ingestion_clock(self):
        with TemporaryDirectory() as folder,patch('time.time',return_value=NOW-5) as clock:
            path=Path(folder)/'research.sqlite';store=ResearchStore(path,{'19','2'})
            store.ingest(summary(401900001,NOW-86400),NOW-1000,'ARCHIVED_SOURCE',dict(path='SYNTHETIC_TEST',file_sha256='a'*64))
            before=file_sha(path);clock.return_value=NOW
            rows,info=derive_history(path)
            self.assertEqual(file_sha(path),before);self.assertEqual(info['canonical_games'],1)
            p=rows[0]['payload'];self.assertEqual(p['ingested_at_utc'],NOW);self.assertEqual(p['materialized_at_utc'],NOW)
            self.assertEqual(p['observed_at_utc'],NOW-1000);self.assertEqual(p['usage_status'],'UNKNOWN')
            self.assertIn('_faz44_derivation',p['raw'])

    def test_default_collection_is_network_free_and_403_is_retained(self):
        collector=Mock();s,r=collect_schedules(collector=collector);collector.assert_not_called();self.assertEqual(r['network_requests'],0)
        collector.side_effect=lambda url,**kw:dict(source_url=url,status='HTTP_403',http_status=403)
        s,r=collect_schedules(live=True,collector=collector)
        self.assertEqual(s,[]);self.assertEqual(r['network_requests'],5);self.assertTrue(all(x['status']=='HTTP_403' for x in r['sources']))
