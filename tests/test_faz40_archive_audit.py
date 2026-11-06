"""Read-only audits use disposable synthetic databases; no network."""
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

import faz40_archive_audit as audit
from nba_research_store import ResearchStore
from tests import test_faz32 as fixtures


class ReadonlyAuditTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)/'research.sqlite'
        self.store=ResearchStore(self.path,{'19','2'})
        now=int(time.time())
        self.store.ingest(fixtures.summary(900030001,now-86400),now-1000,'ARCHIVED_SOURCE',
                          dict(path='SYNTHETIC_TEST',file_sha256='a'*64))

    def test_readonly_loader_bypasses_mutating_constructor_and_preserves_database(self):
        before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        with patch.object(ResearchStore,'__init__',side_effect=AssertionError('constructor must not run')):
            rows,meta=audit.load_nba(self.path,usage='SYNTHETIC_TEST')
        self.assertEqual(rows[0]['payload']['usage'],'SYNTHETIC_TEST')
        self.assertEqual(meta['sha256'],before)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),before)

    def test_audit_of_insufficient_synthetic_archive_does_not_emit_metrics(self):
        result=audit.run(self.path,usage='SYNTHETIC_TEST')
        self.assertEqual(result['prospective_records_created'],0)
        for league,reports in result['reports'].items():
            for report in reports.values():self.assertIsNone(report['metrics'])
        self.assertFalse(result['production_coefficients_changed'])

    def test_active_wal_or_corrupt_database_is_rejected_without_mutation(self):
        sidecar=Path(str(self.path)+'-wal');sidecar.write_bytes(b'synthetic-active-wal')
        with self.assertRaisesRegex(ValueError,'STATIC_RESEARCH'):audit.load_nba(self.path)
        sidecar.unlink()
        invalid=Path(self.folder.name)/'invalid.sqlite';invalid.write_bytes(b'not SQLite')
        with self.assertRaises(sqlite3.Error):audit.load_nba(invalid)

    def test_corrupt_euro_snapshot_cannot_be_used_as_verified_period_history(self):
        source=Path(__file__).resolve().parents[1]/'docs/evidence/euroleague-eurocup-audit-20261104.json'
        raw=json.loads(source.read_text());raw['results'][0]['estimates'][0]['sha256']='0'*64
        path=Path(self.folder.name)/'corrupt-source.json';path.write_text(json.dumps(raw))
        with self.assertRaises(ValueError):audit.load_euro(path,usage='SYNTHETIC_TEST')

    def test_wal_header_without_sidecars_is_refused_before_creating_auxiliary_files(self):
        db=sqlite3.connect(self.path);db.execute('PRAGMA journal_mode=WAL');db.close()
        self.assertEqual(self.path.read_bytes()[18:20],b'\x02\x02')
        before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError,'STATIC_RESEARCH'):audit.load_nba(self.path)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),before)
        self.assertFalse(Path(str(self.path)+'-wal').exists())
        self.assertFalse(Path(str(self.path)+'-shm').exists())


if __name__=='__main__':unittest.main()
