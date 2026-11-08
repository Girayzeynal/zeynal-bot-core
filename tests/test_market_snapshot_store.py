import os
import tempfile
import unittest
from market_snapshot_store import MarketSnapshotStore
from sharp_guard import MarketSnapshot, audit_market


class SnapshotStoreTests(unittest.TestCase):
    def test_immutable_history_and_movement(self):
        with tempfile.TemporaryDirectory() as folder:
            store = MarketSnapshotStore(os.path.join(folder, 'market.sqlite'))
            opening = MarketSnapshot('book', 'TOTAL', 225.5, 1.91, 1.91, 100, 'provider')
            current = MarketSnapshot('book', 'TOTAL', 221.5, 1.90, 1.92, 200, 'provider')
            self.assertTrue(store.append('fixture', opening))
            self.assertFalse(store.append('fixture', opening))
            self.assertTrue(store.append('fixture', current))
            history = store.history('fixture', 'book', 'TOTAL', 'provider')
            self.assertEqual([x.line for x in history], [225.5, 221.5])
            self.assertEqual(audit_market(history, now_utc=210).movement, -4)
            with self.assertRaises(ValueError):
                store.append('fixture', MarketSnapshot('book', 'TOTAL', 226.5, 1.91, 1.91, 100, 'provider'))
            self.assertEqual(store.history('other', 'book', 'TOTAL', 'provider'), [])


if __name__ == '__main__':
    unittest.main()
