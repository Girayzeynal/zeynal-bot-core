from unittest import TestCase
from hybrid_engine.rotation_period_results import metrics,MARKETS

class PeriodResultTests(TestCase):
    def test_quarter_and_half_errors(self):
        original=[[30,20],[30,20],[30,20],[30,20]]
        actual=[[25,25],[25,25],[25,25],[25,25]]
        control=[[27,24]]*4;candidate=[[25,25]]*4
        intervals={k:dict(total=[45,50,55] if k.endswith('Q') else [90,100,110]) for k in MARKETS}
        r=dict(actual=actual,original=dict(quarters=original),team_allocation=dict(quarters=control,conditional_80_intervals=intervals),
            player_allocation=dict(quarters=candidate,conditional_80_intervals=intervals))
        m=metrics([r]);self.assertEqual(m['original']['1Q']['margin_mae'],10)
        self.assertEqual(m['team_allocation']['1H']['total_mae'],2)
        self.assertEqual(m['player_allocation']['2H']['total_mae'],0)
        self.assertEqual(m['player_allocation']['1Q']['conditional_interval_hits'],1)
    def test_pending_is_not_zero_error(self):
        self.assertEqual(metrics([]),dict(original={},team_allocation={},player_allocation={}))
