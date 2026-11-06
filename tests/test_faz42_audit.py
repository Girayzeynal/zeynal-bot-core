from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from faz42_audit import run,cached_players
from faz40_archive_audit import file_sha
from nba_research_store import ResearchStore
from tests.test_faz32 import summary
from tests.test_faz42_history import NOW


class AuditTests(TestCase):
    def test_readonly_audit_counts_real_structure_without_inventing_permission_or_predictions(self):
        with TemporaryDirectory() as folder,patch('time.time',return_value=NOW) as clock:
            path=Path(folder)/'research.sqlite';store=ResearchStore(path,{'19','2'})
            store.ingest(summary(401909901,NOW-86400),NOW-1000,'ARCHIVED_SOURCE',dict(path='SYNTHETIC_TEST',file_sha256='a'*64))
            before=file_sha(path)
            with patch('faz42_audit.time.sleep',side_effect=lambda n:setattr(clock,'return_value',NOW+1)):
                r=run(path,train_end_utc=NOW-3*86400,validation_end_utc=NOW-2*86400)
            self.assertEqual(file_sha(path),before)
            self.assertEqual(r['inventory']['partitions']['NBA:2027']['unique_games'],1)
            self.assertEqual(r['inventory']['partitions']['NBA:2027']['usable_permission_games'],0)
            self.assertEqual(r['prospective_records_created'],0)
            self.assertIsNone(r['evaluation']['NBA']['cohorts']['TEST']['metrics'])

    def test_missing_cached_sources_cannot_be_silently_counted_as_players(self):
        with TemporaryDirectory() as folder,self.assertRaises(FileNotFoundError):cached_players(folder)
