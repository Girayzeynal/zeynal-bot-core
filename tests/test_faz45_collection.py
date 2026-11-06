"""Mock public responses and temporary files; no real network/storage claims."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock,patch

from prediction_inputs import digest
from faz41_adapters import capture
from faz41_evidence import REGISTRY,REGISTRY_PIN
from faz44_inputs import publish_development_artifact,make_bundle
from faz45_collection import collect_support,seal_support_bundle,validate_support_bundle,read_support_bundle,FORMAT,main
from tests.test_faz45_support import dataset,record
from tests.test_faz42_history import NOW
from tests.test_faz42_prospective import test_model as synthetic_model
from tests.test_euroleague_live import source


class SupportCollectionTests(TestCase):
    def setUp(self):
        self.timer=patch('time.time',return_value=NOW);self.timer.start();self.addCleanup(self.timer.stop)
        self.raw,self.scores,_=dataset(REGISTRY,usage='RETROSPECTIVE_RESEARCH');self.identities=['ESPN:'+r['header']['id'] for r in self.raw]

    def response(self,url,**kw):
        raw=next(deepcopy(r) for r in self.raw if url.endswith(r['header']['id']))
        raw['article']={'text':'EXCLUDED_PROVIDER_PROSE'};raw['news']=[{'headline':'EXCLUDED_HEADLINE'}]
        return dict(status='DOCUMENT_RECEIVED',source_url=url,provider=kw['provider'],observed_at_utc=NOW-10,http_status=200,payload=raw)

    def collect(self,**kw):
        options=dict(live=True,collector=self.response);options.update(kw)
        with patch('time.time',return_value=NOW-5):return collect_support(self.scores,self.identities[:1],**options)

    def sealed(self,collection=None):return seal_support_bundle(self.collect() if collection is None else collection,'a'*64,self.scores)

    def validate(self,s,**kw):
        opts=dict(trusted_sha256=s['sha256'],score_input_sha256='a'*64,scores=self.scores);opts.update(kw)
        return validate_support_bundle(s,**opts)

    def rehash(self,s):s['sha256']=digest(s['payload']);return s

    def test_default_is_network_free_and_unknown_ids_or_unbounded_request_are_refused(self):
        fn=Mock();r=collect_support(self.scores,self.identities[:1],collector=fn);fn.assert_not_called();self.assertEqual(r['network_requests'],0)
        for ids in [[],self.identities*3,['ESPN:unknown'],[self.identities[0]]*2]:
            with self.subTest(ids=ids),self.assertRaises(ValueError):collect_support(self.scores,ids,collector=fn)
        fn.assert_not_called()

    def test_public_collection_keeps_replayable_player_pbp_and_excludes_prose(self):
        r=self.collect();self.assertEqual(r['network_requests'],1);self.assertEqual(r['rejected'],[]);self.assertEqual(len(r['observations']),2)
        serialized=json.dumps(r['observations']);self.assertNotIn('EXCLUDED_PROVIDER_PROSE',serialized);self.assertNotIn('EXCLUDED_HEADLINE',serialized)
        self.assertTrue(all(o['payload']['usage_status']=='UNKNOWN' for o in r['observations']))
        self.assertTrue(all(o['payload']['ingested_at_utc']==NOW-5 for o in r['observations']))
        self.assertEqual(len(self.validate(self.sealed(r))['observations']),2)

    def test_403_429_network_and_invalid_json_are_preserved_without_retry(self):
        for status in ('HTTP_403','HTTP_429','TRANSPORT_FAILED','INVALID_DOCUMENT'):
            fn=Mock(return_value=dict(status=status,source_url=self.scores[0]['payload']['source_url'],provider='ESPN'))
            r=self.collect(collector=fn);fn.assert_called_once();self.assertEqual(r['observations'],[]);self.assertEqual(r['receipts'][0]['status'],status)

    def test_conflicting_final_cannot_be_published_as_player_or_pbp_evidence(self):
        def wrong(url,**kw):
            r=self.response(url,**kw);t=r['payload']['header']['competitions'][0]['competitors'][0]
            t['score']=str(int(t['score'])+1);t['linescores'][0]['displayValue']=str(int(t['linescores'][0]['displayValue'])+1);t['linescores'][0]['value']=int(t['linescores'][0]['displayValue'])
            return r
        r=self.collect(collector=wrong);self.assertEqual(r['observations'],[]);self.assertEqual({x['reason'] for x in r['rejected']},{'COLLECTED_SUPPORT_SCORE_CONFLICT'})

    def test_missing_minutes_does_not_turn_valid_pbp_into_player_or_roster(self):
        def missing(url,**kw):
            r=self.response(url,**kw);r['payload']['boxscore'].pop('players');return r
        r=self.collect(collector=missing);self.assertEqual(len(r['observations']),1);self.assertEqual(r['rejected'][0]['kind'],'PLAYER_MINUTES')
        self.assertEqual(r['observations'][0]['payload']['claims']['rotation_status'],'ABSTAIN_SUBSTITUTION_ROLES_UNVERIFIED')

    def test_bad_pbp_does_not_discard_reconciled_minutes_or_repair_events(self):
        def bad(url,**kw):
            r=self.response(url,**kw);r['payload']['plays'][3]['homeScore']=999;return r
        r=self.collect(collector=bad);self.assertEqual(len(r['observations']),1);self.assertEqual(r['observations'][0]['payload']['data_type'],'PLAYER_MINUTES')
        self.assertEqual(r['rejected'][0]['kind'],'PBP_TIMELINE');self.assertIn('SCORE_CORRECTION',r['rejected'][0]['reason'])

    def test_wrong_receipt_origin_is_fail_closed_before_publication(self):
        def bad(url,**kw):r=self.response(url,**kw);r['source_url']='https://evil.example/summary';return r
        with self.assertRaisesRegex(ValueError,'RECEIPT_SOURCE_MISMATCH'):self.collect(collector=bad)

    def test_external_pin_score_binding_future_clock_and_missing_reference_are_refused(self):
        s=self.sealed()
        with self.assertRaisesRegex(ValueError,'TRUSTED_SUPPORT_PIN'):self.validate(s,trusted_sha256='f'*64)
        with self.assertRaisesRegex(ValueError,'SCORE_POLICY_BINDING'):self.validate(s,score_input_sha256='b'*64)
        b=deepcopy(s);b['payload']['created_at_utc']=NOW+1;self.rehash(b)
        with self.assertRaisesRegex(ValueError,'CLOCK'):self.validate(b)
        b=deepcopy(s);k=next(iter(b['payload']['observations']));b['payload']['observations']['f'*64]=b['payload']['observations'].pop(k);self.rehash(b)
        with self.assertRaisesRegex(ValueError,'REFERENCE'):self.validate(b)

    def test_missing_completed_receipt_or_changed_response_hash_is_refused(self):
        for change in ('missing','status','hash'):
            s=self.sealed()
            if change=='missing':s['payload']['receipts']=[]
            elif change=='status':s['payload']['receipts'][0]['status']='TRANSPORT_FAILED'
            else:s['payload']['receipts'][0]['response_sha256']='b'*64
            self.rehash(s)
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'COMPLETED_RECEIPT'):self.validate(s)

    def test_local_publication_is_atomic_idempotent_and_immutable_under_two_writers(self):
        s=self.sealed()
        with TemporaryDirectory() as folder:
            p=Path(folder)/'faz45-support-test.json'
            def publish(_):return publish_development_artifact(p,s,expected_format=FORMAT,filename_prefix='faz45-support-')
            with ThreadPoolExecutor(max_workers=2) as pool:r=list(pool.map(publish,range(2)))
            self.assertEqual(sorted(r),[False,True]);before=p.read_bytes();self.assertEqual(p.stat().st_mode&0o777,0o600)
            read_support_bundle(p,trusted_sha256=s['sha256'],score_input_sha256='a'*64,scores=self.scores);self.assertEqual(p.read_bytes(),before)
            b=deepcopy(s);b['payload']['created_at_utc']=NOW-1;self.rehash(b)
            with self.assertRaisesRegex(ValueError,'IMMUTABLE'):publish_development_artifact(p,b,expected_format=FORMAT,filename_prefix='faz45-support-')
            with self.assertRaisesRegex(ValueError,'FORMAT_REQUIRED'):publish_development_artifact(p,s,expected_format=FORMAT,filename_prefix='ordinary-')
            self.assertEqual(p.read_bytes(),before)

    def test_both_euro_competitions_use_stats_seconds_with_exact_score_binding(self):
        for league in ('EUROLEAGUE','EUROCUP'):
            raw=source(league)
            for side in ('local','road'):
                rows=raw['stats'][side]['players'];n=len(rows)
                for i,p in enumerate(rows):p['stats']['timePlayed']=float(12000//n+(i<12000%n))
            with patch('time.time',return_value=NOW-100):score=capture(raw['game'],provider='EUROLEAGUE_LIVE',league=league,season_end_year=2027,
                observed_at_utc=NOW-110,ingested_at_utc=NOW-105)
            identity='EUROLEAGUE_LIVE:'+score['payload']['provider_fixture_id']
            fn=lambda url,**kw:dict(status='DOCUMENT_RECEIVED',source_url=url,provider=kw['provider'],observed_at_utc=NOW-10,payload=raw['stats'])
            with patch('time.time',return_value=NOW-5):r=collect_support([score],[identity],live=True,collector=fn)
            self.assertEqual(r['rejected'],[]);self.assertEqual(len(r['observations']),1)
            s=seal_support_bundle(r,'c'*64,[score]);self.assertEqual(len(s['payload']['observations']),1)

    def test_audit_cli_loads_frozen_inputs_and_emits_unknown_permission_abstain(self):
        model=synthetic_model();model['payload']['purpose']='EXPERIMENTAL_DRY_RUN';model['sha256']=digest(model['payload'])
        bundle=make_bundle(self.scores,[],model,days=['2026-11-06']);support=seal_support_bundle(self.collect(),bundle['sha256'],self.scores)
        with TemporaryDirectory() as folder:
            a=Path(folder)/'inputs.json';a.write_text(json.dumps(bundle));b=Path(folder)/'support.json';b.write_text(json.dumps(support));before=(a.read_bytes(),b.read_bytes())
            target=self.scores[-1]['payload']['fixture'];stream=StringIO()
            args=['faz45_collection','--audit','--score-inputs',str(a),'--trusted-score-sha256',bundle['sha256'],'--support-inputs',str(b),'--trusted-support-sha256',support['sha256'],'--target-canonical-id',target['canonical_id'],'--cutoff-utc',str(target['start_utc']-1)]
            with patch('sys.argv',args),redirect_stdout(stream):self.assertEqual(main(),0)
            r=json.loads(stream.getvalue());self.assertEqual(r['prospective_records_created'],0);self.assertEqual(r['usable_distinct_games']['PLAYER_MINUTES'],0)
            self.assertEqual((a.read_bytes(),b.read_bytes()),before)
            args[-1]='0';stream=StringIO()
            with patch('sys.argv',args),redirect_stdout(stream):self.assertEqual(main(),1)
            self.assertEqual(json.loads(stream.getvalue())['reason'],'SUPPORT_PREMATCH_CUTOFF_REQUIRED')
