"""Mock-only network and local artifacts; no real Cloud/lineup claims."""
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock,patch

from prediction_inputs import digest
from faz44_inputs import publish_development_artifact
from faz42_schedule import seal_schedule
from faz46_collection import collect,seal_audit,validate_audit,read_audit,FORMAT,main
from faz46_rosters import endpoint,audit_endpoint
from tests.test_faz42_history import NOW,permitted_registry
from tests.test_faz46_rosters import euro
from tests.test_faz33 import event


class PrematchCollectionTests(TestCase):
    def setUp(self):
        self.timer=patch('time.time',return_value=NOW);self.clock=self.timer.start();self.addCleanup(self.timer.stop)
        self.registry=permitted_registry();self.pin=digest(self.registry);self.raw,self.fixture,self.pid=euro()
        self.url=endpoint('EUROLEAGUE_LIVE','EUROLEAGUE',self.pid,2027)
        with patch('time.time',return_value=NOW-20):self.schedule=seal_schedule({'data':[self.raw['game']],'total':1},provider='EUROLEAGUE_LIVE',league='EUROLEAGUE',season_end_year=2027,
            source_url=self.url.rsplit('/',2)[0]+'?limit=1000',observed_at_utc=NOW-30,ingested_at_utc=NOW-25,usage='SYNTHETIC_TEST',registry=self.registry,registry_pin=self.pin)

    def response(self,*,status='DOCUMENT_RECEIVED'):
        out=dict(source_url=self.url,provider='EUROLEAGUE_LIVE',status=status,http_status=200 if status=='DOCUMENT_RECEIVED' else 403,observed_at_utc=NOW-10)
        if status=='DOCUMENT_RECEIVED':out['payload']=deepcopy(self.raw['stats'])
        return out

    def audit(self,response=None):
        with patch('time.time',return_value=NOW-1):return audit_endpoint(self.schedule,self.fixture['canonical_id'],response or self.response(),registry=self.registry,registry_pin=self.pin)

    def bundle(self):
        audit=self.audit();receipt=deepcopy(audit['receipt']);report=dict(audits=[audit],sources=[receipt],observations=2,confirmed_lineups=0,prospective_records_created=0,network_requests=1)
        return seal_audit(report,registry=self.registry,registry_pin=self.pin)

    def validate(self,s,**kw):
        options=dict(trusted_sha256=s['sha256'],registry=self.registry,registry_pin=self.pin);options.update(kw)
        return validate_audit(s,**options)

    def rehash(self,s):s['sha256']=digest(s['payload']);return s

    def test_default_collection_has_no_network_or_prospective_prediction(self):
        fn=Mock();r=collect(collector=fn);fn.assert_not_called();self.assertEqual(r['network_requests'],0);self.assertEqual(r['prospective_records_created'],0)

    def test_source_bound_audit_replays_original_game_plus_stats(self):
        a=self.audit();self.assertEqual(a['status'],'UNCONFIRMED_SOURCE_LISTING_AVAILABLE');self.assertEqual(len(a['observations']),2)
        b=self.bundle();self.assertEqual(len(self.validate(b)['report']['audits']),1);self.assertEqual(a['confirmed_lineups'],0)

    def test_source_errors_are_separate_from_empty_roster_and_not_retried(self):
        for status in ('HTTP_403','HTTP_429','TRANSPORT_FAILED','INVALID_DOCUMENT'):
            a=self.audit(self.response(status=status));self.assertEqual(a['status'],'ABSTAIN_SOURCE_'+status);self.assertEqual(a['observations'],[])
        v=self.response()
        for side in ('local','road'):v['payload'][side]['players']=[];v['payload'][side]['team']=None
        a=self.audit(v);self.assertEqual(a['status'],'ABSTAIN_ROSTER_NOT_PUBLISHED')

    def test_stale_schedule_wrong_origin_and_missing_completed_response_fail_closed(self):
        self.clock.return_value=NOW+301
        with self.assertRaisesRegex(ValueError,'STALE_SCHEDULE'):audit_endpoint(self.schedule,self.fixture['canonical_id'],self.response(),registry=self.registry,registry_pin=self.pin)
        self.clock.return_value=NOW;v=self.response();v['source_url']='https://evil.example/stats'
        with self.assertRaisesRegex(ValueError,'ORIGIN_MISMATCH'):self.audit(v)
        v=self.response();v['http_status']=None
        self.assertEqual(self.audit(v)['status'],'PREMATCH_COMPLETED_RECEIPT_REQUIRED')

    def test_future_receipt_or_stats_older_than_schedule_are_not_available(self):
        for at in (NOW+1,NOW-31):
            v=self.response();v['observed_at_utc']=at
            self.assertEqual(self.audit(v)['status'],'PREMATCH_SOURCE_CHRONOLOGY')

    def test_root_pin_counts_false_lineup_claim_and_missing_receipt_are_refused(self):
        s=self.bundle()
        with self.assertRaisesRegex(ValueError,'PIN_MISMATCH'):self.validate(s,trusted_sha256='0'*64)
        for field,value in [('observations',3),('confirmed_lineups',1)]:
            b=deepcopy(s);b['payload']['report'][field]=value;self.rehash(b)
            with self.subTest(field=field),self.assertRaises(ValueError):self.validate(b)
        b=deepcopy(s);b['payload']['report']['audits'][0]['receipt']['status']='TRANSPORT_FAILED';b['payload']['report']['sources'][0]['status']='TRANSPORT_FAILED';self.rehash(b)
        with self.assertRaisesRegex(ValueError,'RECEIPT_BINDING'):self.validate(b)

    def test_rehashed_five_and_false_compact_source_digest_are_refused(self):
        s=self.bundle();a=s['payload']['report']['audits'][0];o=a['observations'][0];o['payload']['claims']['starting_five']=o['payload']['claims']['players'][:5];o['sha256']=digest(o['payload']);self.rehash(s)
        with self.assertRaisesRegex(ValueError,'CANNOT_REPLAY'):self.validate(s)
        s=self.bundle();s['payload']['report']['audits'][0]['compact_json_sha256']='a'*64;self.rehash(s)
        with self.assertRaisesRegex(ValueError,'RAW_PROOF_REQUIRED'):self.validate(s)

    def test_atomic_readonly_local_publication_and_duplicate_are_safe(self):
        s=self.bundle()
        with TemporaryDirectory() as folder:
            p=Path(folder)/'faz46-prematch-test.json'
            self.assertTrue(publish_development_artifact(p,s,expected_format=FORMAT,filename_prefix='faz46-prematch-'));before=p.read_bytes()
            self.assertFalse(publish_development_artifact(p,s,expected_format=FORMAT,filename_prefix='faz46-prematch-'))
            read_audit(p,trusted_sha256=s['sha256'],registry=self.registry,registry_pin=self.pin);self.assertEqual(p.read_bytes(),before)
            self.assertEqual(p.stat().st_mode&0o777,0o600)

    def test_collector_is_bounded_and_does_not_infer_lineups_from_nba_schedule(self):
        fn=Mock(return_value=dict(status='HTTP_403',source_url='unused',provider='NBA'))
        r=collect(live=True,collector=fn);self.assertEqual(fn.call_count,6);self.assertEqual(r['network_requests'],6)
        self.assertEqual(r['observations'],0);self.assertEqual(r['confirmed_lineups'],0);self.assertEqual(r['nba_official_access'],'HTTP_403')

    def test_cli_without_live_does_not_fetch_sources_or_write_a_prediction(self):
        output=StringIO()
        with patch('sys.argv',['faz46_collection']),redirect_stdout(output),patch('faz46_collection.fetch') as fn:
            self.assertEqual(main(),0);fn.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())['status'],'ABSTAIN_LIVE_PREMATCH_NOT_REQUESTED')

    def test_missing_top_level_receipt_cannot_claim_zero_network_for_captured_listings(self):
        s=self.bundle();s['payload']['report']['sources']=[];s['payload']['report']['network_requests']=0;self.rehash(s)
        with self.assertRaisesRegex(ValueError,'RECEIPT_NOT_IN_MANIFEST'):self.validate(s)

    def test_cross_document_rescheduled_provider_id_refuses_entire_discovery(self):
        calls=[]
        def response(url,**kw):
            calls.append(url)
            if kw['provider']=='ESPN':
                raw=event(NOW+3600+len(calls)*60,'900000099')
                return dict(status='DOCUMENT_RECEIVED',source_url=url,provider='ESPN',observed_at_utc=NOW-1,payload={'events':[raw]})
            return dict(status='HTTP_403',source_url=url,provider=kw['provider'])
        r=collect(live=True,collector=response);self.assertEqual(r['status'],'ABSTAIN_DISCOVERY_IDENTITY_CONFLICT')
        self.assertEqual(r['audits'],[]);self.assertEqual(len(calls),6)

    def empty_bundle(self):
        response=self.response()
        for side in ('local','road'):response['payload'][side]['players']=[];response['payload'][side]['team']=None
        a=self.audit(response);report=dict(audits=[a],sources=[deepcopy(a['receipt'])],observations=0,confirmed_lineups=0,prospective_records_created=0,network_requests=1)
        return seal_audit(report,registry=self.registry,registry_pin=self.pin)

    def test_missing_roster_status_needs_replayable_raw_source_even_with_no_observations(self):
        s=self.empty_bundle();self.assertEqual(self.validate(s)['report']['observations'],0)
        del s['payload']['report']['audits'][0]['raw_proof'];self.rehash(s)
        with self.assertRaisesRegex(ValueError,'RAW_PROOF_REQUIRED'):self.validate(s)

    def test_rehashed_empty_roster_claim_cannot_hide_nonempty_source_listing(self):
        s=self.bundle();a=s['payload']['report']['audits'][0];a['observations']=[];a['status']='ABSTAIN_ROSTER_NOT_PUBLISHED';s['payload']['report']['observations']=0;self.rehash(s)
        with self.assertRaisesRegex(ValueError,'AUDIT_CANNOT_REPLAY'):self.validate(s)

    def test_empty_source_audit_cannot_be_backdated_across_tipoff_or_root_clock(self):
        for at in (self.fixture['start_utc'],NOW+1):
            s=self.empty_bundle();s['payload']['report']['audits'][0]['audited_at_utc']=at;self.rehash(s)
            with self.subTest(at=at),self.assertRaisesRegex(ValueError,'RECEIPT_BINDING'):self.validate(s)
