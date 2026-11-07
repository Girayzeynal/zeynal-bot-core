import sqlite3
import unittest

from tools.archive_nba_2026_27 import SCHEMA, persist_day


class ArchiveBackfillTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(SCHEMA)
        self.addCleanup(self.db.close)
        self.game = {
            "provider": "ESPN", "provider_fixture_id": "401000001",
            "start_ts_utc": 1793600000, "home_team_id": "2",
            "away_team_id": "3", "actual_home": 105, "actual_away": 99,
            "scope": "FINAL_WITH_OT",
        }

    def test_idempotent_archive_and_day_receipt(self):
        persist_day(self.db, "2026-11-02", [self.game], 1793700000)
        persist_day(self.db, "2026-11-02", [self.game], 1793700010)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM games").fetchone()[0], 1)
        self.assertEqual(self.db.execute("SELECT completed_count FROM scan_days").fetchone()[0], 1)

    def test_conflicting_final_rejected_without_overwrite(self):
        persist_day(self.db, "2026-11-02", [self.game], 1793700000)
        changed = dict(self.game, actual_home=106)
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            persist_day(self.db, "2026-11-02", [changed], 1793700010)
        self.assertEqual(self.db.execute("SELECT home_score FROM games").fetchone()[0], 105)

    def test_duplicate_day_fails_without_partial_insert(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            persist_day(self.db, "2026-11-02", [self.game, self.game], 1793700000)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM games").fetchone()[0], 0)

    def test_invalid_response_does_not_mark_day_scanned(self):
        with self.assertRaises(ValueError):
            persist_day(self.db, "2026-11-02", None, 1793700000)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM scan_days").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
