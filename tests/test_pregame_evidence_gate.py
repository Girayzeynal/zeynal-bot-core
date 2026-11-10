"""Tests for the deterministic pregame evidence gate."""
import unittest
from pregame_evidence_gate import assess_pregame_evidence


class PregameEvidenceGateTests(unittest.TestCase):
    def setUp(self):
        self.kw = dict(fixture_verified=True, tipoff_verified=True,
            prediction_utc=100000, tipoff_utc=104000, data_observed_utc=99900,
            sample_home=10, sample_away=12, lineup_confirmed=True,
            market_observed_utc=99900)

    def check(self, **changes):
        return assess_pregame_evidence(**(self.kw | changes))

    def test_complete_evidence_is_not_a_win_probability(self):
        result = self.check()
        self.assertEqual((result.status, result.score, result.reasons),
                         ("EVIDENCE_COMPLETE", 100, ()))

    def test_unverified_fixture_blocks(self):
        self.assertEqual(self.check(fixture_verified=False).status, "BLOCKED")

    def test_started_game_blocks(self):
        self.assertIn("UNVERIFIED_FUTURE_TIPOFF",
                      self.check(tipoff_utc=100000).reasons)

    def test_stale_data_flags_caution(self):
        self.assertIn("STALE_OR_MISSING_TEAM_DATA",
                      self.check(data_observed_utc=1).reasons)

    def test_future_market_timestamp_flags_caution(self):
        self.assertIn("STALE_OR_MISSING_MARKET",
                      self.check(market_observed_utc=100001).reasons)

    def test_thin_sample_flags_caution(self):
        self.assertIn("INSUFFICIENT_SAMPLE",
                      self.check(sample_away=9).reasons)

    def test_unconfirmed_lineup_flags_caution(self):
        self.assertIn("UNCONFIRMED_LINEUP",
                      self.check(lineup_confirmed=False).reasons)

    def test_invalid_threshold_fails(self):
        with self.assertRaises(ValueError):
            self.check(max_data_age_seconds=-1)


if __name__ == "__main__":
    unittest.main()
