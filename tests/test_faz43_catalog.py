from copy import deepcopy
from unittest import TestCase
from unittest.mock import Mock,patch

import faz43_catalog as c
from prediction_inputs import digest
from tests.test_euroleague_live import source
from tests.test_faz42_history import NOW,permitted_registry


class CatalogExpansionTests(TestCase):
    def setUp(self):
        self.timer=patch('time.time',return_value=NOW+1);self.timer.start();self.addCleanup(self.timer.stop)
        self.registry=permitted_registry();self.pin=digest(self.registry)

    def seal(self,league='EUROLEAGUE',**updates):
        f=source(league);raw=dict(competition=f['competition'],season=f['season'],games=dict(data=[f['game']],total=1));raw.update(updates)
        code='E' if league=='EUROLEAGUE' else 'U';base=f'https://api-live.euroleague.net/v2/competitions/{code}'
        urls=[base,base+f'/seasons/{code}2026',base+f'/seasons/{code}2026/games']
        receipts=[dict(source_url=u,observed_at_utc=NOW-20,ingested_at_utc=NOW-10,response_sha256=digest(raw[k])) for k,u in zip(('competition','season','games'),urls)]
        with patch('time.time',return_value=NOW):return c.seal_catalog(raw,league=league,year=2026,source_receipts=receipts,registry=self.registry,registry_pin=self.pin)

    def replay(self,s,**updates):
        args=dict(asof_utc=NOW+1,registry=self.registry,registry_pin=self.pin);args.update(updates);return c.replay_catalog(s,**args)

    def test_real_trimmed_catalog_fields_are_replayed_without_claiming_player_data(self):
        for league in ('EUROLEAGUE','EUROCUP'):
            facts=self.replay(self.seal(league));self.assertEqual(facts['completed_period_games'],1)
            self.assertEqual(facts['player_stats_games'],0);self.assertEqual(facts['per_game_endpoint_requests'],0)
            game=facts['completed'][0];self.assertEqual(game['regulation_home'],sum(game['quarters']['home']))

    def test_same_fixture_duplicate_does_not_increase_completed_count(self):
        f=source()['game'];s=self.seal(games=dict(data=[f,deepcopy(f)],total=2));r=self.replay(s)
        self.assertEqual(r['completed_period_games'],1);self.assertEqual(r['duplicate_identical'],1)

    def test_unknown_usage_is_not_model_permission(self):
        self.registry['EUROLEAGUE_LIVE']['usage']='UNKNOWN';self.pin=digest(self.registry);s=self.seal()
        with self.assertRaisesRegex(ValueError,'USAGE_NOT_ESTABLISHED'):self.replay(s)
        self.assertEqual(self.replay(s,require_permitted=False)['completed_period_games'],1)

    def test_materialization_and_original_receipts_cannot_be_backdated_into_cutoff(self):
        with self.assertRaisesRegex(ValueError,'UNAVAILABLE'):self.replay(self.seal(),asof_utc=NOW)
        s=self.seal();s['payload']['source_receipts'][0]['source_url']='https://evil.test/';s['sha256']=digest(s['payload'])
        with self.assertRaisesRegex(ValueError,'RECEIPT'):self.replay(s)

    def test_rehashed_catalog_counts_and_origin_digests_are_refused(self):
        for field,value in [('facts',{}),('raw_sha256','0'*64)]:
            s=self.seal();s['payload'][field]=value;s['sha256']=digest(s['payload'])
            with self.subTest(field=field),self.assertRaises(ValueError):self.replay(s)

    def test_cross_league_and_incomplete_catalog_are_refused(self):
        with self.assertRaises(ValueError):self.seal(games=dict(data=[source('EUROCUP')['game']],total=1),season=source('EUROCUP')['season'])
        with self.assertRaises(ValueError):self.seal(games=dict(data=[],total=1))

    def test_default_collection_has_no_network_and_http_failure_remains_abstain(self):
        collector=Mock();self.assertEqual(c.collect(collector=collector)['network_requests'],0);collector.assert_not_called()
        collector.side_effect=lambda url,provider:dict(status='HTTP_403',source_url=url,http_status=403)
        r=c.collect(live=True,collector=collector)
        self.assertTrue(all(row['status']=='ABSTAIN_PROVIDER_UNAVAILABLE' for row in r['reports']))
        self.assertEqual(r['prospective_records_created'],0)

    def test_rehashed_materialization_cannot_precede_original_receipt_ingestion(self):
        s=self.seal();s['payload']['source_receipts'][0]['ingested_at_utc']=NOW+1;s['sha256']=digest(s['payload'])
        with patch('time.time',return_value=NOW+3),self.assertRaisesRegex(ValueError,'RECEIPT_AFTER_MATERIALIZATION'):
            self.replay(s,asof_utc=NOW+2)
