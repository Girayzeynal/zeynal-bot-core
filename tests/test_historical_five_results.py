from unittest import TestCase
from hybrid_engine.historical_five_results import metrics
class HistoricalResultsTests(TestCase):
    def test_matched_error_metrics(self):
        r=dict(actual=[100,90],original_prediction=dict(home=110,away=95),team_control=dict(home=103,away=92),player_candidate=dict(home=102,away=89))
        m=metrics([r])
        self.assertEqual(m['original_prediction']['total_mae'],15)
        self.assertEqual(m['team_control']['total_mae'],5)
        self.assertEqual(m['player_candidate']['total_mae'],1)
        self.assertEqual(m['player_candidate']['margin_mae'],3)
    def test_no_results_not_zero_error(self):
        self.assertEqual(metrics([]),{})
