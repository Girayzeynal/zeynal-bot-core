from unittest import TestCase
from unittest.mock import patch
from hybrid_engine.rotation_efficiency import fit,predict
from hybrid_engine.data import Abstain

class RotationEfficiencyTests(TestCase):
    def games(self):
        out=[]
        for i in range(32):
            a={str(100+j):30. for j in range(8)}
            b={str(200+j):30. for j in range(8)}
            a['100']+=i%5;a['101']-=i%5
            pace=98+i%4
            out.append(dict(fixture_id=str(i),league='NBA',season='2026/2027',
                fixture_start_utc=100+i,available_at_utc=200+i,
                home_team_id='1',away_team_id='2',minutes={'home':a,'away':b},
                pace=pace,ratings=[110+i%5,105+i%3]))
        return out
    def test_fit_predict_shared_pace_and_rating(self):
        games=self.games()
        m=fit(games,500,players_enabled=True)
        r=predict(m,'1','2',[games[-1]['minutes']['home'],games[-1]['minutes']['away']])
        self.assertAlmostEqual(r['total'],r['home']+r['away'])
        self.assertAlmostEqual(r['home'],r['estimated_shared_possessions']*r['home_points_per_100']/100)
        self.assertEqual(r['represented_minutes'],[240.,240.])
        self.assertFalse(m['payload']['individual_causal_defense_identified'])
    def test_reject_late_training_label(self):
        games=self.games();games[-1]['available_at_utc']=501
        with self.assertRaises(ValueError):fit(games,500,players_enabled=True)
    def test_no_fake_fit_on_insufficient_games(self):
        with self.assertRaises(Abstain):fit(self.games()[:2],500,players_enabled=True)
