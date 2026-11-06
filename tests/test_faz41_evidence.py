"""Deterministic synthetic evidence tests, not real source verification."""
from copy import deepcopy
from unittest import TestCase
from unittest.mock import patch

import faz41_evidence as e
from prediction_inputs import digest

NOW=1793960000
FIXTURE=e.fixture_identity(league='NBA',season_end_year=2027,start_utc=NOW+1000,home_team_id='8',away_team_id='20')


class EvidenceV2Tests(TestCase):
    def setUp(self):
        self.clock=patch('time.time',return_value=NOW+1);self.clock.start();self.addCleanup(self.clock.stop)
        self.registry=deepcopy(e.REGISTRY)
        for p in self.registry.values():
            p.update(usage='PERMITTED',permission_ref='https://licence.example/explicit-test-grant',
                     reviewed_at_utc=NOW-100,expires_at_utc=NOW+10000)
        self.pin=digest(self.registry)

    def seal(self,**updates):
        params=dict(fixture=FIXTURE,provider='ESPN',provider_fixture_id='401909922',
            source_url='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=401909922',
            data_type='OFFICIAL_STAT',raw={'source':'synthetic'},claims={'home_score':100},
            observed_at_utc=NOW-10,ingested_at_utc=NOW-5,usage='SYNTHETIC_TEST',
            registry=self.registry,registry_pin=self.pin)
        params.update(updates)
        with patch('time.time',return_value=NOW):return e.seal_observation(**params)

    def validate(self,o=None,**updates):
        args=dict(fixture=FIXTURE,cutoff_utc=NOW+1,maximum_age_seconds=60,registry=self.registry,registry_pin=self.pin)
        args.update(updates)
        return e.validate_observation(self.seal() if o is None else o,**args)

    def test_metadata_preserves_distinct_clocks_and_missing_publication(self):
        p=self.validate();self.assertIsNone(p['published_at_utc'])
        self.assertEqual([p[k] for k in ('observed_at_utc','ingested_at_utc','materialized_at_utc')],[NOW-10,NOW-5,NOW])
        self.assertEqual(p['usage'],'SYNTHETIC_TEST')

    def test_equal_materialization_cutoff_and_future_ingestion_fail_closed(self):
        with self.assertRaisesRegex(ValueError,'NOT_AVAILABLE'):self.validate(cutoff_utc=NOW)
        with self.assertRaisesRegex(ValueError,'CHRONOLOGY'):self.seal(ingested_at_utc=NOW+1)

    def test_future_publication_and_news_without_publication_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'PUBLICATION_CHRONOLOGY'):self.seal(published_at_utc=NOW-1)
        self.registry['NEWS']=dict(self.registry['ESPN'],host='news.example',paths=['/rss/'],types=['NEWS_CLAIM'],level='SECONDARY')
        with self.assertRaisesRegex(ValueError,'PUBLICATION_TIME_REQUIRED'):
            self.seal(provider='NEWS',source_url='https://news.example/rss/item',data_type='NEWS_CLAIM',registry_pin=digest(self.registry))

    def test_freshness_boundary_is_explicit(self):
        self.validate(maximum_age_seconds=11)
        with self.assertRaisesRegex(ValueError,'STALE'):self.validate(maximum_age_seconds=10)

    def test_fixture_season_team_and_league_mismatch_are_rejected(self):
        for key,value in [('season_end_year',2026),('home_team_id','1'),('league','EUROCUP'),('start_utc',NOW+2000)]:
            f=deepcopy(FIXTURE);f[key]=value;f['canonical_id']=digest({k:v for k,v in f.items() if k!='canonical_id'})
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'BINDING'):self.validate(fixture=f)

    def test_digest_raw_and_rehashed_owner_tampering_are_rejected(self):
        o=self.seal();o['payload']['claims']['home_score']=101
        with self.assertRaisesRegex(ValueError,'DIGEST'):self.validate(o)
        for key,value in [('raw',{'altered':1}),('owner','NBA'),('usage_status','UNKNOWN'),('evidence_level','OFFICIAL')]:
            o=self.seal();o['payload'][key]=value;o['sha256']=digest(o['payload'])
            with self.subTest(key=key),self.assertRaises(ValueError):self.validate(o)

    def test_trusted_registry_pin_blocks_permission_relabel(self):
        self.registry['ESPN']['usage']='UNKNOWN'
        with self.assertRaisesRegex(ValueError,'PIN_MISMATCH'):self.seal()

    def test_default_public_api_access_is_not_permission(self):
        o=self.seal(registry=e.REGISTRY,registry_pin=e.REGISTRY_PIN)
        with self.assertRaisesRegex(ValueError,'USAGE_NOT_ESTABLISHED'):
            self.validate(o,registry=e.REGISTRY,registry_pin=e.REGISTRY_PIN)
        self.assertEqual(self.validate(o,registry=e.REGISTRY,registry_pin=e.REGISTRY_PIN,require_permitted=False)['usage_status'],'UNKNOWN')

    def test_expired_and_postcutoff_permissions_are_rejected(self):
        for fields in [dict(expires_at_utc=NOW),dict(reviewed_at_utc=NOW+1)]:
            self.registry['ESPN'].update(reviewed_at_utc=NOW-100,expires_at_utc=NOW+10000)
            self.registry['ESPN'].update(fields);self.pin=digest(self.registry)
            with self.subTest(fields=fields),self.assertRaisesRegex(ValueError,'PERMISSION_NOT_VALID'):self.validate()

    def test_malicious_source_origins_and_url_credentials_are_rejected(self):
        for url in ['http://site.api.espn.com/apis/site/v2/sports/basketball/nba/x',
                    'https://site.api.espn.com.evil.test/apis/site/v2/sports/basketball/nba/x',
                    'https://user:secret@site.api.espn.com/apis/site/v2/sports/basketball/nba/x',
                    'https://site.api.espn.com:444/apis/site/v2/sports/basketball/nba/x',
                    'https://site.api.espn.com/private/x']:
            with self.subTest(url=url),self.assertRaisesRegex(ValueError,'ORIGIN'):self.seal(source_url=url)

    def test_two_provider_aliases_under_same_owner_are_not_independent(self):
        self.registry['ESPN_ALIAS']=deepcopy(self.registry['ESPN']);self.pin=digest(self.registry)
        result=e.compare_observations([self.seal(),self.seal(provider='ESPN_ALIAS')],fixture=FIXTURE,
            cutoff_utc=NOW+1,maximum_age_seconds=60,registry=self.registry,registry_pin=self.pin)
        self.assertEqual(result[0]['status'],'SINGLE_OWNER')

    def test_conflict_is_not_truth_voting_and_duplicate_does_not_raise_sample_count(self):
        a=self.seal();b=self.seal(provider='NBA',source_url='https://cdn.nba.com/static/json/liveData/boxscore/x.json')
        args=dict(fixture=FIXTURE,cutoff_utc=NOW+1,maximum_age_seconds=60,registry=self.registry,registry_pin=self.pin)
        self.assertEqual(e.compare_observations([a,a,b],**args)[0]['status'],'INDEPENDENT_OWNER_AGREEMENT')
        b=self.seal(provider='NBA',source_url='https://cdn.nba.com/static/json/liveData/boxscore/x.json',claims={'home_score':101})
        self.assertEqual(e.compare_observations([a,a,b],**args)[0]['status'],'CONFLICT')

    def test_legacy_v1_and_unknown_schema_cannot_enter_model_contract(self):
        from tests.test_faz41_source_evidence import claim
        with self.assertRaisesRegex(ValueError,'V2_REQUIRED'):self.validate(claim())

    def test_nonfinite_claims_and_mixed_synthetic_real_are_rejected(self):
        with self.assertRaises(ValueError):self.seal(claims={'score':float('nan')})
        with self.assertRaisesRegex(ValueError,'MIXED'):
            e.compare_observations([self.seal(),self.seal(usage='RETROSPECTIVE_RESEARCH')],fixture=FIXTURE,
                cutoff_utc=NOW+1,maximum_age_seconds=60,registry=self.registry,registry_pin=self.pin)
