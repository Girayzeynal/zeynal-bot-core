import unittest

from lineup_uncertainty import LineupStatus, assess_lineup


PLAYERS = ("A", "B", "C", "D", "E", "F")


class LineupUncertaintyTests(unittest.TestCase):
    def test_missing_starters_is_valid_unavailable_state(self):
        result = assess_lineup(eligible=PLAYERS, prediction_utc=100)
        self.assertEqual(result.status, LineupStatus.UNAVAILABLE)
        self.assertEqual(result.starters, ())

    def test_projected_five_is_not_official(self):
        result = assess_lineup(eligible=PLAYERS, starters=PLAYERS[:5],
                               prediction_utc=100)
        self.assertEqual(result.status, LineupStatus.PROJECTED)

    def test_official_requires_source_and_timestamp(self):
        with self.assertRaises(ValueError):
            assess_lineup(eligible=PLAYERS, starters=PLAYERS[:5],
                          official=True, prediction_utc=100)
        result = assess_lineup(eligible=PLAYERS, starters=PLAYERS[:5],
                               official=True, source="provider", observed_at_utc=90,
                               prediction_utc=100)
        self.assertEqual(result.status, LineupStatus.OFFICIAL)

    def test_future_observation_cannot_leak_into_prediction(self):
        with self.assertRaisesRegex(ValueError, "post-prediction"):
            assess_lineup(eligible=PLAYERS, starters=PLAYERS[:5],
                          official=True, source="provider",
                          observed_at_utc=101, prediction_utc=100)

    def test_excluded_or_uncertain_official_starter_rejected(self):
        with self.assertRaises(ValueError):
            assess_lineup(eligible=PLAYERS, excluded=("A",),
                          starters=PLAYERS[:5])
        with self.assertRaises(ValueError):
            assess_lineup(eligible=PLAYERS, uncertain=("A",),
                          starters=PLAYERS[:5], official=True,
                          source="provider", observed_at_utc=90, prediction_utc=100)

    def test_malformed_and_duplicate_rosters_rejected(self):
        for roster in ("A", ("A", "A"), ("A", ""), None):
            with self.subTest(roster=roster), self.assertRaises(ValueError):
                assess_lineup(eligible=roster)
        with self.assertRaises(ValueError):
            assess_lineup(eligible=PLAYERS, starters=PLAYERS[:4])


if __name__ == "__main__":
    unittest.main()
