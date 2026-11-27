from unittest import TestCase
import numpy as np
from hybrid_engine.rotation_joint import residual_pool,simulate
from hybrid_engine.data import Abstain

class JointResearchTests(TestCase):
    def row(self,i,*,label=2000):
        q=[[25.,25.]]*4
        actual=[[25+i,25,25,25],[25,25,25,25]]
        return dict(fixture_id=str(i),league='NBA',season='2026/2027',model_version='V1',
            model_digest='a',snapshot_sha256=str(i),fixture_start_utc=1000,
            prediction_generated_at_utc=500,first_archived_at_utc=501,
            label_available_utc=label,actual=[sum(v) for v in actual],actual_periods=dict(home=actual[0],away=actual[1]),
            prediction=[100,100],predicted_quarters=q)
    def test_past_only_deduplication(self):
        rows=[self.row(1),self.row(2),self.row(3,label=4000),self.row(1)]
        pool=residual_pool(rows,self.row(9),3000)
        self.assertEqual([r['fixture_id'] for r in pool],['1','2'])
    def test_joint_variable_totals_and_repeatable(self):
        pool=residual_pool([self.row(1),self.row(9)],self.row(8),3000)
        a=simulate([[25,25]]*4,pool);b=simulate([[25,25]]*4,pool)
        self.assertGreater(a['unique_game_totals'],1)
        self.assertEqual(a['scenario_sha256'],b['scenario_sha256'])
        self.assertAlmostEqual(sum(a['regulation_outcomes'].values()),1.)
        self.assertEqual(a['point_total'],200.)
        self.assertFalse(a['calibrated'])
    def test_no_history_abstains(self):
        with self.assertRaises(Abstain):residual_pool([],self.row(9),3000)
