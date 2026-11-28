from unittest import TestCase
from core.team_identity import digest
from hybrid_engine.historical_five import summarize_team
from tests.test_player_minutes import inputs,NOW

class HistoricalFiveTests(TestCase):
    def boxes(self):
        boxes=inputs()['boxes']
        for b in boxes:
            b['source_digest']=digest(b['source'])
            for i,p in enumerate(b['players']):
                p['minutes_display']=str([40,38,36,34,32,24,20,16][i])
                p['points']=i+1
        return boxes

    def test_ranked_by_six_game_minutes_without_injury_or_lineup(self):
        r=summarize_team(self.boxes(),'1','2026/2027',now=NOW,target_id='future')
        self.assertEqual([p['player_id'] for p in r['main_five']],['100','101','102','103','104'])
        self.assertEqual(r['main_five'][0]['average_minutes'],40)
        self.assertEqual(r['main_five'][0]['average_points'],1)
        self.assertEqual(r['mean_team_minutes'],240)
        self.assertEqual(len(r['bench']),3)
        self.assertFalse(r['confirmed_starting_five'])

    def test_future_observation_rejected_even_with_valid_digest(self):
        boxes=self.boxes()
        boxes[0]['source']['observed_at_utc']=NOW+1
        boxes[0]['source_digest']=digest(boxes[0]['source'])
        with self.assertRaises(ValueError):
            summarize_team(boxes,'1','2026/2027',now=NOW,target_id='future')

    def test_missing_points_not_replaced_with_zero(self):
        boxes=self.boxes();boxes[0]['players'][0].pop('points')
        r=summarize_team(boxes,'1','2026/2027',now=NOW,target_id='future')
        self.assertIsNone(r['main_five'][0]['average_points'])
