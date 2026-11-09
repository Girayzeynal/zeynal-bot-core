"""Offline contract tests: NBA official evidence is never fabricated."""
import unittest
from tools.archive_nba_official_crosscheck import parse_final


def game(**updates):
    record = {
        "gameStatus": 3,
        "gameId": "0022600123",
        "homeTeam": {"teamId": 1610612738, "score": 108},
        "awayTeam": {"teamId": 1610612749, "score": 103},
    }
    record.update(updates)
    return record


class OfficialNBAScoreboardTests(unittest.TestCase):
    def test_completed_game(self):
        self.assertEqual(
            parse_final(game()),
            ("0022600123", "1610612738", "1610612749", 108, 103),
        )

    def test_live_game_rejected(self):
        self.assertIsNone(parse_final(game(gameStatus=2)))

    def test_missing_scores_rejected(self):
        self.assertIsNone(parse_final(game(homeTeam={"teamId": 1610612738})))

    def test_boolean_score_rejected(self):
        self.assertIsNone(parse_final(game(homeTeam={"teamId": 1610612738, "score": True})))

    def test_tied_final_rejected(self):
        self.assertIsNone(parse_final(game(awayTeam={"teamId": 1610612749, "score": 108})))

    def test_missing_team_identity_rejected(self):
        self.assertIsNone(parse_final(game(homeTeam={"score": 108})))

    def test_identical_teams_rejected(self):
        self.assertIsNone(parse_final(game(awayTeam={"teamId": 1610612738, "score": 103})))

    def test_invalid_fixture_id_rejected(self):
        self.assertIsNone(parse_final(game(gameId="invalid")))


if __name__ == "__main__":
    unittest.main()
