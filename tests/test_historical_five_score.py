from unittest import TestCase
from unittest.mock import patch
from core.team_identity import digest
from hybrid_engine.historical_five_score import compare,rotation_from_summary
from hybrid_engine.data import Abstain

class HistoricalFiveScoreTests(TestCase):
    def setup_case(self):
        snapshot=dict(fixture_id='target',fixture_start_utc=10000,season='2026/2027',
                      home={'provider_id':'1'},away={'provider_id':'2'},prediction={'home':110,'away':100})
        def team(t,base):
            rows=[dict(player_id=str(base+i),average_minutes=30.) for i in range(8)]
            return dict(team_id=t,main_five=rows[:5],bench=rows[5:])
        summary=dict(format='NBA_HISTORICAL_MAIN_FIVE_V1',status='HISTORICAL_ROTATION_READY',
            fixture_id='target',fixture_start_utc=10000,generated_at_utc=8000,
            original_snapshot_sha256=digest(snapshot),teams={'home':team('1',100),'away':team('2',200)})
        summary['sha256']=digest(summary)
        control=dict(season='2026/2027',cutoff_utc=7000,training_sha256='x',training_fixture_ids=['past'])
        model=dict(control,training_games=30,players=['100','200'])
        return snapshot,summary,dict(control=control,candidate={'payload':model,'sha256':digest(model)})

    def test_separate_scores_and_full_rotation(self):
        s,r,p=self.setup_case()
        self.assertAlmostEqual(sum(rotation_from_summary(r['teams']['home']).values()),240)
        with patch('hybrid_engine.historical_five_score.projected_pair',return_value=[105.,101.]),patch('hybrid_engine.historical_five_score.conditional_pair',return_value={'prediction':[107.,100.]}):
            result=compare(r,s,p,now=8001)
        self.assertEqual(result['player_candidate']['total'],207)
        self.assertEqual(result['candidate_minus_control'],[2,-1])
        self.assertFalse(result['forecast_changed'])
        self.assertFalse(result['production_enabled'])
        self.assertEqual(result['injury_source_calls'],0)

    def test_training_target_and_late_publication_rejected(self):
        s,r,p=self.setup_case()
        with self.assertRaises(Abstain):compare(r,s,p,now=9700)
        p['control']['training_fixture_ids']=['target']
        p['candidate']['payload']['training_fixture_ids']=['target']
        with self.assertRaises(Abstain):compare(r,s,p,now=8001)
