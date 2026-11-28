from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from copy import deepcopy
import time
import numpy as np
from core.team_identity import digest
from hybrid_engine.data import Abstain
from hybrid_engine.rotation_joint import simulate
from hybrid_engine.rotation_refresh import candidate,observations,refresh_one,review,comparison,PREFIX
from hybrid_engine.rotation_cycle import RotationCycle
from hybrid_engine.boxes import publish_json

def entry(i,g,tip,label=None,actual=19):
    pool=[dict(errors=np.full((4,2),v).tolist()) for v in (-2,2)]
    sim=simulate(np.full((4,2),25.),pool)
    p=dict(format='joint',original_model_version='V1',simulation=sim,residual_pool_sha256=digest(pool))
    row=dict(fixture_id=str(i),season='2026/2027',fixture_start_utc=tip,snapshot_sha256=str(i),
        label_available_utc=label,actual=[actual*4]*2 if label is not None else None,
        actual_periods=dict(home=[actual]*4,away=[actual]*4),home='Home',away='Away')
    return (g,g+.1,digest(p|{'i':i}),p,row),pool

class RefreshTests(TestCase):
    def fixture(self):
        now=int(time.time())
        prior=[entry(i,now-9000,now-8000,now-6000)[0] for i in (1,2,3)]
        t,pool=entry(4,now-9000,now+10000)
        return now,prior+[t],t,pool
    def test_new_clock_allows_old_pending_target_but_no_future_labels(self):
        now,rows,t,pool=self.fixture()
        equal=entry(5,now-9000,now-8000,now)[0]
        future=entry(6,now-9000,now-8000,now+1)[0]
        other=entry(7,now-9000,now-8000,now-6000)[0];other[4]['season']='2025/2026'
        rows.extend([equal,future,other]);before=deepcopy(rows)
        with TemporaryDirectory() as tmp:
            folder=Path(tmp);pin=digest(pool)
            publish_json(folder/('joint-pool-'+pin+'.json'),dict(payload=pool,sha256=pin))
            p=candidate(folder,rows,t,now)
        self.assertEqual(p['prior_n'],3)
        self.assertLess(p['simulation']['markets']['FULL']['total']['mean'],200)
        self.assertEqual(p['screen']['status'],'INSUFFICIENT_CHRONOLOGICAL_EVIDENCE')
        self.assertEqual(rows,before)
        self.assertFalse(p['calibrated'])
    def test_cutoff_and_settled_target(self):
        now,rows,t,pool=self.fixture()
        with self.assertRaises(Abstain):candidate(Path('.'),rows,t,t[4]['fixture_start_utc']-300)
        t[4]['label_available_utc']=now;t[4]['actual']=[76,76]
        with self.assertRaises(Abstain):candidate(Path('.'),rows,t,now)
    def test_persist_replay_restart_dedup_and_later_result(self):
        now,rows,t,pool=self.fixture()
        with TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'player-shadow';folder.mkdir();ledger=root/'ledger';ledger.write_bytes(b'unchanged')
            pin=digest(pool);publish_json(folder/('joint-pool-'+pin+'.json'),dict(payload=pool,sha256=pin))
            with patch('hybrid_engine.rotation_refresh.records',return_value=(rows,{},0)):
                status=refresh_one(root,ledger)
                self.assertEqual(status['status'],'CAPTURED_REFRESH')
                before={p.name:p.read_bytes() for p in folder.iterdir()}
                self.assertEqual(refresh_one(root,ledger)['status'],'IDLE')
                self.assertEqual(before,{p.name:p.read_bytes() for p in folder.iterdir()})
                self.assertEqual(ledger.read_bytes(),b'unchanged')
                later=entry(9,now-9000,now-7000,now-5000)[0]
                rows.append(later)
                # A newly available result must really be later than the
                # first refresh's clock, otherwise it would invalidate replay.
                later[4]['label_available_utc']=now+1
                with patch('hybrid_engine.rotation_refresh.time.time',return_value=now+2):
                    # Simulated clock must agree with the actual publication
                    # filesystem clock; test candidate separately, not publish.
                    self.assertEqual(len(observations(rows,t,now+2)),4)
                t[4]['label_available_utc']=t[4]['fixture_start_utc']+4000
                t[4]['actual']=[76,76]
                r=review(folder,rows,t[4]['label_available_utc'])
                self.assertEqual(len(r['entries']),1)
                self.assertEqual(comparison(r,t[4]['label_available_utc'])['FULL','total']['n'],1)
    def test_cycle_refresh_lane_no_rewrite(self):
        with TemporaryDirectory() as tmp:
            ledger=Path(tmp)/'ledger';ledger.touch()
            cycle=RotationCycle(tmp,ledger,None,clock=lambda:1000,refresh_enabled=True)
            with patch('hybrid_engine.runtime_reports.RuntimeLedgerReports.read',return_value=dict(status='VERIFIED_LIVE_REPORT',forecasts=[])),patch('hybrid_engine.rotation_refresh.refresh_one',return_value=dict(status='CAPTURED_REFRESH',prior_n=11)):
                self.assertEqual(cycle.tick()['status'],'REFRESHED')
                self.assertEqual(cycle.tick()['status'],'IDLE')
