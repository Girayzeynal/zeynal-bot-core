"""Temporary SYNTHETIC_TEST store only; no real prediction persistence."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time
from unittest import TestCase
from unittest.mock import patch

from faz42_test_store import SyntheticSnapshotStore
from tests import test_faz42_prospective as original
from tests.test_faz42_history import NOW


class BeginSignal:
    def __init__(self,db,event):self.db=db;self.event=event
    def __enter__(self):self.db.__enter__();return self
    def __exit__(self,*args):
        try:return self.db.__exit__(*args)
        finally:self.db.close()
    def execute(self,sql,*args):
        if sql=='BEGIN IMMEDIATE':self.event.set()
        return self.db.execute(sql,*args)


class SyntheticContentionTests(TestCase):
    setUp=original.ProspectiveTrackTests.setUp
    seal=original.ProspectiveTrackTests.seal
    shot=original.ProspectiveTrackTests.shot
    insert=original.ProspectiveTrackTests.insert

    def _after_contended_begin(self,*,expire=False):
        snapshot=self.shot();at=[NOW];self.store.clock=lambda:at[0]
        original_connect=self.store.connect;writer=original_connect();writer.execute('BEGIN IMMEDIATE');entered=Event()
        try:
            with patch.object(self.store,'connect',side_effect=lambda:BeginSignal(original_connect(),entered)),ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(self.insert,snapshot)
                try:
                    self.assertTrue(entered.wait(5),'writer never reached BEGIN IMMEDIATE')
                    # Hold beyond the old hard-coded 100ms busy budget. This
                    # exercises real SQLite contention after validation ends.
                    time.sleep(.25)
                    if expire:at[0]=NOW+61
                finally:writer.rollback()
                if expire:
                    with self.assertRaisesRegex(ValueError,'PREDICTION_EXPIRED_DURING_RECORDING'):future.result(timeout=5)
                else:self.assertTrue(future.result(timeout=5))
        finally:writer.close()
        with original_connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM faz42_snapshots').fetchone()[0],0 if expire else 1)

    def test_writer_released_after_old_100ms_budget_can_commit_once(self):
        self._after_contended_begin()

    def test_waiting_for_lock_never_bypasses_final_recording_deadline(self):
        self._after_contended_begin(expire=True)

    def test_default_lock_budget_and_explicit_configuration_are_bounded(self):
        with self.store.connect() as db:self.assertEqual(db.execute('PRAGMA busy_timeout').fetchone(),(1500,))
        for value in (0,-1,5001,True,1.5):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'BOUNDED_SYNTHETIC_LOCK_BUDGET'):
                SyntheticSnapshotStore(self.folder.name,busy_timeout_ms=value)
        reopened=SyntheticSnapshotStore(self.folder.name,busy_timeout_ms=25)
        with reopened.connect() as db:self.assertEqual(db.execute('PRAGMA busy_timeout').fetchone(),(25,))
