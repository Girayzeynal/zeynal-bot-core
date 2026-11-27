from unittest import TestCase
from hybrid_engine.prequential_residual import calibrate, empirical_band, bands_for

class ResidualTests(TestCase):
    def test_empty_history_preserves_scores_and_quarters(self):
        score=[100.,120.]
        quarters=[[25.,30.]]*4
        p,q=calibrate(score,quarters,[])
        self.assertEqual(p,score)
        self.assertEqual(q,quarters)
        self.assertIsNone(empirical_band(220,[],.8))

    def test_past_residual_and_quarter_conservation(self):
        prior=[dict(predictions={'BLEND':[110.,120.]},actual=[100.,100.],
                    actual_team_quarters=[[20,20,30,30],[25]*4])]*8
        p,q=calibrate([110.,120.],[[27.5,30.]]*4,prior)
        self.assertLess(sum(p),230.)
        self.assertAlmostEqual(sum(x[0] for x in q),p[0])
        self.assertAlmostEqual(sum(x[1] for x in q),p[1])
        self.assertLess(q[0][0],q[3][0])

    def test_empirical_rank_and_insufficient_evidence(self):
        self.assertIsNone(empirical_band(100,[1,2,3],.9))
        self.assertEqual(empirical_band(100,[1,2,3,4],.8),[96,104])
        self.assertIsNone(bands_for({'TOTAL':100},[])['TOTAL']['0.8'])
