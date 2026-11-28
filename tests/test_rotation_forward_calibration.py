from unittest import TestCase
from hybrid_engine.rotation_forward_calibration import candidate
from hybrid_engine.data import Abstain
from hybrid_engine.rotation_joint import MARKETS

class ForwardCorrectionTests(TestCase):
    def entry(self,i,g,label=None,actual=27):
        p=dict(original_model_version='V1',simulation=dict(markets={k:dict(home=dict(mean=25*len(v)),away=dict(mean=25*len(v))) for k,v in MARKETS.items()}))
        row=dict(fixture_id=str(i),season='2026/2027',fixture_start_utc=g+1000,snapshot_sha256=str(i),
            label_available_utc=label,actual=[actual*4]*2 if label is not None else None,
            actual_periods=dict(home=[actual]*4,away=[actual]*4))
        return (g,g,str(i),p,row)
    def test_no_prior_no_publication(self):
        t=self.entry(1,1000)
        with self.assertRaises(Abstain):candidate([t],t,1001)
    def test_strict_cutoff_and_score_conservation(self):
        prior=self.entry(1,1000,2500);equal=self.entry(2,1500,3000)
        target=self.entry(3,3000)
        result=candidate([prior,equal,target],target,3010)
        self.assertEqual(result['prior_n'],1)
        self.assertEqual(result['prior'][0]['fixture_id'],'1')
        self.assertAlmostEqual(result['corrected_total'],200+16/9)
        self.assertAlmostEqual(sum(result['corrected_team_scores']),result['corrected_total'])
        self.assertFalse(result['calibrated'])
    def test_late_publication_rejected(self):
        target=self.entry(3,3000)
        with self.assertRaises(Abstain):candidate([],target,3800)
