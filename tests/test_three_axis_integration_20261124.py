"""Synthetic coverage/identity/priority checks; no live provider assertions."""
from unittest import TestCase
from unittest.mock import patch
from hybrid_engine.provider_bridge import native_market_coverage
from hybrid_engine.europe_player_identity_audit import match_candidates
from hybrid_engine.research_diagnostics import ResearchCycle

class ThreeAxisIntegrationTests(TestCase):
    def test_requested_returned_and_admitted_are_distinct(self):
        document={'bookmakers':[{'markets':[{'key':'totals'},{'key':'totals_q1'}]}]}
        observed=[{'payload':{'quotes':[{'period':'FULL','market':'TOTAL'}]}}]
        r=native_market_coverage(document,['totals','totals_q1','team_totals'],observed)
        self.assertEqual(r['not_returned'],['team_totals'])
        self.assertEqual(r['admitted_quote_counts'],{'FULL/TOTAL':1})
        self.assertFalse(r['player_props_requested'])

    def test_exact_player_identity_never_promotes_news_to_model_input(self):
        ctx=dict(league='EUROLEAGUE',fixture_id='f',home=dict(official_name='FC Barcelona',provider_id='BAR'),
                 away=dict(official_name='Fenerbahce Tarfin Istanbul',provider_id='ULK'))
        native=dict(fixture_id='f',teams=dict(home=dict(status='OFFICIAL_SEASON_REGISTRATION_OBSERVED',
            registered_players=[dict(player_id='011199',name='NEBO, JOSH',team_id='BAR')]),away={}))
        news=dict(sources=[dict(source='A',unverified_player_candidates=[
            dict(player_text='Josh Nebo',team_text='Barcelona',source_reported_status='OUT_SITE_REPORTED')]),
            dict(source='B',unverified_player_candidates=[
            dict(player_text='Josh Nebo',team_text='Barcelona',source_reported_status='CLEARED_SITE_REPORTED')])])
        result=match_candidates(ctx,native,news)
        self.assertEqual(len(result['matched']),1)
        self.assertEqual(result['matched'][0]['player_id'],'011199')
        self.assertEqual(result['conflicts'],1)
        self.assertFalse(result['model_input']);self.assertFalse(result['availability_verified'])
        self.assertFalse(match_candidates(ctx,dict(native,fixture_id='other'),news)['matched'])

    def test_earliest_fixture_kept_even_under_queue_pressure(self):
        cycle=ResearchCycle(None,None)
        with patch('time.time',return_value=1000):
            for i in range(16):
                self.assertTrue(cycle.request_fixture(dict(league='NBA',fixture_id=str(i),fixture_start_utc=3000+i)))
            self.assertTrue(cycle.request_fixture(dict(league='EUROLEAGUE',fixture_id='urgent',fixture_start_utc=1400)))
            self.assertEqual(cycle.requested_fixtures[0],'urgent')
            self.assertNotIn('15',cycle.requested_deadlines)
            self.assertFalse(cycle.request_fixture(dict(league='EUROCUP',fixture_id='late',fixture_start_utc=5000)))
