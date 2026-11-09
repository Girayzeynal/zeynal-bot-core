"""Regression tests for strict EuroLeague/EuroCup official-feed parsing."""
import unittest
from tools.archive_europe_official_2026_27 import parse_completed

def game(**changes):
    value = {
        "played": True,
        "gameCode": 123,
        "utcDate": "2026-11-05T18:00:00Z",
        "local": {"code": "AAA", "score": 88},
        "road": {"code": "BBB", "score": 79},
    }
    value.update(changes)
    return value

class OfficialFeedParsingTests(unittest.TestCase):
    def test_completed_game_has_real_scores_and_utc_time(self):
        result = parse_completed(game())
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "123")
        self.assertEqual(result[2:], ("AAA", "BBB", 88, 79))

    def test_unfinished_game_is_not_archived(self):
        self.assertIsNone(parse_completed(game(played=False, gameStatus="live")))

    def test_missing_scores_are_not_fabricated(self):
        self.assertIsNone(parse_completed(game(local={"code": "AAA"})))

    def test_boolean_score_is_not_accepted_as_integer(self):
        self.assertIsNone(parse_completed(game(local={"code": "AAA", "score": True})))

    def test_missing_timezone_is_rejected(self):
        self.assertIsNone(parse_completed(game(utcDate="2026-11-05T18:00:00")))

    def test_same_team_is_rejected(self):
        self.assertIsNone(parse_completed(game(road={"code": "AAA", "score": 79})))

    def test_tied_final_score_is_rejected(self):
        self.assertIsNone(parse_completed(game(road={"code": "BBB", "score": 88})))

if __name__ == "__main__":
    unittest.main()
