"""Isolated scheduler fault, duplicate and backup tests; no production services."""
import asyncio
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, Mock
from faz25 import Poller,validate_schedule,exclusive,backup


def payload():
    d=json.loads((Path(__file__).parent/'fixtures/espn-final-401909911.json').read_text())['event']
    stamp=datetime.fromtimestamp(int(time.time())+3600,timezone.utc).isoformat()
    d['date']=stamp;d['competitions'][0]['date']=stamp
    d['status']={'type':{'state':'pre','completed':False}}
    d['competitions'][0]['status']=deepcopy(d['status'])
    return {'events':[d]}


class Faz25Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Android/UserLAnd /tmp may race directory removal after SQLite file operations.
        # Use the same home filesystem as the checked-out repository for test isolation.
        self.folder=tempfile.TemporaryDirectory(prefix='faz25-test-', dir=Path.home())
        self.addCleanup(self._cleanup_test_folder)
        self.db=str(Path(self.folder.name)/'ledger.sqlite');self.poller=Poller(self.db,timeout=.1)
        self.schedule=AsyncMock(return_value=[payload()]);self.collect=AsyncMock(return_value={'inserted':True})
        self.reconcile=AsyncMock(return_value={'status':'awaiting_final'})

    def _cleanup_test_folder(self):
        """Remove test artifacts; disclose Android's empty-directory rmdir bug.

        A verified empty directory may be left behind if the filesystem refuses
        rmdir with ENOTEMPTY. Never ignore remaining files or other errors.
        """
        import os
        import warnings

        root = Path(self.folder.name)
        for attempt in range(8):
            try:
                self.folder.cleanup()
                return
            except OSError as exc:
                if exc.errno != 39:
                    raise
                # os.scandir, unlike Path.rglob, also sees hidden entries.
                if not root.exists():
                    return
                with os.scandir(root) as entries:
                    remaining = [entry.name for entry in entries]
                if remaining:
                    if attempt == 7:
                        raise RuntimeError(
                            "FAZ25 test artifacts remain: " + repr(remaining[:20])
                        ) from exc
                elif attempt == 7:
                    warnings.warn(
                        "FAZ25_ANDROID_EMPTY_DIRECTORY_RMDIR_FAILED: "
                        + str(root) + " (directory contains no files)",
                        RuntimeWarning,
                        stacklevel=2,
                    )
                    return
                time.sleep(0.05 * (attempt + 1))

    async def tick(self):
        return await self.poller.tick(schedule=self.schedule,collect=self.collect,reconcile=self.reconcile)

    async def test_success_and_persistent_cooldown(self):
        result=await self.tick();self.assertEqual(result['status'],'polled');self.collect.assert_awaited_once()
        restarted=Poller(self.db)
        result=await restarted.tick(schedule=self.schedule,collect=self.collect,reconcile=self.reconcile)
        self.assertEqual(result['status'],'schedule_cooldown');self.collect.assert_awaited_once()

    async def test_connection_failure_sets_retry_without_prediction(self):
        self.schedule.side_effect=ConnectionError('synthetic disconnect')
        self.assertEqual((await self.tick())['status'],'schedule_unavailable')
        self.assertFalse(self.poller.due('schedule'));self.collect.assert_not_awaited()
        with self.poller.ledger._connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM predictions').fetchone()[0],0)

    async def test_access_block_is_not_empty_success(self):
        self.schedule.return_value=[None]
        self.assertEqual((await self.tick())['status'],'schedule_unavailable')
        self.collect.assert_not_awaited()

    async def test_timeout_is_bounded_and_retriable(self):
        async def stalled(): await asyncio.sleep(10)
        self.schedule.side_effect=stalled
        result=await self.tick()
        self.assertEqual(result['status'],'schedule_unavailable')
        self.assertEqual(result['error_type'],'TimeoutError')

    async def test_lock_prevents_concurrent_runner(self):
        with exclusive(self.db) as acquired:
            self.assertTrue(acquired);self.assertEqual((await self.tick())['status'],'busy')
        self.schedule.assert_not_awaited()

    async def test_recorded_prediction_never_recollected(self):
        row=validate_schedule([payload()])[0]
        with self.poller.ledger._connect() as db:
            db.execute('INSERT INTO predictions VALUES (?,?,?,?,?,?,?)',('NBA',row['provider_fixture_id'],1,100,90,None,'FINAL_WITH_OT'))
        await self.tick();self.collect.assert_not_awaited()

    async def test_final_reconciliation_runs_even_when_schedule_fails(self):
        with self.poller.ledger._connect() as db:
            db.execute('CREATE TABLE faz24_stages (fixture_id TEXT)')
            db.execute("INSERT INTO faz24_stages VALUES ('final-target')")
        self.schedule.side_effect=RuntimeError('blocked')
        result=await self.tick();self.reconcile.assert_awaited_once_with('final-target')
        self.assertEqual(result['actions'][0]['status'],'awaiting_final')

    async def test_late_poll_does_not_generate_prediction(self):
        board=payload();stamp=datetime.fromtimestamp(int(time.time())-1,timezone.utc).isoformat()
        board['events'][0]['date']=stamp;board['events'][0]['competitions'][0]['date']=stamp
        self.schedule.return_value=[board];await self.tick();self.collect.assert_not_awaited()

    async def test_failed_baseline_or_collection_has_backoff(self):
        self.collect.side_effect=ValueError('source stale')
        result=await self.tick();self.assertEqual(result['actions'][0]['status'],'retry_pending')
        with self.poller.ledger._connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM predictions').fetchone()[0],0)

    async def test_duplicate_dates_deduplicated_conflicts_rejected(self):
        a=payload();self.assertEqual(len(validate_schedule([a,deepcopy(a)])),1)
        b=deepcopy(a);b['events'][0]['id']='different-id'
        b['events'][0]['competitions'][0]['id']='different-id'
        with self.assertRaises(ValueError):validate_schedule([a,b])

    async def test_backup_is_consistent_owner_only_no_clobber(self):
        path=Path(self.folder.name)/'backup.sqlite'
        result=backup(self.db,path);self.assertFalse(result['external_uploaded'])
        self.assertEqual(path.stat().st_mode & 0o777,0o600)
        with sqlite3.connect(path) as db:self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(),('ok',))
        before=path.read_bytes()
        with self.assertRaises(FileExistsError):backup(self.db,path)
        self.assertEqual(before,path.read_bytes())

    async def test_backup_leaves_no_staging_files(self):
        destination = Path(self.folder.name) / "clean-backup.sqlite"
        backup(self.db, destination)
        self.assertTrue(destination.is_file())
        self.assertEqual(
            list(Path(self.folder.name).glob(".faz25-backup-*")), [])

    async def test_backup_no_clobber_cleans_staging_file(self):
        destination = Path(self.folder.name) / "existing.sqlite"
        destination.write_bytes(b"original")
        with self.assertRaises(FileExistsError):
            backup(self.db, destination)
        self.assertEqual(destination.read_bytes(), b"original")
        self.assertEqual(
            list(Path(self.folder.name).glob(".faz25-backup-*")), [])

    async def test_backup_invalid_timeout_does_not_create_file(self):
        destination = Path(self.folder.name) / "invalid.sqlite"
        with self.assertRaises(ValueError):
            backup(self.db, destination, timeout_seconds=0)
        self.assertFalse(destination.exists())
        self.assertEqual(
            list(Path(self.folder.name).glob(".faz25-backup-*")), [])

    async def test_crash_after_atomic_commit_does_not_recollect(self):
        row=validate_schedule([payload()])[0]
        async def committed_then_disconnected(fixture):
            with self.poller.ledger._connect() as db:
                db.execute('INSERT INTO predictions VALUES (?,?,?,?,?,?,?)',('NBA',fixture['provider_fixture_id'],1,100,90,None,'FINAL_WITH_OT'))
            raise ConnectionError('reply lost after commit')
        self.collect.side_effect=committed_then_disconnected
        await self.tick()
        with self.poller.ledger._connect() as db:db.execute('UPDATE faz25_attempts SET next_utc=0')
        await self.tick();self.collect.assert_awaited_once()

    async def test_pending_results_do_not_starve_other_fixtures(self):
        with self.poller.ledger._connect() as db:
            db.execute('CREATE TABLE faz24_stages (fixture_id TEXT)')
            db.executemany('INSERT INTO faz24_stages VALUES (?)',[('a',),('b',),('c',)])
        await self.tick();await self.tick()
        self.assertIn('c',[call.args[0] for call in self.reconcile.await_args_list])

    async def test_history_refresh_missing_finals_or_pace_never_publishes_baseline(self):
        from faz25 import refresh_baseline,BaselineUnavailable
        history=type('History',(),{})();adapter=type('Adapter',(),{})()
        store=type('Store',(),{})();store.put=Mock()
        history.fetch_verified_games=AsyncMock(return_value=None)
        adapter.fetch_pace_evidence=AsyncMock(return_value=None)
        with self.assertRaises(BaselineUnavailable):
            await refresh_baseline(adapter,history,store,'BOS','2')
        history.fetch_verified_games.return_value=[{'home_team_id':'2','away_team_id':'15'}]*6
        with self.assertRaises(BaselineUnavailable):
            await refresh_baseline(adapter,history,store,'BOS','2')
        store.put.assert_not_called()

    async def test_missing_source_field_is_retryable_without_prediction(self):
        self.collect.side_effect=KeyError('status')
        result=await self.tick()
        self.assertEqual(result['actions'][0]['error_type'],'KeyError')
        self.assertEqual(result['actions'][0]['status'],'retry_pending')
        with self.poller.ledger._connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM predictions').fetchone()[0],0)
