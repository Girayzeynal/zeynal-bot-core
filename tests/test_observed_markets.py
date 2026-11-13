"""Synthetic bookmaker contracts; real quotes are acquired only in explicit research."""
from copy import deepcopy
from datetime import datetime,timezone
from unittest import TestCase

import numpy as np

from core.team_identity import digest
from hybrid_engine.data import Abstain
from hybrid_engine.distributions import gaussian_forecast
from hybrid_engine.observed_markets import observe_espn,evaluate_observation,decimal_price
from tests.test_season_archive_audit import nba,NOW


def receipt(total=210.5):
    e=nba();e['date']=datetime.fromtimestamp(NOW+3600,timezone.utc).isoformat()
    for status in (e['status']['type'],e['competitions'][0]['status']['type']):
        status.update(state='pre',completed=False,name='STATUS_SCHEDULED')
    q=dict(provider=dict(id='synthetic-book',name='SYNTHETIC TEST ONLY'),overUnder=total,
        total=dict(over=dict(close=dict(line='o'+str(total),odds='-110')),under=dict(close=dict(line='u'+str(total),odds='-110'))),
        pointSpread=dict(home=dict(close=dict(line='-3.5',odds='-105')),away=dict(close=dict(line='+3.5',odds='-115'))))
    e['competitions'][0]['odds']=[q];doc=dict(events=[e])
    return dict(provider='ESPN',status='DOCUMENT_RECEIVED',http_status=200,
        source_url='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20261111',
        observed_at_utc=NOW-2,ingested_at_utc=NOW-1,document=doc,document_sha256=digest(doc))


class ObservedMarketTests(TestCase):
    def test_absent_bookmaker_quotes_do_not_create_reference_lines(self):
        r=receipt();r['document']['events'][0]['competitions'][0]['odds']=[];r['document_sha256']=digest(r['document'])
        result=observe_espn(r,now_utc=NOW)
        self.assertEqual(result['quotes'],[]);self.assertEqual(result['synthetic_lines_created'],0)

    def setUp(self):
        from unittest.mock import patch
        p=patch('time.time',return_value=NOW);p.start();self.addCleanup(p.stop)

    def test_actual_native_lines_and_prices_are_preserved_without_generated_period_lines(self):
        result=observe_espn(receipt(),now_utc=NOW);self.assertEqual(len(result['quotes']),2)
        p=[q['payload'] for q in result['quotes']]
        self.assertEqual({x['market'] for x in p},{'TOTAL','HOME_HANDICAP'})
        self.assertEqual([x['line'] for x in p],[210.5,-3.5]);self.assertEqual(result['synthetic_lines_created'],0)
        self.assertTrue(all(x['settlement_scope']=='UNKNOWN' and not x['closing_time_verified'] for x in p))

    def test_unknown_overtime_scope_never_becomes_a_bet_or_high_confidence(self):
        q=observe_espn(receipt(200.5),now_utc=NOW)['quotes'][0]
        f=gaussian_forecast([110,100],[10,10],np.ones((4,2)),method='ANALYTIC')
        r=evaluate_observation(q,f,trusted_sha256=q['sha256'],model_digest='synthetic',prediction_utc=NOW)
        self.assertEqual(r['conditional_direction'],'OVER');self.assertEqual(r['status'],'ABSTAIN')
        self.assertIsNone(r['recommended_direction']);self.assertIsNone(r['verified_confidence_index'])
        self.assertEqual(r['risk_level'],'NOT_ESTIMABLE')
        self.assertIn('MARKET_SCOPE_UNVERIFIED_WITH_REGULATION_MODEL',r['reasons'])
        self.assertFalse(r['conditional_probability_is_settlement_probability'])

    def test_under_direction_comes_from_model_mass_not_a_fixed_choice(self):
        q=observe_espn(receipt(250.5),now_utc=NOW)['quotes'][0]
        f=gaussian_forecast([110,100],[10,10],np.ones((4,2)),method='ANALYTIC')
        r=evaluate_observation(q,f,trusted_sha256=q['sha256'],model_digest='synthetic',prediction_utc=NOW)
        self.assertEqual(r['conditional_direction'],'UNDER')

    def test_side_line_disagreement_is_refused_instead_of_averaged(self):
        r=receipt();r['document']['events'][0]['competitions'][0]['odds'][0]['total']['under']['close']['line']='u222.5'
        r['document_sha256']=digest(r['document']);result=observe_espn(r,now_utc=NOW)
        self.assertEqual(result['quotes'],[]);self.assertEqual(result['rejected'][0]['reason'],'TOTAL_LINE_CONFLICT')

    def test_post_tipoff_quote_and_future_observation_are_not_pregame_evidence(self):
        r=receipt();self.assertEqual(observe_espn(r,now_utc=NOW+4000)['quotes'],[])
        r['observed_at_utc']=NOW+1;r['ingested_at_utc']=NOW+1
        with self.assertRaisesRegex(ValueError,'OBSERVATION_CLOCK'):observe_espn(r,now_utc=NOW)

    def test_stale_or_not_yet_available_quote_is_explicit(self):
        q=observe_espn(receipt(),now_utc=NOW)['quotes'][0]
        f=gaussian_forecast([110,100],[10,10],np.ones((4,2)),method='ANALYTIC')
        r=evaluate_observation(q,f,trusted_sha256=q['sha256'],model_digest='synthetic',prediction_utc=NOW+600)
        self.assertIn('STALE_BOOKMAKER_OBSERVATION',r['reasons'])
        with self.assertRaises(Abstain):evaluate_observation(q,f,trusted_sha256=q['sha256'],model_digest='synthetic',prediction_utc=NOW-10)

    def test_receipt_source_and_quote_hash_cannot_be_substituted(self):
        r=receipt();r['source_url']='https://invalid.test/scoreboard'
        with self.assertRaises(ValueError):observe_espn(r,now_utc=NOW)
        q=observe_espn(receipt(),now_utc=NOW)['quotes'][0];q['payload']['line']=1
        with self.assertRaisesRegex(ValueError,'QUOTE_PIN'):evaluate_observation(q,None,trusted_sha256=q['sha256'],model_digest='synthetic',prediction_utc=NOW)

    def test_american_prices_are_converted_without_inventing_missing_prices(self):
        self.assertEqual(decimal_price('+100'),2);self.assertEqual(decimal_price('EVEN'),2)
        self.assertAlmostEqual(decimal_price('-200'),1.5)
        for bad in ['-90','1.9','',None]:
            with self.assertRaises(ValueError):decimal_price(bad)
