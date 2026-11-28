from unittest import TestCase
from hybrid_engine.rotation_calibration import audit,radius
from hybrid_engine.rotation_joint import MARKETS

class CalibrationTests(TestCase):
    def entry(self,i,g,label,actual=27):
        p=dict(original_model_version='V1',simulation=dict(markets={
            k:dict(home=dict(mean=25*len(v)),away=dict(mean=25*len(v))) for k,v in MARKETS.items()}))
        row=dict(fixture_id=str(i),season='2026/2027',fixture_start_utc=g+400,
            label_available_utc=label,actual=[actual*4,actual*4] if label is not None else None,
            actual_periods=dict(home=[actual]*4,away=[actual]*4))
        return (g,g,str(i),p,row)
    def test_strict_prior_label_clock(self):
        e=[self.entry(1,1000,2000),self.entry(2,2000,3000),self.entry(3,2001,3100)]
        r=audit(e,4000)['groups'][0]
        self.assertEqual([v['prior_n'] for v in r['trace']],[0,0,1])
        self.assertEqual(r['paired_correction_cases'],1)
        self.assertLess(r['markets']['FULL']['corrected_mae'],r['markets']['FULL']['raw_mae'])
    def test_pending_no_zero_error_or_self_fit(self):
        r=audit([self.entry(1,1000,None)],2000)['groups'][0]
        self.assertEqual(r['pending'],1)
        self.assertIsNone(r['markets']['FULL']['corrected_mae'])
    def test_finite_sample_ranks(self):
        self.assertIsNone(radius([1,2,3],80))
        self.assertEqual(radius([1,2,3,4],80),4)
        self.assertIsNone(radius(list(range(8)),90))
        self.assertEqual(radius(list(range(9)),90),8)
    def test_duplicates_rejected(self):
        e=self.entry(1,1000,2000)
        with self.assertRaises(ValueError):audit([e,e],3000)
