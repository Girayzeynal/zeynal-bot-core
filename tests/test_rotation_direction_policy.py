from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch,Mock
from hybrid_engine.rotation_direction_policy import action,audit,blocked
from hybrid_engine.rotation_cycle import RotationCycle
from hybrid_engine.rotation_refresh import refresh_one
from hybrid_engine.rotation_selective import capture_new as selective
from hybrid_engine.rotation_forward_calibration import capture_new as forward

class DirectionPolicyTests(TestCase):
    def test_verified_win_protected_loss_investigated_push_held(self):
        self.assertEqual(action('WIN',verified=True),'PROTECT_SUCCESS')
        self.assertEqual(action('LOSS',verified=True),'INVESTIGATE_FAILURE')
        self.assertEqual(action('PUSH',verified=True),'HOLD_PUSH')
        for x in ('WIN','LOSS','PUSH',20,-20,None):
            self.assertEqual(action(x),'HOLD_UNVERIFIED')
        self.assertFalse(blocked()['parameter_change'])

    def test_numeric_error_never_creates_direction_label(self):
        def row(i,actual):
            return (1,1,str(i),{},dict(actual=actual,fixture_start_utc=100,
                label_available_utc=200 if actual is not None else None,
                actual_periods={'home':[actual[0]/4]*4,'away':[actual[1]/4]*4} if actual else {}))
        r=audit([row(1,[100,100]),row(2,[120,120]),row(3,None)],300)
        self.assertEqual(r['settled'],2)
        self.assertEqual(r['pending'],1)
        self.assertEqual(r['verified_wins'],0)
        self.assertEqual(r['verified_losses'],0)
        self.assertFalse(r['parameter_change'])

    def test_legacy_entrypoints_no_write(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);ledger=root/'ledger';ledger.write_bytes(b'unchanged')
            for f,args in [(refresh_one,(root,ledger)),(selective,(root,ledger,'x')),(forward,(root,ledger,'x'))]:
                self.assertEqual(f(*args)['status'],'HOLD_UNVERIFIED')
            self.assertEqual(list(root.iterdir()),[ledger])
            self.assertEqual(ledger.read_bytes(),b'unchanged')

    def test_old_flags_cannot_reenable_score_learning(self):
        with TemporaryDirectory() as tmp:
            ledger=Path(tmp)/'ledger';ledger.touch()
            capture=Mock(return_value='a'*64)
            c=RotationCycle(tmp,ledger,None,capture=capture,clock=lambda:1000,forward_enabled=True,selective_enabled=True,refresh_enabled=True)
            row=dict(fixture_id='f',snapshot_sha256='s',league='NBA',actual=None,fixture_start_utc=5000)
            with patch('hybrid_engine.runtime_reports.RuntimeLedgerReports.read',return_value=dict(status='VERIFIED_LIVE_REPORT',forecasts=[row])),patch('hybrid_engine.rotation_report.records',return_value=([],{},0)),patch('hybrid_engine.rotation_refresh.refresh_one') as r,patch('hybrid_engine.rotation_selective.capture_new') as s,patch('hybrid_engine.rotation_forward_calibration.capture_new') as f:
                self.assertEqual(c.tick()['status'],'CAPTURED')
                capture.assert_called_once()
                r.assert_not_called();s.assert_not_called();f.assert_not_called()
            self.assertIn('HOLD_UNVERIFIED',c.render_status())
