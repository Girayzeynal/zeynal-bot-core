from unittest import TestCase
import numpy as np
from hybrid_engine.rotation_selective import severity,proposal,guard,axes

def row(i,err,decision=None,label=None):
    g=i*1000 if decision is None else decision
    q=np.full((4,2),25.)
    return dict(fixture_id=str(i),decision=g,label=g+500 if label is None else label,raw=q.tolist(),actual=(q+err).tolist())

class SelectiveTests(TestCase):
    def test_severity_symmetric(self):
        self.assertEqual(severity(-21,'FULL'),'CRITICAL')
        self.assertEqual(severity(3,'FULL'),'EXCELLENT')
        self.assertEqual(severity(4,'1Q'),'MODERATE')
    def test_isolated_outlier_not_learned(self):
        np.testing.assert_array_equal(proposal([row(1,20),row(2,0),row(3,0)]),np.zeros((4,2)))
    def test_repeat_errors_bounded(self):
        v=proposal([row(1,8),row(2,8),row(3,0)])
        self.assertTrue(np.all(v>0));self.assertTrue(np.all(v<=3))
    def test_guard_rejects_regression_on_good_forecasts(self):
        v=[row(i,8) for i in range(1,5)]+[row(5,0),row(6,0)]
        self.assertEqual(guard(v)['status'],'REJECT_REGRESSION')
    def test_guard_does_not_use_equal_label_clock(self):
        v=[row(1,8,label=3000),row(2,8,label=3000),row(3,8)]
        self.assertEqual(guard(v)['paired_cases'],0)
    def test_axes_conserve_halves(self):
        a=axes(np.full((4,2),25))
        self.assertEqual(a['FULL','total'],a['1H','total']+a['2H','total'])
