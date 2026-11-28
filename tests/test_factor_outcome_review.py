from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import json
import os
from core.team_identity import digest
from hybrid_engine.rotation_efficiency import fit,predict,VERSION
from hybrid_engine.historical_five_results import evaluate
from tests.test_rotation_efficiency import RotationEfficiencyTests

class FactorOutcomeTests(TestCase):
    def test_valid_factor_receipt_pending_then_settled(self):
        games=RotationEfficiencyTests().games()
        a=fit(games,500,players_enabled=False);b=fit(games,500,players_enabled=True)
        rotations=[games[-1]['minutes'][s] for s in ('home','away')]
        def side(i):
            rows=[dict(player_id=k,average_minutes=v) for k,v in rotations[i].items()]
            return dict(team_id=str(i+1),main_five=rows[:5],bench=rows[5:])
        r=dict(fixture_id='future',fixture_start_utc=2000,generated_at_utc=550,
               original_snapshot_sha256='a'*64,teams=dict(home=side(0),away=side(1)))
        p=dict(format=VERSION,fixture_id='future',fixture_start_utc=2000,generated_at_utc=600,
               original_snapshot_sha256='a'*64,rotation_sha256=digest(r),
               model_sha256=b['sha256'],control_sha256=a['sha256'],production_enabled=False,forecast_changed=False,
               original_prediction=dict(home=110.,away=100.,total=210.),
               team_control=predict(a,'1','2',rotations),player_candidate=predict(b,'1','2',rotations))
        row=dict(fixture_id='future',snapshot_sha256='a'*64,fixture_start_utc=2000,
                 prediction_generated_at_utc=400,prediction=[110.,100.],season='2026/2027',
                 home='H',away='A',actual=None,label_available_utc=None)
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            def save(prefix,body):
                pin=digest(body);path=root/(prefix+pin+'.json')
                path.write_text(json.dumps(dict(payload=body,sha256=pin)));os.utime(path,(600,600));return path
            save('historical-five-',r);save('factor-model-',a['payload']);save('factor-model-',b['payload'])
            save('factor-score-',p)
            with patch('ledger_reports.LedgerReports.read',return_value=dict(status='VERIFIED_LIVE_REPORT',forecasts=[row])):
                report=evaluate(root,root/'ledger.sqlite',now=700)
                self.assertEqual(report['exclusions'],{})
                self.assertEqual(report['groups'][0]['pending'],1)
                row.update(actual=[108,102],label_available_utc=3000)
                report=evaluate(root,root/'ledger.sqlite',now=3100)
                self.assertEqual(report['groups'][0]['matched'],1)
                self.assertEqual(report['groups'][0]['metrics']['original_prediction']['total_mae'],0)
