"""Validate prepared Bayesian artifacts inside the pinned historical evidence packet.

This is a read-only compatibility check: no extraction, no model promotion,
no Telegram calls, and no writes to the production volume.
"""
import hashlib
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from hybrid_engine.live_nba import PreparedBayes

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / 'docs/evidence/nba-phase843-prospective-native-20261113.tar.gz'
EXPECTED_PACKET_SHA = '9e95f0d849f530325ef881e389179796577a82c65c4aa3be798bbaa2bf3700b3'
CANDIDATES = (
    'prepared-final/nba-prepared-8029ba30c8c80d332dca7daa39e558a13440e454ec26b096717baa0341870259.json',
    'prepared-optimized/nba-prepared-ae4e578f441770883247e648314c1a7a29c86caa76ab4aa6af006fda4b10254e.json',
)


class PreparedArchiveCompatibilityTests(unittest.TestCase):
    def test_archived_prepared_models_load_under_current_code(self):
        self.assertEqual(hashlib.sha256(PACKET.read_bytes()).hexdigest(), EXPECTED_PACKET_SHA)
        with tarfile.open(PACKET, 'r:gz') as archive, tempfile.TemporaryDirectory() as temp:
            for name in CANDIDATES:
                member = archive.getmember(name)
                self.assertTrue(member.isfile())
                self.assertLess(member.size, 4 * 1024 * 1024)
                stream = archive.extractfile(member)
                self.assertIsNotNone(stream)
                raw = stream.read(4 * 1024 * 1024 + 1)
                self.assertEqual(len(raw), member.size)
                document = json.loads(raw)
                pinned = document['sha256']
                self.assertEqual(len(pinned), 64)
                # A historical digest from the same file is not an independently
                # trusted deployment pin. This checks internal compatibility only.
                path = Path(temp) / Path(name).name
                path.write_bytes(raw)
                model = PreparedBayes(str(path), trusted_sha256=pinned)
                self.assertGreaterEqual(len(model.model.training_ids), 30)
                print('ARCHIVED_MODEL_COMPATIBILITY=' + json.dumps({
                    'archive_member': name,
                    'artifact_sha256': pinned,
                    'training_games': len(model.model.training_ids),
                    'status': 'LOAD_OK_NOT_DEPLOYMENT_AUTHORIZATION',
                }, sort_keys=True))


if __name__ == '__main__':
    unittest.main()
