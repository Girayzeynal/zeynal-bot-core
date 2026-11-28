from unittest import TestCase
import numpy as np
from hybrid_engine.rotation_periods import fit,predict,allocate
from tests.test_rotation_efficiency import RotationEfficiencyTests

class RotationPeriodTests(TestCase):
    def games(self):
        games=RotationEfficiencyTests().games()
        for i,g in enumerate(games):
            q=[[28+i%3,27,30,25],[25,26,27+i%3,26]]
            g.update(quarters=q,score=[sum(v) for v in q])
        return games
    def test_period_score_and_half_conservation(self):
        games=self.games();m=fit(games,500,players_enabled=True)
        r=predict(m,'1','2',[games[-1]['minutes'][s] for s in ('home','away')],[114.4,110.7])
        np.testing.assert_allclose(np.asarray(r['quarters']).sum(axis=0),[114.4,110.7])
        np.testing.assert_allclose(np.asarray(r['halves']).sum(axis=0),[114.4,110.7])
        self.assertEqual(r['scenarios'],4096)
        self.assertTrue(r['scenario_team_totals_conserved'])
        self.assertFalse(r['intervals_calibrated'])
    def test_integer_allocation_conserves_each_side_each_draw(self):
        shares=np.array([[[.1,.2,.3,.4],[.25,.25,.25,.25]],[[.4,.3,.2,.1],[.15,.35,.2,.3]]])
        paths=allocate(shares,[101,111])
        np.testing.assert_array_equal(paths.sum(axis=-1),[[101,111],[101,111]])
    def test_future_label_rejected(self):
        games=self.games();games[-1]['available_at_utc']=501
        with self.assertRaises(ValueError):fit(games,500,players_enabled=True)
