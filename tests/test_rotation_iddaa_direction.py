from tempfile import TemporaryDirectory
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import time
from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.rotation_iddaa_direction import build,capture_one,review,side,PREFIX
from hybrid_engine.iddaa_comparison import remember

class HalfReferenceTests(TestCase):
    def test_direction_without_payment_or_parameter_change(self):
        now=int(time.time());tip=now+7200
        with TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'player-shadow';folder.mkdir()
            src=root/'iddaa-bulletin';src.mkdir()
            r=dict(league='NBA',fixture_id='f',snapshot_sha256='s',fixture_start_utc=tip,
                first_archived_at_utc=now-50,home='Washington Wizards',away='Orlando Magic',actual=None)
            p=dict(original_snapshot_sha256='s',fixture_id='f',fixture_start_utc=tip,
                forecast_changed=False,calibrated=False,production_enabled=False,
                simulation={'markets':{'1H':{'total':{'mean':113.5}}}})
            raw=(now-50,now-49,'a'*64,p,r)
            doc=dict(platform='İddaa',league='NBA',fixture_id='f',observed_at_utc=now-10,
                events=[dict(id=123,home='Washington',away='Orlando',start=tip,quotes=[dict(period='1H',line=112.5)])])
            pin=digest(doc);publish_json(src/('bulletin-'+pin+'.json'),doc)
            remember(src,doc,pin,now)
            with patch('hybrid_engine.rotation_iddaa_direction.time.time',return_value=now+2):
                self.assertEqual(capture_one(root,raw),'CAPTURED_HALF_REFERENCE')
                self.assertEqual(capture_one(root,raw),'ALREADY_RECORDED')
            # Receipt test uses real filesystem clock; advance the audit clock.
            path=folder/(PREFIX+raw[2]+'.json')
            import os
            os.utime(path,(now+2,now+2))
            self.assertEqual(review(folder,[raw],now+3)['counts'],{'PENDING':1})
            r.update(actual=[60,60],label_available_utc=tip+3600,
                actual_periods=dict(home=[30,30,0,0],away=[30,30,0,0]))
            self.assertEqual(review(folder,[raw],tip+3601)['counts'],{'CORRECT':1})
            self.assertEqual(capture_one(root,raw),'HOLD_CLOSED')
            self.assertEqual(side(240,215.5),'OVER')
            with self.assertRaises(ValueError):build(folder,raw,tip-300)
