"""Prepared-model preflight must fail closed and avoid production storage."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hybrid_engine.prepared_preflight import check


class PreparedPreflightTests(unittest.TestCase):
    def test_missing_research_directory_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'RESEARCH_DIRECTORY_NOT_PRESENT'):
                check('/missing/artifact.json', 'deadbeef', str(Path(tmp) / 'missing'))

    def test_data_volume_rejected(self):
        with self.assertRaisesRegex(ValueError, 'RESEARCH_DIRECTORY_OVERLAPS_PRODUCTION_VOLUME'):
            check('/missing/artifact.json', 'deadbeef', '/data')

    def test_valid_artifact_reports_research_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = type('Prepared', (), {'model': type('Model', (), {'training_ids': ['one']})()})()
            with patch('hybrid_engine.prepared_preflight.PreparedBayes', return_value=fake) as loader:
                result = check('/isolated/model.json', 'pinned', tmp)
            loader.assert_called_once_with('/isolated/model.json', trusted_sha256='pinned')
            self.assertEqual(result['status'], 'RESEARCH_PREPARED_ARTIFACT_VALID')
            self.assertFalse(result['production_promotion'])
            self.assertFalse(result['calibrated'])
            self.assertEqual(result['training_games'], 1)


if __name__ == '__main__':
    unittest.main()
