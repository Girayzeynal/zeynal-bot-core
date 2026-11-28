from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch,Mock
from hybrid_engine.rotation_cycle import RotationCycle,eligible

class RotationCycleTests(TestCase):
    def row(self,i,tip=5000):
        return dict(fixture_id=str(i),snapshot_sha256=str(i),league='NBA',actual=None,fixture_start_utc=tip)
    def test_selection_excludes_close_and_duplicate(self):
        self.assertEqual([r['fixture_id'] for r in eligible([self.row(1),self.row(2,1100),self.row(3),self.row(3)],1000)],['1'])
    def test_capture_once_then_next_match_and_restart(self):
        rows=[self.row(1),self.row(2)];capture=Mock(return_value='a'*64)
        with TemporaryDirectory() as tmp:
            ledger=Path(tmp)/'ledger';ledger.touch()
            cycle=RotationCycle(tmp,ledger,None,capture=capture,clock=lambda:1000)
            with patch('hybrid_engine.runtime_reports.RuntimeLedgerReports.read',return_value=dict(status='VERIFIED_LIVE_REPORT',forecasts=rows)),patch('hybrid_engine.rotation_report.records',return_value=([],{},0)):
                self.assertEqual(cycle.tick()['fixture_id'],'1')
                self.assertEqual(cycle.tick()['fixture_id'],'2')
                self.assertEqual(cycle.tick()['status'],'IDLE')
                self.assertEqual(capture.call_count,2)
            cycle=RotationCycle(tmp,ledger,None,capture=capture,clock=lambda:1000)
            def existing(*a,selector,**k):
                return ([(0,0,'p',{},r) for r in rows if r['fixture_id']==selector],{},0)
            with patch('hybrid_engine.runtime_reports.RuntimeLedgerReports.read',return_value=dict(status='VERIFIED_LIVE_REPORT',forecasts=rows)),patch('hybrid_engine.rotation_report.records',side_effect=existing):
                self.assertEqual(cycle.tick()['status'],'IDLE')
                self.assertEqual(capture.call_count,2)
    def test_failure_retries_without_starving_next(self):
        rows=[self.row(1),self.row(2)];capture=Mock(side_effect=[ValueError('SOURCE_BLOCK'), 'b'*64])
        with TemporaryDirectory() as tmp:
            ledger=Path(tmp)/'ledger';ledger.touch()
            clock=[1000]
            cycle=RotationCycle(tmp,ledger,None,capture=capture,clock=lambda:clock[0])
            with patch('hybrid_engine.runtime_reports.RuntimeLedgerReports.read',return_value=dict(status='VERIFIED_LIVE_REPORT',forecasts=rows)),patch('hybrid_engine.rotation_report.records',return_value=([],{},0)):
                r=cycle.tick();self.assertEqual(r['retry_at_utc'],1300)
                clock[0]=1300
                self.assertEqual(cycle.tick()['fixture_id'],'2')
                self.assertEqual(capture.call_count,2)
