"""Fail-closed staging tests; no production writes or Telegram requests."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hybrid_engine.stage_archived_model import stage

PACKET = Path(__file__).resolve().parents[1] / 'docs/evidence/nba-phase843-prospective-native-20261113.tar.gz'


class StageArchivedModelTests(unittest.TestCase):
    def test_pinned_optimized_model_stages_and_loads(self):
        with tempfile.TemporaryDirectory() as root:
            report = stage(str(PACKET), root)
            self.assertEqual(report['status'], 'STAGED_RESEARCH_ONLY')
            self.assertGreaterEqual(report['training_games'], 30)
            self.assertFalse(report['calibrated'])
            self.assertFalse(report['production_promotion'])
            self.assertEqual(Path(report['path']).stat().st_mode & 0o777, 0o600)

    def test_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            stage(str(PACKET), root)
            with self.assertRaises(FileExistsError):
                stage(str(PACKET), root)

    def test_rejects_production_volume(self):
        with self.assertRaisesRegex(ValueError, 'RESEARCH_DIRECTORY_OVERLAPS_PRODUCTION_VOLUME'):
            stage(str(PACKET), '/data')

    def test_packet_tamper_rejected_without_output(self):
        with tempfile.TemporaryDirectory() as root:
            fake = Path(root) / 'tampered.tar.gz'
            fake.write_bytes(PACKET.read_bytes()[:100])
            out = Path(root) / 'output'
            out.mkdir()
            with self.assertRaisesRegex(ValueError, 'EVIDENCE_PACKET_SHA256_MISMATCH'):
                stage(str(fake), str(out))
            self.assertEqual(list(out.iterdir()), [])

    def test_rejects_missing_directory(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError, 'RESEARCH_DIRECTORY_NOT_PRESENT'):
                stage(str(PACKET), str(Path(root) / 'missing'))


if __name__ == '__main__':
    unittest.main()
