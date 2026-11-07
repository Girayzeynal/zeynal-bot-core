"""Pilot orchestration and portable recovery tests; positive forecasts are synthetic."""
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import AsyncMock,Mock

from tests import test_faz33 as fixtures
from faz25 import exclusive
from faz33 import ProviderUnavailable
from faz34 import RunJournal,cut_proofs
from faz35 import pilot,validate_config,capsule,restore_pilot
from research_recovery import make_bundle
from prospective_cuts import CutLedger


class PilotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fx=fixtures.CutTests();await self.fx.asyncSetUp()
        self.addCleanup(self.fx.folder.cleanup);self.addCleanup(self.fx.time_patch.stop);self.addCleanup(self.fx.sleep_patch.stop);self.fx._cleanups.clear()
        self.root=self.fx.root;self.ledger=self.fx.ledger;self.journal=self.root/'operations.sqlite'
        self.fx.runner.discover=AsyncMock(return_value=([self.fx.item],[]));self.fx.runner.refresh_history=AsyncMock(return_value=0)

    def config(self):
        return dict(schema_version=1,collection=dict(database=self.ledger.path,research_database=self.fx.store.path,state_directory=str(self.root),legacy_databases={}),
                    storage=dict(mode='LOCAL_ONLY',external_target=None,upload_enabled=False))

    async def execute(self):
        return await pilot(self.ledger.path,lambda:self.fx.runner,journal_path=self.journal,checkpoint_dir=self.root/'checkpoints')

    async def test_not_due_has_no_collection_or_forecast_and_keeps_journal_bytes(self):
        self.fx.clock.now=fixtures.BASE-10
        journal=RunJournal(self.journal);journal.append('previous','FINISHED')
        before=self.journal.read_bytes();result=await self.execute()
        self.assertEqual(result['status'],'WAITING_FOR_CUT');self.assertFalse(result['collection_executed'])
        self.assertEqual(result['new_prospective_cuts'],0);self.assertEqual(self.journal.read_bytes(),before)
        self.assertEqual(result['next_cut_utc'],fixtures.BASE)

    async def test_due_runs_reference_and_shadow_atomically_but_never_counts_synthetic_as_live(self):
        result=await self.execute()
        self.assertTrue(result['collection_executed']);self.assertEqual(result['status'],'TICK_COMPLETE')
        self.assertEqual(result['new_prospective_cuts'],0);self.assertEqual(result['new_cut_proofs'],[])
        self.assertEqual(result['collection']['new_synthetic_cuts'],1)
        proof=result['synthetic_cut_proofs'][0]
        self.assertEqual(proof['shadow_status'],'NO_MODEL_AVAILABLE');self.assertEqual(proof['model_sha'],'a'*40)
        self.assertLess(proof['recorded_utc'],proof['start_utc']);self.assertEqual(len(proof['prediction_sha256']),64)

    async def test_repeat_pilot_preserves_original_cut_and_skips_second_collection(self):
        await self.execute();before=cut_proofs(self.ledger.path);r=await self.execute()
        self.assertFalse(r['collection_executed']);self.assertEqual(r['new_prospective_cuts'],0)
        self.assertEqual(before,cut_proofs(self.ledger.path))

    async def test_missed_cut_is_never_backfilled(self):
        self.fx.clock.now=fixtures.BASE+301;r=await self.execute()
        self.assertFalse(r['collection_executed']);self.assertEqual(r['planning']['tick']['plan'][0]['status'],'MISSED_CUT')
        self.assertEqual(cut_proofs(self.ledger.path),{})

    async def test_process_interruption_is_recovered_even_while_waiting(self):
        self.fx.clock.now=fixtures.BASE-10;RunJournal(self.journal).append('SYNTHETIC_INTERRUPTION','STARTED')
        r=await self.execute();self.assertFalse(r['collection_executed'])
        self.assertEqual(r['state_check']['recovered_run_ids'],['SYNTHETIC_INTERRUPTION'])
        self.assertEqual(cut_proofs(self.ledger.path),{})

    async def test_overlap_returns_busy_without_initializing_runner(self):
        factory=Mock()
        with exclusive(self.ledger.path) as acquired:
            self.assertTrue(acquired)
            r=await pilot(self.ledger.path,factory,journal_path=self.journal,checkpoint_dir=self.root/'checkpoints')
        self.assertEqual(r['status'],'BUSY');self.assertFalse(r['collection_executed']);factory.assert_not_called()

    async def test_sqlite_exclusive_lock_is_failure_not_empty_success(self):
        with self.ledger.connect() as db:
            db.execute('BEGIN EXCLUSIVE');r=await self.execute()
        self.assertEqual(r['status'],'SQLITE_BUSY');self.assertFalse(r['collection_executed'])
        self.assertIsNone(r['new_prospective_cuts'])

    async def test_planning_source_errors_persist_cooldown_across_restarts_without_forecasts(self):
        for index,status in enumerate(('HTTP_403','HTTP_429','TIMEOUT','NETWORK_UNAVAILABLE','NETWORK_OR_PROVIDER_UNAVAILABLE')):
            self.fx.clock.now=fixtures.BASE+index*1000
            self.fx.runner.discover=AsyncMock(side_effect=ProviderUnavailable(status,int(self.fx.clock.now)+300))
            r=await self.execute();self.assertEqual(r['status'],status);self.assertFalse(r['collection_executed'])
            self.assertGreater(r['retry_after_utc'],self.fx.clock.now)
            r=await self.execute();self.assertEqual(r['status'],'PROVIDER_COOLDOWN')
            self.fx.runner.discover.assert_awaited_once();self.assertEqual(cut_proofs(self.ledger.path),{})

    async def test_unauthorized_external_target_or_upload_is_rejected(self):
        self.assertIs(validate_config(self.config())['storage']['upload_enabled'],False)
        for field,value in (('upload_enabled',True),('external_target','https://example.invalid/upload'),('mode','EXTERNAL')):
            c=self.config();c['storage'][field]=value
            with self.assertRaises(ValueError):validate_config(c)

    async def test_config_rejects_relative_and_colliding_paths_and_unrecognized_fields(self):
        c=self.config();c['collection']['database']='relative.sqlite'
        with self.assertRaises(ValueError):validate_config(c)
        c=self.config();c['collection']['research_database']=self.ledger.path
        with self.assertRaises(ValueError):validate_config(c)
        c=self.config();c['unexpected']='not silently ignored'
        with self.assertRaises(ValueError):validate_config(c)

    async def test_capsule_restore_rewrites_paths_and_preserves_mode_and_original_digest(self):
        await self.execute();before=cut_proofs(self.ledger.path)
        result=capsule(self.config(),self.root/'portable.tar.gz','a'*40)
        self.assertFalse(result['external_upload_performed']);self.assertEqual(result['cross_cloud_restore'],'NOT_VERIFIED')
        b=result['bundle'];r=restore_pilot(b['path'],self.root/'new-location',b['sha256'])
        config=validate_config(json.loads(Path(r['config_path']).read_text()));restored=Path(config['collection']['database'])
        self.assertEqual(restored.parent,self.root/'new-location');self.assertEqual(config['storage']['external_target'],None)
        self.assertEqual(cut_proofs(restored),before)
        with self.assertRaises(ValueError):CutLedger(restored,'PROSPECTIVE')

    async def test_incomplete_capsule_is_rejected_before_destination_creation(self):
        b=make_bundle({'history.sqlite':self.fx.store.path},self.root/'incomplete.tar.gz','a'*40)
        with self.assertRaises(ValueError):restore_pilot(b['path'],self.root/'must-not-exist',b['sha256'])
        self.assertFalse((self.root/'must-not-exist').exists())
