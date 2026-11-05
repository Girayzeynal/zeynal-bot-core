"""Clock fault injection and pinned recovery; positive forecasts remain synthetic."""
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock,patch

from faz25 import exclusive
from faz34 import cut_proofs
from faz35 import capsule
from faz36 import commit_stage,StateConflict,head
from faz37 import ClockGuard,ClockDiscontinuity,GuardedRunner,pinned_lineage,restore_state,recovery_child
from faz33 import ProviderUnavailable
from prediction_inputs import digest
from research_recovery import make_bundle
from tests import test_faz33 as fixtures


class ClockTests(unittest.TestCase):
    def setUp(self):self.wall=10000.;self.mono=200.;self.guard=ClockGuard(wall=lambda:self.wall,monotonic=lambda:self.mono)
    def test_normal_elapsed_clock_is_accepted(self):
        self.wall+=10;self.mono+=10;self.assertEqual(self.guard.check(),10010)
        self.assertFalse(self.guard.evidence()['initial_utc_independently_attested'])
    def test_forward_jump_to_apparently_due_time_is_rejected(self):
        self.wall+=3600
        with self.assertRaises(ClockDiscontinuity):self.guard.check()
    def test_backward_jump_and_monotonic_reset_are_rejected(self):
        self.wall-=.1
        with self.assertRaises(ClockDiscontinuity):self.guard.check()
        self.wall=10000;self.mono-=1
        with self.assertRaises(ClockDiscontinuity):self.guard.check()
    def test_nonfinite_initial_time_is_rejected(self):
        for invalid in (float('nan'),float('inf'),-1):
            with self.assertRaises(ClockDiscontinuity):ClockGuard(wall=lambda:invalid)


class PinnedManifestTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup);self.root=Path(self.folder.name);self.state=self.root/'state'
    def bundle(self,name,rows):
        path=self.root/(name+'.sqlite')
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE predictions (league TEXT,fixture_id TEXT,value INTEGER,PRIMARY KEY(league,fixture_id))')
            db.executemany('INSERT INTO predictions VALUES (?,?,?)',[('SYNTHETIC',k,v) for k,v in rows])
        return make_bundle({'synthetic.sqlite':str(path)},self.root/(name+'.tar.gz'),'a'*40)
    def generations(self):
        a=self.bundle('a',[('one',1)]);first=commit_stage(self.state,a['path'],a['sha256'],None)['manifest']
        b=self.bundle('b',[('one',1),('two',2)]);second=commit_stage(self.state,b['path'],b['sha256'],first['sha256'])['manifest']
        return first,second
    def test_entire_parent_lineage_and_monotonic_generation_are_verified(self):
        _,latest=self.generations();r=pinned_lineage(self.state,latest['sha256']);self.assertEqual(r['verified_generations'],2)
    def test_old_valid_head_is_refused_against_trusted_new_head(self):
        old,latest=self.generations();(self.state/'HEAD.json').write_text(json.dumps(old))
        with self.assertRaises(StateConflict):restore_state(self.state,self.root/'must-not-restore',latest['sha256'])
        self.assertFalse((self.root/'must-not-restore').exists())
    def test_missing_or_corrupt_parent_is_refused(self):
        old,latest=self.generations();p=self.state/'manifests'/(old['sha256']+'.json');p.write_text('{}')
        with self.assertRaises((ValueError,KeyError)):pinned_lineage(self.state,latest['sha256'])
    def test_rehashed_nonconsecutive_generation_is_refused(self):
        _,latest=self.generations();latest['payload']['generation']+=1;latest['sha256']=digest(latest['payload'])
        (self.state/'HEAD.json').write_text(json.dumps(latest));(self.state/'manifests'/(latest['sha256']+'.json')).write_text(json.dumps(latest))
        with self.assertRaises(StateConflict):pinned_lineage(self.state,latest['sha256'])


class CaptureAndRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fx=fixtures.CutTests();await self.fx.asyncSetUp()
        self.addCleanup(self.fx.folder.cleanup);self.addCleanup(self.fx.time_patch.stop);self.addCleanup(self.fx.sleep_patch.stop);self.fx._cleanups.clear()
        self.guard=ClockGuard(wall=lambda:self.fx.clock.now,monotonic=lambda:self.fx.clock.now-fixtures.BASE)
        self.fx.ledger.clock_check=self.guard.check
        self.config=dict(schema_version=1,collection=dict(database=self.fx.ledger.path,research_database=self.fx.store.path,state_directory=str(self.fx.root),legacy_databases={}),storage=dict(mode='LOCAL_ONLY',external_target=None,upload_enabled=False))
    async def test_clock_guard_rejects_before_final_sql_insert_even_after_validation(self):
        await self.fx.capture();packet=self.fx.packet();before=cut_proofs(self.fx.ledger.path)
        calls=0
        def unstable():
            nonlocal calls
            calls+=1
            if calls==2:raise ClockDiscontinuity('SYNTHETIC_CLOCK_JUMP')
            return int(self.fx.clock.now)
        self.fx.ledger.clock_check=unstable
        # Reuse the validated packet in a NEW isolated synthetic ledger.
        other=self.fx.root/'empty.sqlite'
        from prospective_cuts import CutLedger
        ledger=CutLedger(other,'SYNTHETIC_TEST',clock_check=unstable)
        with self.assertRaises(ClockDiscontinuity):ledger.insert(packet)
        with ledger.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM faz33_cuts').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM faz33_fixtures').fetchone()[0],0)
        self.assertEqual(before,cut_proofs(self.fx.ledger.path))
    async def test_guarded_provider_fetch_refuses_mid_request_clock_jump(self):
        runner=GuardedRunner(self.fx.ledger,self.fx.store,self.fx.api,model_sha='a'*40,clock_guard=self.guard)
        self.guard.monotonic=lambda:0
        async def response(url):self.fx.clock.now+=3600;return {'events':[]}
        self.fx.api._get_json.side_effect=response
        with self.assertRaises(ClockDiscontinuity):await runner.fetch('SYNTHETIC_TEST')
        self.assertEqual(cut_proofs(self.fx.ledger.path),{})
    async def test_provider_403_is_preserved_but_clock_jump_during_429_is_primary_failure(self):
        runner=GuardedRunner(self.fx.ledger,self.fx.store,self.fx.api,model_sha='a'*40,clock_guard=self.guard)
        self.fx.api.last_http_status=403;self.fx.api._get_json.return_value=None
        with self.assertRaises(ProviderUnavailable) as raised:await runner.fetch('SYNTHETIC_TEST')
        self.assertEqual(raised.exception.status,'HTTP_403')
        self.guard.monotonic=lambda:0;self.fx.api.last_http_status=429
        async def response(url):self.fx.clock.now+=3600;return None
        self.fx.api._get_json.side_effect=response
        with self.assertRaises(ClockDiscontinuity):await runner.fetch('SYNTHETIC_TEST')
    async def test_pinned_restore_preserves_original_forecast_and_does_not_claim_cloud_migration(self):
        await self.fx.capture();before=cut_proofs(self.fx.ledger.path)
        b=capsule(self.config,self.fx.root/'source.tar.gz','a'*40)['bundle'];state=self.fx.root/'state'
        latest=commit_stage(state,b['path'],b['sha256'],None)['manifest']
        r=restore_state(state,self.fx.root/'restored',latest['sha256'])
        self.assertEqual(cut_proofs(self.fx.root/'restored/prospective.sqlite'),before)
        self.assertFalse(r['new_cloud_runtime_tested']);self.assertFalse(r['external_committed'])
        self.assertTrue((self.fx.root/'restored/FAZ37_VERIFIED_STATE.json').exists())
        r=recovery_child(state,latest['sha256']);self.assertTrue(r['new_source_directory']);self.assertFalse(r['new_cloud_runtime_tested'])
    async def test_restore_refuses_concurrent_publisher_and_does_not_create_destination(self):
        await self.fx.capture();b=capsule(self.config,self.fx.root/'source.tar.gz','a'*40)['bundle'];state=self.fx.root/'state'
        latest=commit_stage(state,b['path'],b['sha256'],None)['manifest']
        with exclusive(state/'HEAD.json') as acquired:
            self.assertTrue(acquired)
            with self.assertRaises(BlockingIOError):restore_state(state,self.fx.root/'must-not-create',latest['sha256'])
        self.assertFalse((self.fx.root/'must-not-create').exists())
