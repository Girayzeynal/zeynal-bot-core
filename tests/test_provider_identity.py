"""Manufactured native event-clock bindings; no real Odds API result is claimed."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from core.team_identity import digest
from hybrid_engine.provider_access import ProviderAccess
from hybrid_engine.provider_bridge import ProviderBridge,odds_observations,render,matches
from hybrid_engine.provider_identity import bind,verify_detail,clock_text
from hybrid_engine.market_views import assess,render as render_market
from tests.test_provider_bridge import SNAPSHOT,NOW,SECRET,event,priced_event,receipt,iso,FakeProvider
from tests.test_market_observations import setup_native

CATALOG='https://api.the-odds-api.com/v4/sports/basketball_nba/events'
DETAIL='https://api.the-odds-api.com/v4/sports/basketball_nba/events/synthetic-event/odds?regions=us&markets=totals&oddsFormat=decimal'


def discovery(offset=600):
    e=event();e['commence_time']=iso(SNAPSHOT['fixture_start_utc']+offset)
    return receipt([e],url=CATALOG)


def detail(offset=600):
    e=priced_event();e['commence_time']=iso(SNAPSHOT['fixture_start_utc']+offset)
    return receipt(e,url=DETAIL)


class EventClockBindingTests(unittest.TestCase):
    def setUp(self):
        self.clock=patch('time.time',return_value=NOW);self.clock.start();self.addCleanup(self.clock.stop)

    def test_unique_plus600_keeps_two_clocks_and_original_snapshot(self):
        snap=deepcopy(SNAPSHOT);before=digest(snap);e,w=bind(discovery(),snap)
        p=w['payload'];self.assertEqual(p['delta_seconds'],600)
        self.assertEqual(p['prematch_deadline_utc'],snap['fixture_start_utc'])
        self.assertEqual(p['archived_start_utc'],snap['fixture_start_utc'])
        self.assertEqual(p['provider_start_utc'],snap['fixture_start_utc']+600)
        self.assertFalse(p['scheduled_times_are_identical']);self.assertEqual(before,digest(snap))
        self.assertEqual(w['sha256'],digest(p));self.assertIn('600 sn',clock_text(w))

    def test_exact_match_retains_exact_mode(self):
        self.assertEqual(bind(discovery(0),SNAPSHOT)[1]['payload']['mode'],'EXACT_SCHEDULE_MATCH')

    def test_other_offsets_not_a_general_time_tolerance(self):
        for offset in (-600,1,300,599,601,900,3600,86400):
            with self.subTest(offset=offset),self.assertRaises(ValueError):bind(discovery(offset),SNAPSHOT)

    def test_offset_requires_unambiguous_same_order_pair(self):
        r=discovery();r['document'].append(deepcopy(r['document'][0]));r['document_sha256']=digest(r['document'])
        with self.assertRaises(ValueError):bind(r,SNAPSHOT)

    def test_reversed_pair_nearby_rejects_binding(self):
        r=discovery();e=deepcopy(r['document'][0]);e['id']='other-event'
        e['home_team'],e['away_team']=e['away_team'],e['home_team'];r['document'].append(e)
        r['document_sha256']=digest(r['document'])
        with self.assertRaisesRegex(ValueError,'REVERSED'):bind(r,SNAPSHOT)

    def test_wrong_competition_cannot_use_nba_clock_rule(self):
        snap=deepcopy(SNAPSHOT);snap['league']='EUROLEAGUE'
        with self.assertRaises(ValueError):bind(discovery(),snap)
        r=discovery();r['document'][0]['sport_key']='basketball_euroleague';r['document_sha256']=digest(r['document'])
        with self.assertRaises(ValueError):bind(r,SNAPSHOT)

    def test_forged_or_unbound_native_receipt_refused(self):
        for field,value in [('source_url','https://other.invalid/events'),('provider','OTHER'),('document_sha256','f'*64)]:
            r=discovery();r[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):bind(r,SNAPSHOT)

    def test_stale_discovery_cannot_bind_fresh_prices(self):
        r=discovery();r['observed_at_utc']=NOW-121;r['ingested_at_utc']=NOW-121
        with self.assertRaisesRegex(ValueError,'FRESH'):bind(r,SNAPSHOT)

    def test_earlier_official_tipoff_stops_even_before_provider_tipoff(self):
        start=SNAPSHOT['fixture_start_utc']
        r=discovery();r['observed_at_utc']=start-5;r['ingested_at_utc']=start-5
        with patch('time.time',return_value=start),self.assertRaisesRegex(ValueError,'EARLIEST'):
            bind(r,SNAPSHOT,asof_utc=start)

    def test_detail_must_keep_catalog_event_id_time_and_pair(self):
        for field,value in [('id','different-event'),('commence_time',iso(SNAPSHOT['fixture_start_utc']+1200)),('home_team','Wrong Team')]:
            d=detail();d['document'][field]=value;d['document_sha256']=digest(d['document'])
            with self.subTest(field=field),self.assertRaises(ValueError):verify_detail(discovery(),d,SNAPSHOT)

    def test_detail_cannot_use_another_source_endpoint(self):
        d=detail();d['source_url']='https://api.the-odds-api.com/v4/sports/basketball_nba/events/OTHER/odds'
        with self.assertRaises(ValueError):verify_detail(discovery(),d,SNAPSHOT)

    def test_parser_needs_discovery_to_accept_offset_and_keeps_binding(self):
        d=detail()
        with self.assertRaises(ValueError):odds_observations(d,SNAPSHOT)
        rows,rejected=odds_observations(d,SNAPSHOT,discovery=discovery())
        self.assertEqual(rejected,0);self.assertEqual(len(rows),1)
        p=rows[0]['payload'];self.assertEqual(p['fixture']['tipoff_utc'],SNAPSHOT['fixture_start_utc'])
        self.assertEqual(p['source']['event_clock_binding']['payload']['provider_start_utc'],SNAPSHOT['fixture_start_utc']+600)
        self.assertEqual(p['calibration_status'],'NOT_CALIBRATED')
        self.assertEqual(p['settlement_verification'],'NOT_VERIFIED_BY_OBSERVATION')

    def test_strict_matches_is_not_relaxed_for_other_callers(self):
        self.assertFalse(matches(discovery()['document'][0],SNAPSHOT))

    def test_bound_raw_distribution_does_not_claim_settlement_or_confidence(self):
        import numpy as np
        from hybrid_engine.distributions import gaussian_forecast
        from hybrid_engine.decision_audit import trace_for
        from hybrid_engine.decision_layer import DecisionDistribution
        forecast=gaussian_forecast([110,105],[10,10],np.ones((4,2)),method='RQMC_HALTON')
        distribution=DecisionDistribution(forecast,trace_for(SNAPSHOT))
        rows,_=odds_observations(detail(),SNAPSHOT,discovery=discovery())
        view=assess(rows[0],distribution,asof_utc=NOW)
        self.assertIsNone(view['rows'][0]['expected_value']);self.assertIsNone(view['confidence_index'])
        self.assertFalse(view['selection_enabled']);self.assertIn('600 sn',render_market(view))
        self.assertIn('SOURCE_AVAILABLE_AFTER_ORIGINAL_FORECAST',view['reasons'])


class OffsetBridgeTests(unittest.TestCase):
    def setUp(self):
        self.clock=patch('time.time',return_value=NOW);self.clock.start();self.addCleanup(self.clock.stop)
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.fake=FakeProvider();self.original=self.fake.__call__

    def getter(self,provider,url,key,**kwargs):
        r=self.original(provider,url,key,**kwargs)
        if provider=='THE_ODDS_API':
            d=r['document']
            if urlsplit(url).path.endswith('/events'):
                d[0]['commence_time']=iso(SNAPSHOT['fixture_start_utc']+600)
            elif '/odds?' in url:
                d['commence_time']=iso(SNAPSHOT['fixture_start_utc']+600)
            r['document_sha256']=digest(d)
        return r

    def test_bounded_offset_connects_native_quotes_and_persists_catalog(self):
        access=ProviderAccess({'THE_ODDS_API':SECRET},getter=self.getter,clock=lambda:NOW)
        r=ProviderBridge(access,self.root/'evidence',clock=lambda:NOW).collect(SNAPSHOT)
        row=r['providers']['THE_ODDS_API'];self.assertEqual(row['status'],'OBSERVED_RULES_AND_CALIBRATION_PENDING')
        self.assertEqual(row['event_clock_binding']['payload']['delta_seconds'],600)
        self.assertTrue((self.root/'evidence'/('provider-'+row['discovery_source_pin']+'.json')).exists())
        self.assertIn('600 sn',render(r));self.assertFalse(r['forecast_changed'])

    def test_diagnostic_binds_without_requesting_odds(self):
        access=ProviderAccess({'THE_ODDS_API':SECRET},getter=self.getter,clock=lambda:NOW)
        r=ProviderBridge(access,self.root/'evidence',clock=lambda:NOW,diagnostic_only=True).collect(SNAPSHOT)
        self.assertEqual(r['providers']['THE_ODDS_API']['status'],'NBA_PROVIDER_OFFSET_BOUND')
        self.assertFalse(any('/odds?' in u for _,u in self.fake.calls))

    def test_season_plan_denial_is_cached_without_new_api_requests(self):
        def getter(provider,url,key,**kw):
            r=self.original(provider,url,key,**kw)
            if '/games?' in url:
                r['document']=dict(errors={'plan':'Free plan cannot access this season'})
                r['document_sha256']=digest(r['document'])
            return r
        access=ProviderAccess({'API_BASKETBALL':SECRET},getter=getter,clock=lambda:NOW)
        b=ProviderBridge(access,self.root/'evidence',clock=lambda:NOW)
        first=b.collect(SNAPSHOT);count=len(self.fake.calls);second=b.collect(SNAPSHOT)
        self.assertEqual(count,len(self.fake.calls))
        row=second['providers']['API_BASKETBALL'];self.assertEqual(row['coverage_cache'],'UNCHANGED_SEASON_RESTRICTION_REUSED')
        self.assertEqual(row['observed_at_utc'],first['providers']['API_BASKETBALL']['observed_at_utc'])
        self.assertIn('kesin neden ayrıca doğrulanmalı',render(second))


if __name__=='__main__':unittest.main()
