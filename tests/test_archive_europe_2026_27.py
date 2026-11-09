import sqlite3
import unittest
from tools.archive_europe_2026_27 import SCHEMA, parse_game, persist

def event(season="2026-2027", league=120, status="FT"):
    return {"id": 12345, "date": "2026-11-05T19:00:00+00:00",
            "league": {"id": league, "season": season},
            "status": {"short": status},
            "teams": {"home": {"id": 10}, "away": {"id": 11}},
            "scores": {"home": {"total": 88}, "away": {"total": 81}}}

class EuropeanArchiveTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(SCHEMA)
        self.addCleanup(self.db.close)

    def test_accepts_real_completed_season_shape(self):
        row = parse_game(event(), 120)
        self.assertIsNotNone(row)
        self.assertEqual(row[4:6], (88, 81))

    def test_wrong_season_or_league_or_unfinished_rejected(self):
        self.assertIsNone(parse_game(event(season="2025-2026"), 120))
        self.assertIsNone(parse_game(event(league=194), 120))
        self.assertIsNone(parse_game(event(status="Q4"), 120))

    def test_idempotent_persist(self):
        row = parse_game(event(), 120)
        persist(self.db, "EuroLeague", "2026-11-05", [row], 123)
        persist(self.db, "EuroLeague", "2026-11-05", [row], 124)
        self.assertEqual(self.db.execute("select count(*) from games").fetchone()[0], 1)

    def test_conflicting_result_rolls_back(self):
        row = parse_game(event(), 120)
        persist(self.db, "EuroLeague", "2026-11-05", [row], 123)
        changed = (*row[:4], 90, *row[5:])
        with self.assertRaises(ValueError):
            persist(self.db, "EuroLeague", "2026-11-05", [changed], 124)
        self.assertEqual(self.db.execute("select home_score from games").fetchone()[0], 88)

if __name__ == "__main__":
    unittest.main()
