from unittest import TestCase
from unittest.mock import patch
from hybrid_engine.rotation_report import render,result_metrics
class RotationReportTests(TestCase):
    def test_no_records_does_not_invent_forecast(self):
        with patch('hybrid_engine.rotation_report.records',return_value=([],{},0)):
            self.assertIn('Yeni tahmin üretilmedi',render('/tmp/a','/tmp/b')[0])
            self.assertIn('Henüz gerçek hata',render('/tmp/a','/tmp/b',['results'])[0])
    def test_invalid_args(self):
        self.assertIn('Kullanım',render('/tmp/a','/tmp/b',['x','y'])[0])
    def test_final_metrics_and_pending(self):
        from hybrid_engine.rotation_joint import MARKETS
        p=dict(simulation=dict(markets={k:dict(total=dict(mean=50*len(v),p10=40*len(v),p90=60*len(v),p05=35*len(v),p95=65*len(v))) for k,v in MARKETS.items()}))
        r=dict(season='2026/2027',actual=[100,100],actual_periods=dict(home=[25]*4,away=[25]*4),
            label_available_utc=20,fixture_start_utc=10,prediction=[101,100])
        entries=[(1,1,'x',p,r),(2,2,'y',p,dict(r,actual=None))]
        m=result_metrics(entries,30)['2026/2027']
        self.assertEqual((m['matched'],m['pending']),(1,1))
        self.assertEqual(m['markets']['FULL']['mae'],0)
        self.assertEqual(m['original_total_mae'],1)
