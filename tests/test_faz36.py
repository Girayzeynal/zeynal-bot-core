"""Local protocol simulation and synthetic collector races; no distributed claims."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock,patch

from faz25 import exclusive
from faz34 import run_once,cut_proofs
from faz35 import pilot
from faz36 import commit_stage,head,StateConflict,scheduler_plan
from research_recovery import make_bundle
from prediction_inputs import digest
from tests import test_faz33 as fixtures


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup);self.root=Path(self.folder.name)

    def bundle(self,name,rows):
        # This is generic synthetic SQLite protocol data, not NBA forecasts.
        path=self.root/(name+'.sqlite')
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE predictions (league TEXT,fixture_id TEXT,value INTEGER,PRIMARY KEY(league,fixture_id))')
            db.executemany('INSERT INTO predictions VALUES (?,?,?)',[('SYNTHETIC',k,v) for k,v in rows])
        return make_bundle({'synthetic.sqlite':str(path)},self.root/(name+'.tar.gz'),'a'*40)

    def stage(self,b,parent=None):return commit_stage(self.root/'state',b['path'],b['sha256'],parent)

    def test_same_capsule_is_idempotent_and_never_claims_external_commit(self):
        b=self.bundle('a',[('one',1)]);first=self.stage(b);again=self.stage(b)
        self.assertEqual(again['status'],'ALREADY_STAGED');self.assertEqual(first['manifest'],again['manifest'])
        p=first['manifest']['payload'];self.assertEqual(p['generation'],1);self.assertFalse(p['external_committed'])
        self.assertEqual(p['scope'],'LOCAL_STAGING_ONLY')

    def test_new_generation_extends_history_and_stale_writer_is_rejected(self):
        a=self.bundle('a',[('one',1)]);first=self.stage(a)['manifest']
        b=self.bundle('b',[('one',1),('two',2)])
        with self.assertRaises(StateConflict):self.stage(b,None)
        second=self.stage(b,first['sha256'])['manifest']
        self.assertEqual(second['payload']['generation'],2);self.assertEqual(second['payload']['parent_sha256'],first['sha256'])
        self.assertTrue((self.root/'state/manifests'/(first['sha256']+'.json')).exists())

    def test_rollback_or_rehashed_changed_prediction_cannot_replace_latest_history(self):
        first=self.stage(self.bundle('a',[('one',1),('two',2)]))['manifest']
        for name,rows in [('missing',[('one',1)]),('changed',[('one',9),('two',2)])]:
            with self.assertRaises(StateConflict):self.stage(self.bundle(name,rows),first['sha256'])
        self.assertEqual(head(self.root/'state'),first)

    def test_corrupt_bundle_preserves_head_and_never_stages(self):
        first=self.stage(self.bundle('a',[('one',1)]))['manifest'];bad=self.root/'corrupt.tar.gz';bad.write_bytes(b'not a backup')
        with self.assertRaises(ValueError):commit_stage(self.root/'state',bad,'0'*64,first['sha256'])
        self.assertEqual(head(self.root/'state'),first)

    def test_corrupt_sqlite_with_new_container_hash_is_rejected(self):
        import io,tarfile
        raw=b'not a sqlite database';manifest=dict(schema_version=1,source_version='a'*40,files={'synthetic.sqlite':hashlib.sha256(raw).hexdigest()})
        path=self.root/'corrupt-sqlite.tar.gz'
        with tarfile.open(path,'w:gz') as tar:
            for name,value in [('manifest.json',json.dumps(manifest).encode()),('synthetic.sqlite',raw)]:
                m=tarfile.TarInfo(name);m.size=len(value);tar.addfile(m,io.BytesIO(value))
        with self.assertRaises(sqlite3.DatabaseError):commit_stage(self.root/'state',path,hashlib.sha256(path.read_bytes()).hexdigest(),None)
        self.assertFalse((self.root/'state/HEAD.json').exists())

    def test_tampered_head_is_rejected(self):
        self.stage(self.bundle('a',[('one',1)]));p=self.root/'state/HEAD.json';value=json.loads(p.read_text());value['payload']['generation']+=1;p.write_text(json.dumps(value))
        with self.assertRaises(ValueError):head(self.root/'state')

    def test_stored_capsule_corruption_is_not_reported_as_a_healthy_head(self):
        r=self.stage(self.bundle('a',[('one',1)]));path=self.root/'state'/r['manifest']['payload']['bundle_key'];path.write_bytes(b'broken')
        with self.assertRaises(ValueError):head(self.root/'state')

    def test_rehashed_metadata_cannot_turn_bundle_key_into_path_traversal(self):
        r=self.stage(self.bundle('a',[('one',1)]))['manifest'];r['payload']['bundle_sha256']='../../outside';r['sha256']=digest(r['payload'])
        (self.root/'state/HEAD.json').write_text(json.dumps(r))
        with self.assertRaises(ValueError):head(self.root/'state')

    def test_two_publisher_processes_cannot_both_commit_different_initial_states(self):
        bundles=[self.bundle('a',[('a',1)]),self.bundle('b',[('b',2)])];state=self.root/'state'
        code="import sys;from faz36 import commit_stage;\ntry:\n commit_stage(sys.argv[1],sys.argv[2],sys.argv[3],None);print('STAGED')\nexcept (ValueError,BlockingIOError):\n print('CONFLICT')\n"
        processes=[subprocess.Popen([sys.executable,'-c',code,str(state),b['path'],b['sha256']],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for b in bundles]
        results=[]
        for process in processes:
            out,err=process.communicate(timeout=15);self.assertEqual(process.returncode,0,err);results.append(out.strip())
        self.assertEqual(sorted(results),['CONFLICT','STAGED']);self.assertEqual(head(state)['payload']['generation'],1)

    def test_scheduler_readiness_never_turns_local_protocol_into_timing_guarantee(self):
        for kind in ('local_timer','github_actions'):
            p=scheduler_plan(kind);self.assertFalse(p['enabled']);self.assertFalse(p['punctuality_guaranteed']);self.assertFalse(p['ready_for_unattended_collection'])
        self.assertTrue(any('ephemeral' in r for r in scheduler_plan('github_actions')['risks']))


class CollectorRaceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fx=fixtures.CutTests();await self.fx.asyncSetUp()
        self.addCleanup(self.fx.folder.cleanup);self.addCleanup(self.fx.time_patch.stop);self.addCleanup(self.fx.sleep_patch.stop);self.fx._cleanups.clear()
        self.runner=self.fx.runner;self.runner.discover=AsyncMock(return_value=([self.fx.item],[]));self.runner.refresh_history=AsyncMock(return_value=0)
        self.journal=self.fx.root/'operations.sqlite'

    async def run_pilot(self):return await pilot(self.fx.ledger.path,lambda:self.runner,journal_path=self.journal,checkpoint_dir=self.fx.root/'checkpoints')

    async def test_capture_window_expiring_after_plan_is_not_backfilled(self):
        calls=0
        async def schedule():
            nonlocal calls
            calls+=1
            if calls==2:self.fx.clock.now=fixtures.BASE+301
            return [self.fx.item],[]
        self.runner.discover=AsyncMock(side_effect=schedule)
        r=await self.run_pilot();self.assertTrue(r['collection_executed'])
        self.assertEqual(r['collection']['new_synthetic_cuts'],0);self.assertEqual(cut_proofs(self.fx.ledger.path),{})
        self.assertEqual(r['collection']['tick']['plan'][0]['status'],'MISSED_CUT')

    async def test_other_worker_committing_between_plan_and_collection_does_not_duplicate(self):
        captured=[]
        async def race(*args,**kwargs):
            if not kwargs.get('dry_run'):
                with exclusive(self.fx.ledger.path) as acquired:
                    self.assertTrue(acquired);await self.runner.capture(self.fx.item,'T24H',refresh=False)
                    captured.append(cut_proofs(self.fx.ledger.path))
            return await run_once(*args,**kwargs)
        with patch('faz35.run_once',side_effect=race):r=await self.run_pilot()
        self.assertEqual(r['collection']['new_synthetic_cuts'],0);self.assertEqual(cut_proofs(self.fx.ledger.path),captured[0])
        self.assertEqual(len(captured[0]),1)

    async def test_missing_provider_history_is_an_explicit_rejection_with_no_partial_forecast(self):
        from faz33 import Runner
        self.runner.refresh_history=Runner.refresh_history.__get__(self.runner);self.fx.api._get_json.return_value={}
        r=await self.run_pilot();self.assertEqual(r['new_prospective_cuts'],0)
        self.assertEqual(r['collection']['tick']['actions'][0]['status'],'HISTORY_SEASON_SCOPE_UNVERIFIED')
        self.assertEqual(cut_proofs(self.fx.ledger.path),{})
