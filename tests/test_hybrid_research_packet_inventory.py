"""Inventory the committed research capsule without extracting untrusted tar members."""
import hashlib
import tarfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / 'docs/evidence/nba-phase843-prospective-native-20261113.tar.gz'
EXPECTED_SHA = '9e95f0d849f530325ef881e389179796577a82c65c4aa3be798bbaa2bf3700b3'


class NativeResearchPacketInventory(unittest.TestCase):
    def test_packet_integrity_and_model_inventory(self):
        self.assertTrue(PACKET.is_file())
        h = hashlib.sha256()
        with PACKET.open('rb') as src:
            for block in iter(lambda: src.read(1024 * 1024), b''):
                h.update(block)
        self.assertEqual(h.hexdigest(), EXPECTED_SHA)
        with tarfile.open(PACKET, 'r:gz') as tar:
            members = tar.getmembers()
            self.assertLess(len(members), 10000)
            self.assertTrue(all(not m.issym() and not m.islnk() and not m.isdev() for m in members))
            models = [m.name for m in members if m.isfile() and
                      ('prepared' in m.name.lower() or 'model' in m.name.lower())]
            print('RESEARCH_PACKET_MODEL_INVENTORY=' + repr(models[:40]))
            self.assertTrue(members)


if __name__ == '__main__':
    unittest.main()
