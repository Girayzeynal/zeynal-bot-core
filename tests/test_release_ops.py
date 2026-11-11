"""Synthetic WAL/backups, local config safety and historical-mode boundaries."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import io
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import time
from unittest import TestCase
from unittest.mock import patch

from release_acceptance import historical_preview,main as acceptance_main
from release_ops import checkpoint,inspect_config,main
from season_archive_inventory import archive_catalog
from tests.test_universal_analysis import games
from tests.test_season_archive_audit import NOW


class ReleaseOperationsTests(TestCase):
    def test_config_requires_existing_volume_and_preserves_local_bytes(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/'fly.local.toml'
            raw='app="zeynal-bot-core"\n[[mounts]]\nsource="existing-data"\ndestination="/data"\n'
            p.write_text(raw);self.assertEqual(inspect_config(p)['mounts'][0]['source'],'existing-data')
            self.assertEqual(p.read_text(),raw)
            p.write_text('app="zeynal-bot-core"\n')
            with self.assertRaisesRegex(ValueError,'VOLUME_MOUNT'):inspect_config(p)
            p.write_text(raw+'[processes]\napp="python dynamic_scheduler.py & python main.py"\n')
            with self.assertRaisesRegex(ValueError,'MULTIPLE_POLLING'):inspect_config(p)

    def test_wal_active_writer_backup_is_consistent_and_hash_manifest_matches(self):
        with TemporaryDirectory() as tmp:
            src=Path(tmp)/'source.sqlite'
            with sqlite3.connect(src) as writer:
                writer.execute('PRAGMA journal_mode=WAL');writer.execute('CREATE TABLE predictions(x)')
                writer.execute('INSERT INTO predictions VALUES(1)');writer.commit()
                writer.execute('BEGIN IMMEDIATE');writer.execute('INSERT INTO predictions VALUES(2)')
                r=checkpoint(src,Path(tmp)/'backups')
                self.assertEqual(r['counts']['predictions'],1)
                saved=Path(r['database']);m=json.loads(Path(r['manifest']).read_text())
                self.assertEqual(hashlib.sha256(saved.read_bytes()).hexdigest(),m['sha256'])
                with sqlite3.connect(saved) as backup:self.assertEqual(backup.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                writer.rollback()

    def test_total_timeout_cancels_backup_and_never_publishes_manifest(self):
        with TemporaryDirectory() as tmp:
            src=Path(tmp)/'source.sqlite';writer=sqlite3.connect(src)
            writer.execute('CREATE TABLE predictions(x)');writer.commit();writer.execute('BEGIN EXCLUSIVE')
            began=time.monotonic()
            try:
                with self.assertRaisesRegex(TimeoutError,'TOTAL_TIMEOUT'):checkpoint(src,Path(tmp)/'backup',timeout=.04)
            finally:writer.rollback();writer.close()
            self.assertLess(time.monotonic()-began,2)
            self.assertEqual(list((Path(tmp)/'backup').iterdir()),[])

    def test_checkpoint_dry_run_never_opens_production_database(self):
        with patch('release_ops.sqlite3.connect',side_effect=AssertionError('PRODUCTION_DB_MUST_STAY_CLOSED')):
            with redirect_stdout(io.StringIO()):self.assertEqual(main(['checkpoint']),0)
        with patch('release_acceptance.run_acceptance',side_effect=AssertionError('NO_NETWORK')):
            with redirect_stdout(io.StringIO()):self.assertEqual(acceptance_main(['--execute']),2)

    def test_single_polling_entrypoint_and_no_secret_or_local_db_image_context(self):
        root=Path(__file__).resolve().parents[1]
        entry=(root/'entrypoint.sh').read_text()
        self.assertIn('exec python -u main.py',entry);self.assertNotIn('python dynamic_scheduler.py',entry)
        ignore=(root/'.dockerignore').read_text()
        for pattern in ('.env','**/*.sqlite','fly.local.toml','.git'):self.assertIn(pattern,ignore)


class HistoricalReleasePreviewTests(TestCase):
    def test_started_example_is_backtest_not_a_live_prediction(self):
        with patch('time.time',return_value=NOW):
            b=archive_catalog(games(),provider='EUROLEAGUE_LIVE',observed_at_utc=NOW-2,ingested_at_utc=NOW-1)
        target=next(g for g in b['payload']['fixtures'] if not g['completed'])
        with patch('release_acceptance.datetime') as clock:
            clock.now.return_value=datetime.fromtimestamp(NOW+5*3600,timezone.utc)
            r=historical_preview(b,b['sha256'],target['canonical_id'])
        self.assertEqual(r['record_type'],'BACKTEST_SIMULATION');self.assertFalse(r['live_prediction_created'])
        self.assertIsNone(r['actual']);self.assertGreater(r['generated_at_utc'],r['fixture_start_utc'])

    def test_no_historical_preview_of_future_target_or_post_cutoff_source(self):
        with patch('time.time',return_value=NOW):
            b=archive_catalog(games(),provider='EUROLEAGUE_LIVE',observed_at_utc=NOW-2,ingested_at_utc=NOW-1)
        target=next(g for g in b['payload']['fixtures'] if not g['completed'])
        with patch('release_acceptance.datetime') as clock:
            clock.now.return_value=datetime.fromtimestamp(NOW,timezone.utc)
            with self.assertRaisesRegex(ValueError,'STARTED_TARGET'):historical_preview(b,b['sha256'],target['canonical_id'])
        with patch('time.time',return_value=NOW+6*3600):
            late=archive_catalog(games(),provider='EUROLEAGUE_LIVE',observed_at_utc=NOW+5*3600,ingested_at_utc=NOW+5*3600)
        with patch('release_acceptance.datetime') as clock:
            clock.now.return_value=datetime.fromtimestamp(NOW+6*3600,timezone.utc)
            with self.assertRaisesRegex(ValueError,'PRE_TIPOFF_SOURCE'):historical_preview(late,late['sha256'],target['canonical_id'])
