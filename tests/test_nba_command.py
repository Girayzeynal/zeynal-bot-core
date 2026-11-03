import unittest
from datetime import datetime, timezone

from nba_command import parse_nba_date, select_local_games


class NbaCommandTests(unittest.TestCase):
    def test_default_date_uses_turkey_time(self):
        now = datetime(2026, 11, 3, 22, 30, tzinfo=timezone.utc)
        self.assertEqual(parse_nba_date([], now), "2026-11-04")

    def test_invalid_date_rejected(self):
        with self.assertRaises(ValueError):
            parse_nba_date(["2026-02-30"], datetime.now(timezone.utc))

    def test_local_day_boundary_and_deduplication(self):
        game = {
            "id": 101, "date": "2026-11-03T22:30:00+00:00",
            "teams": {"home": {"name": "Home"}, "away": {"name": "Away"}},
            "status": {"short": "NS"},
        }
        self.assertEqual(len(select_local_games([game, game], "2026-11-04")), 1)
        self.assertEqual(len(select_local_games([game], "2026-11-03")), 0)

    def test_malformed_game_skipped(self):
        self.assertEqual(select_local_games([{"id": 1}], "2026-11-04"), [])

    def test_invalid_game_identifiers_skipped(self):
        template = {
            "date": "2026-11-03T22:30:00Z",
            "teams": {"home": {"name": "Home"}, "away": {"name": "Away"}},
            "status": {"short": "NS"},
        }
        rows = [{**template, "id": value} for value in (None, "", True, [], {})]
        self.assertEqual(select_local_games(rows, "2026-11-04"), [])

    def test_invalid_rows_skipped(self):
        self.assertEqual(select_local_games([None, [], "invalid"], "2026-11-04"), [])


if __name__ == "__main__":
    unittest.main()
