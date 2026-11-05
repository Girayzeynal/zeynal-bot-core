"""Operational fault injection uses only synthetic ledgers and owned subprocesses."""
import asyncio
from pathlib import Path
import hashlib
import json
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import AsyncMock,patch

from tests import test_faz33 as fixtures
from faz34 import run_once,RunJournal,cut_proofs
from faz25 import exclusive,backup
from prospective_cuts import CutLedger,inspect
from research_recovery import restore_bundle


class OperationsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fx=fixtures.CutTests();await self.fx.asyncSetUp()
        # This fixture's IsolatedAsyncioTestCase runner was never started:
        # delegate its concrete cleanups to OUR active test runner instead.
        self.addCleanup(self.fx.folder.cleanup)
        self.addCleanup(self.fx.time_patch.stop)
        self.addCleanup(self.fx.sleep_patch.stop)
        self.fx._cleanups.clear()
        self.root=self.fx.root;self.ledger=self.fx.ledger;self.journal=self.root/'operations.sqlite'
        self.fx.runner.discover=AsyncMock(return_value=([self.fx.item],[]))
        self.fx.runner.refresh_history=AsyncMock(return_value=0)

    async def once(self,**kwargs):
        return await run_once(self.ledger.path,lambda:self.fx.runner,journal_path=self.journal,checkpoint_dir=self.root/'checkpoints',**kwargs)

    async def test_restart_preserves_packet_sha_and_never_counts_synthetic_as_real(self):
        first=await self.once();before=cut_proofs(self.ledger.path)
        self.assertEqual(first['new_synthetic_cuts'],1);self.assertEqual(first['new_prospective_cuts'],0)
        self.assertEqual(first['checkpoint']['status'],'LOCAL_RESTORE_VERIFIED')
        self.fx.runner.ledger=CutLedger(self.ledger.path,'SYNTHETIC_TEST')
        second=await self.once()
        self.assertEqual(second['new_synthetic_cuts'],0);self.assertEqual(before,cut_proofs(self.ledger.path))
        self.assertEqual(second['tick']['plan'][0]['status'],'ALREADY_RECORDED')
        self.assertEqual(len([e for e in RunJournal(self.journal).events() if e['event']=='FINISHED']),2)

    async def test_shared_lock_stops_overlap_before_runner_initialization(self):
        factory=AsyncMock()
        with exclusive(self.ledger.path) as acquired:
            self.assertTrue(acquired)
            r=await run_once(self.ledger.path,factory,journal_path=self.journal,checkpoint_dir=self.root/'backups')
        self.assertEqual(r['status'],'BUSY');factory.assert_not_called();self.assertFalse(self.journal.exists())

    async def test_abandoned_run_recovers_from_journal_and_existing_cut(self):
        first=await self.once();before=cut_proofs(self.ledger.path)
        RunJournal(self.journal).append('SYNTHETIC_CRASH','STARTED',dict(mode='SYNTHETIC_TEST'))
        r=await self.once()
        self.assertEqual(r['recovered_run_ids'],['SYNTHETIC_CRASH']);self.assertEqual(r['new_synthetic_cuts'],0)
        self.assertEqual(cut_proofs(self.ledger.path),before)
        self.assertIn('INTERRUPTED',[e['event'] for e in RunJournal(self.journal).events()])

    async def test_owned_process_crash_releases_lock_and_rolls_back_uncommitted_rows(self):
        await self.once();before=cut_proofs(self.ledger.path)
        code="import sqlite3,fcntl,os,sys;f=open(sys.argv[1]+'.faz25.lock','a');fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);db=sqlite3.connect(sys.argv[1]);db.execute('BEGIN IMMEDIATE');db.execute(\"INSERT INTO faz33_attempts(status,fixture_id,horizon,observed_utc,details) VALUES ('SYNTHETIC_CRASH',NULL,NULL,1,'{}')\");os._exit(23)"
        p=subprocess.run([sys.executable,'-c',code,self.ledger.path],check=False,timeout=10)
        self.assertEqual(p.returncode,23)
        with exclusive(self.ledger.path) as acquired:self.assertTrue(acquired)
        with self.ledger.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM faz33_attempts WHERE status='SYNTHETIC_CRASH'").fetchone()[0],0)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(),('ok',))
        self.assertEqual(cut_proofs(self.ledger.path),before)
        self.assertEqual((await self.once())['new_synthetic_cuts'],0)

    async def test_early_and_missed_windows_produce_no_packet(self):
        for now in (fixtures.BASE-10,fixtures.BASE+301):
            self.fx.clock.now=now;r=await self.once()
            self.assertEqual(r['new_synthetic_cuts'],0)
        self.assertEqual(inspect(self.ledger.path)['synthetic_cuts'],0)

    async def test_timeout_audits_and_checkpoints_any_committed_state(self):
        self.fx.runner._tick_locked=AsyncMock(side_effect=asyncio.TimeoutError)
        r=await self.once(timeout_seconds=.01)
        self.assertEqual(r['status'],'RUN_TIMEOUT');self.assertEqual(r['new_synthetic_cuts'],0)
        self.assertEqual(r['checkpoint']['status'],'LOCAL_RESTORE_VERIFIED')

    async def test_failed_checkpoint_does_not_claim_external_durability_or_delete_cut(self):
        with patch('faz34.make_bundle',side_effect=TimeoutError('SYNTHETIC_BUSY')):r=await self.once()
        self.assertEqual(r['status'],'CHECKPOINT_FAILED');self.assertEqual(r['new_synthetic_cuts'],1)
        self.assertEqual(r['external_persistence'],'NOT_CONFIGURED');self.assertEqual(r['cross_codex_cloud_restore'],'NOT_VERIFIED')
        self.assertEqual(inspect(self.ledger.path)['synthetic_cuts'],1)
        self.assertEqual((await self.once())['new_synthetic_cuts'],0)

    async def test_dry_run_does_not_write_operations_checkpoint_or_predictions(self):
        before=Path(self.ledger.path).read_bytes();r=await self.once(dry_run=True)
        self.assertEqual(r['status'],'DRY_RUN');self.assertFalse(self.journal.exists());self.assertIsNone(r['checkpoint'])
        self.assertEqual(before,Path(self.ledger.path).read_bytes())

    async def test_wrong_database_paths_are_refused(self):
        r=await run_once(self.ledger.path,lambda:self.fx.runner,journal_path=self.ledger.path,checkpoint_dir=self.root/'checkpoints')
        self.assertEqual(r['status'],'RUN_FAILED');self.assertIsNone(r['new_prospective_cuts'])

    async def test_sqlite_busy_is_bounded_and_not_reported_as_success(self):
        with self.ledger.connect() as db:
            db.execute('BEGIN EXCLUSIVE')
            r=await self.once()
        self.assertEqual(r['status'],'SQLITE_BUSY');self.assertIsNone(r['new_prospective_cuts'])

    async def test_backup_deadline_interrupts_locked_source_and_never_publishes_partial(self):
        destination=self.root/'must-not-exist.sqlite'
        with self.ledger.connect() as db:
            db.execute('BEGIN EXCLUSIVE')
            with self.assertRaises(TimeoutError):backup(self.ledger.path,destination,timeout_seconds=.01)
        self.assertFalse(destination.exists())
        self.assertEqual(inspect(self.ledger.path)['integrity'],'ok')

    async def test_whole_checkpoint_has_one_budget_and_leaves_no_partial_file(self):
        from research_recovery import make_bundle
        destination=self.root/'must-not-publish.tar.gz'
        with self.ledger.connect() as db:
            db.execute('BEGIN EXCLUSIVE')
            with self.assertRaises(TimeoutError):make_bundle({'cuts.sqlite':self.ledger.path},destination,'a'*40,timeout_seconds=.01)
        self.assertFalse(destination.exists())

    async def test_restore_to_new_directory_keeps_original_cut_sha_and_reopens(self):
        r=await self.once();b=r['checkpoint'];destination=self.root/'restored'
        restored=restore_bundle(b['path'],destination,b['sha256'])
        self.assertEqual(restored['status'],'RESTORE_COMPLETE');self.assertFalse(restored['new_codex_cloud_session_tested'])
        self.assertEqual(cut_proofs(destination/'prospective.sqlite'),cut_proofs(self.ledger.path))
        self.assertEqual(inspect(destination/'prospective.sqlite')['synthetic_cuts'],1)
        self.assertEqual((destination/'prospective.sqlite').stat().st_mode&0o777,0o600)
        with self.assertRaises(FileExistsError):restore_bundle(b['path'],destination,b['sha256'])
        with self.assertRaises(ValueError):restore_bundle(b['path'],self.root/'bad-hash','0'*64)
        self.assertFalse((self.root/'bad-hash').exists())

    async def test_journal_tampering_is_detected_even_when_sql_trigger_is_removed(self):
        await self.once()
        with sqlite3.connect(self.journal) as db:
            db.execute('DROP TRIGGER faz34_events_no_UPDATE')
            db.execute("UPDATE faz34_events SET sha256='bad' WHERE seq=1")
        with self.assertRaises(ValueError):RunJournal(self.journal).events()
