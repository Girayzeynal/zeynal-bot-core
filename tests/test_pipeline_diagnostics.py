"""Pipeline failure reproductions; synthetic providers, no real API calls."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,IsolatedAsyncioTestCase
from unittest.mock import patch

from core.team_identity import digest
from hybrid_engine.provider_access import ProviderAccess
from hybrid_engine.provider_bridge import ProviderBridge,render
from tests.test_provider_bridge import FakeProvider,SNAPSHOT,NOW as PROVIDER_NOW
from tests.test_europe_integration import Source
from tests.test_season_archive_audit import NOW
from hybrid_engine.europe_models import prepare,PreparedEurope,season_url
from hybrid_engine.europe_live import EuropeanService
from hybrid_engine.europe_premium_ui import projection
from hybrid_engine.europe_data import EuropeanDataReview,context
from hybrid_engine.intervals import prediction_intervals
from hybrid_engine.boxes import publish_json
from hybrid_engine.pipeline_audit import audit,inventory,audit_europe


class EvidenceCapacityTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.clock=patch('time.time',return_value=PROVIDER_NOW);self.clock.start();self.addCleanup(self.clock.stop)
        self.fake=FakeProvider()
        access=ProviderAccess({'THE_ODDS_API':'SYNTHETIC_ONLY'},getter=self.fake,clock=lambda:PROVIDER_NOW)
        self.bridge=ProviderBridge(access,self.root,clock=lambda:PROVIDER_NOW)

    def fill(self):
        # Reproduce the actual 256-file *legacy root* capacity of the device.
        pins=[]
        for i in range(256):
            payload={'synthetic_record':i}
            pin=digest(payload)
            publish_json(self.root/('provider-'+pin+'.json'),dict(payload=payload,sha256=pin))
            pins.append(pin)
        return pins

    def test_identical_receipt_can_be_reused_at_full_capacity(self):
        pins=self.fill();before={p:p.read_bytes() for p in self.root.glob('*.json')}
        self.assertEqual(self.bridge._save({'synthetic_record':0}),pins[0])
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.glob('*.json')})

    def test_full_legacy_store_does_not_block_new_sharded_provider_evidence(self):
        self.fill()
        before={p:p.read_bytes() for p in self.root.glob('*.json')}
        status=self.bridge.storage_status()
        self.assertEqual(status['legacy_files'],256)
        self.assertTrue(status['legacy_at_capacity'])
        self.assertEqual(status['status'],'AVAILABLE')
        report=self.bridge.collect(deepcopy(SNAPSHOT))
        self.assertNotEqual(report['status'],'LOCAL_EVIDENCE_STORAGE_FULL')
        self.assertEqual(report['providers']['THE_ODDS_API']['status'],
                         'OBSERVED_RULES_AND_CALIBRATION_PENDING')
        self.assertTrue(self.fake.calls)
        self.assertTrue(report['source_pin'])
        self.assertEqual(self.bridge.read_receipt(report['source_pin'])['fixture_id'],SNAPSHOT['fixture_id'])
        self.assertTrue(list(self.root.glob('segments/??/provider-*.json')))
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.glob('*.json')})
        status=self.bridge.storage_status()
        self.assertGreater(status['files'],256)
        self.assertGreater(status['segmented_files'],0)

    def test_existing_receipt_tampering_is_refused_instead_of_silently_reused(self):
        pin=self.bridge._save({'synthetic_record':0});path=self.root/('provider-'+pin+'.json')
        path.write_text('{}')
        with self.assertRaisesRegex(ValueError,'PROVIDER_RECEIPT_PIN_CONFLICT'):
            self.bridge._save({'synthetic_record':0})

    def test_runtime_status_distinguishes_local_limit_without_exposing_key(self):
        access=self.bridge.access;access.max_calls=1
        self.assertEqual(access.get('THE_ODDS_API','/v4/sports/')['status'],'DOCUMENT_RECEIVED')
        self.assertEqual(access.get('THE_ODDS_API','/v4/sports/basketball_nba/events')['status'],'LOCAL_DAILY_REQUEST_BUDGET')
        status=access.runtime_status()
        self.assertEqual(status['THE_ODDS_API']['local_calls_today'],1)
        self.assertEqual(status['THE_ODDS_API']['local_daily_limit'],1)
        self.assertNotIn('SYNTHETIC_ONLY',json.dumps(status))


class ArchivedModelAgeTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.now=NOW-3*86400+3600
        self.timer=patch('time.time',side_effect=lambda:self.now);self.timer.start();self.addCleanup(self.timer.stop)
        self.source=Source('EUROCUP',lambda:self.now)
        self.source.raw['data']=[r for r in self.source.raw['data'] if not r['played'] or
            datetime.fromisoformat(r['utcDate']).timestamp()<self.now-1]
        self.source.raw['total']=len(self.source.raw['data'])
        prepare(self.root/'models','EUROCUP',2026,self.source('EUROLEAGUE_LIVE',season_url('EUROCUP',2026)))
        self.now=NOW
        self.service=EuropeanService('EUROCUP',self.root/'forecasts',self.root/'models',self.source)
        report=await self.service.analyze('EUROCUP','2026-11-11','Paris Basketball','Fenerbahce Beko')
        self.assertEqual(report['status'],'EUROPE_HYBRID_OK',report)
        self.ctx=context(projection(report,'EUROCUP',service=self.service),'EUROCUP')
        self.p=self.service.registry.records()[0]['payload']
        self.reviewer=EuropeanDataReview({'EUROCUP':self.service},None,self.root/'current',clock=lambda:self.now)

    async def test_archive_replay_survives_model_age_boundary_before_tipoff(self):
        self.now=NOW+2*3600
        self.assertLess(self.now,self.ctx['fixture_start_utc'])
        with self.assertRaisesRegex(ValueError,'SCOPE_SOURCE_OR_AGE'):
            PreparedEurope(self.root/'models','EUROCUP',2026)
        before={p:p.read_bytes() for p in self.root.rglob('*.json')}
        with patch('hybrid_engine.models.HierarchicalStrength.fit',side_effect=AssertionError('NO_REFIT')):
            distribution=self.reviewer.distribution(self.service,self.p,self.ctx)
        self.assertEqual(prediction_intervals(distribution.forecast)['sample_sha256'],self.ctx['intervals']['sample_sha256'])
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob('*.json')})

    async def test_archived_replay_never_accepts_model_prepared_after_original_forecast(self):
        from hybrid_engine.europe_archive_model import restore
        prepared=next(a for a in self.p['assets'] if a['file'].startswith('prepared-'))
        training=next(a for a in self.p['assets'] if a['file'].startswith('training-'))
        w=self.service.registry.read_asset(prepared);t=self.service.registry.read_asset(training)
        w['payload']['prepared_at_utc']=self.ctx['prediction_generated_at_utc']+1;w['sha256']=digest(w['payload'])
        c=dict(self.ctx,model_digest=w['sha256'])
        with self.assertRaisesRegex(ValueError,'ARCHIVED_EUROPE_MODEL_SCOPE_OR_CLOCK'):
            restore(w,t,c)

    async def test_targeted_source_context_read_does_not_rescan_entire_forecast_archive(self):
        with patch.object(self.service.registry,'records',side_effect=AssertionError('NO_FULL_ARCHIVE_RESCAN')):
            owner,p=self.reviewer.resolve(self.ctx)
        self.assertIs(owner,self.service);self.assertEqual(digest(p),self.ctx['original_forecast_sha256'])

    async def test_european_doctor_verifies_sources_and_preserves_original_bytes(self):
        before={p:p.read_bytes() for p in (self.root/'forecasts').glob('*.json')}
        with patch('requests.get',side_effect=AssertionError('NO_HTTP')),patch('hybrid_engine.models.HierarchicalStrength.predict',side_effect=AssertionError('NO_PREDICTION')):
            result=audit_europe(self.root/'forecasts','EUROCUP')
        self.assertEqual(result['status'],'VERIFIED_CURRENT_REGISTRY')
        self.assertEqual(result['unique_fixtures'],1);self.assertEqual(result['pending'],1)
        self.assertTrue(result['archive_bytes_unchanged'])
        self.assertEqual(before,{p:p.read_bytes() for p in (self.root/'forecasts').glob('*.json')})

    async def test_full_european_source_store_reports_local_capacity_explicitly(self):
        for i in range(64):self.reviewer.save_source(dict(synthetic=i))
        body='<html>No structured injury report here.</html>'
        self.reviewer.getter=lambda url,league,deadline:dict(status='RECEIVED',url=url,body=body,
            body_sha256=hashlib.sha256(body.encode()).hexdigest(),observed_at_utc=self.now,ingested_at_utc=self.now)
        before={p:p.read_bytes() for p in (self.root/'forecasts').glob('*.json')}
        report=self.reviewer.review(self.ctx,'roster')
        self.assertEqual(report['status'],'LOCAL_EUROPE_SOURCE_STORAGE_FULL')
        self.assertIn('deposu dolu',report['html'])
        self.assertEqual(before,{p:p.read_bytes() for p in (self.root/'forecasts').glob('*.json')})

    async def test_full_review_store_preserves_source_failure_text_without_faking_persistence(self):
        folder=self.root/'current/reviews';folder.mkdir(parents=True)
        for i in range(256):
            p=dict(synthetic=i);publish_json(folder/('review-'+digest(p)+'.json'),dict(payload=p,sha256=digest(p)))
        before={p:p.read_bytes() for p in folder.glob('*.json')}
        self.reviewer.getter=lambda url,league,deadline:dict(status='SOURCE_HTTP_ERROR',url=url,http_status=429,retry_after_seconds=300)
        report=self.reviewer.review(self.ctx,'roster')
        self.assertEqual(report['status'],'CURRENT_OBSERVATIONS_NOT_PERSISTED')
        self.assertIn('429',report['html']);self.assertIn('yeni bir arşiv kaydı değildir',report['html'])
        self.assertEqual(report['details']['verified_player_records'],[])
        self.assertEqual(report['details']['capability'],'OFFICIAL_NEWS_ONLY_NOT_PLAYER_AVAILABILITY_FEED')
        self.assertEqual(before,{p:p.read_bytes() for p in folder.glob('*.json')})


class ReadOnlyDoctorTests(TestCase):
    def test_absent_device_archive_is_unknown_and_never_created(self):
        with TemporaryDirectory() as temp:
            path=Path(temp)/'absent'
            with patch('requests.get',side_effect=AssertionError('NO_PROVIDER_REQUEST')):
                report=audit(path)
            self.assertFalse(path.exists());self.assertEqual(report['nba_archive']['status'],'NOT_PRESENT')
            self.assertEqual(report['api_requests_made'],0);self.assertEqual(report['records_overwritten'],0)
            self.assertFalse(report['running_process_verified'])

    def test_inventory_reports_capacity_and_validated_codes_without_native_error_text(self):
        with TemporaryDirectory() as temp:
            root=Path(temp)
            p=dict(format='ISOLATED_PROVIDER_REVIEW_V1',status='CURRENT_OBSERVATIONS_NOT_HISTORICAL_FORECAST_INPUTS',
                evaluated_at_utc=NOW,providers={'API_BASKETBALL':dict(status='PROVIDER_REPORTED_ERROR',
                error_codes=['PLAN_OR_SUBSCRIPTION_RESTRICTION_REPORTED','PRIVATE_SECRET_TEXT'])},
                private_note='DO_NOT_EXPORT_NATIVE_TEXT')
            publish_json(root/('provider-'+digest(p)+'.json'),dict(payload=p,sha256=digest(p)))
            before={p:p.read_bytes() for p in root.glob('*.json')}
            result=inventory(root,'provider-*.json',maximum_files=1,maximum_bytes=1024*1024)
            self.assertEqual(result['status'],'CAPACITY_REACHED')
            self.assertIn('PLAN_OR_SUBSCRIPTION_RESTRICTION_REPORTED',json.dumps(result))
            self.assertNotIn('PRIVATE_SECRET_TEXT',json.dumps(result));self.assertNotIn('DO_NOT_EXPORT_NATIVE_TEXT',json.dumps(result))
            self.assertEqual(before,{p:p.read_bytes() for p in root.glob('*.json')})
