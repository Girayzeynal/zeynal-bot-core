from unittest import TestCase
from copy import deepcopy
from hybrid_engine.conditional_rotation import conditional_rotation
from hybrid_engine.data import Abstain
from tests.test_player_minutes import inputs,NOW

class ConditionalRotationTests(TestCase):
    def test_uncertain_absence_produces_only_hypothetical_scenarios(self):
        d=inputs()
        d['review']['records']=[dict(team_id='1',player_id='100',source='ESPN',
                                     status='Questionable',status_updated_at_utc=NOW-10)]
        d['rosters']['home']['players'].append('999')
        d.pop('generated_at_utc')
        before=deepcopy(d)
        result=conditional_rotation(**d,now=NOW)
        self.assertEqual(d,before)
        self.assertFalse(result['training_eligible'])
        self.assertFalse(result['score_computed'])
        self.assertIsNone(result['availability_probability'])
        home=result['teams']['home']
        self.assertEqual(home['unseen_current_roster_players'],['999'])
        self.assertAlmostEqual(sum(home['baseline_hypothetical_minutes'].values()),240.)
        case=home['counterfactuals'][0]
        self.assertEqual(case['projected_minutes']['100'],0.)
        self.assertAlmostEqual(sum(case['projected_minutes'].values()),240.)

    def test_future_box_rejected(self):
        d=inputs();d.pop('generated_at_utc')
        d['boxes'][0]['source']['observed_at_utc']=NOW+1
        with self.assertRaises(ValueError):conditional_rotation(**d,now=NOW)
