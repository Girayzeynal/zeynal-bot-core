"""Multi-provider provenance and conflict regression cases."""
import unittest
from multi_source_evidence import Observation, reconcile


class MultiSourceEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.base = dict(fixture_id="401999001", field="home_score",
                         prediction_utc=10000, max_age_seconds=600)
        self.a = Observation("ESPN", "espn", "401999001", "home_score", 110,
                             9900, "https://example.com/a")
        self.b = Observation("NBA", "nba-official", "401999001", "home_score", 110,
                             9900, "https://example.com/b")

    def run_gate(self, items, **kwargs):
        return reconcile(items, **(self.base | kwargs))

    def test_independent_agreement(self):
        self.assertEqual(self.run_gate([self.a, self.b]).status, "VERIFIED_CONSENSUS")

    def test_same_upstream_is_not_independent(self):
        copy = Observation("ESPN-mirror", "espn", "401999001", "home_score", 110,
                           9900, "https://example.com/mirror")
        self.assertEqual(self.run_gate([self.a, copy]).status, "INSUFFICIENT_EVIDENCE")

    def test_conflict_does_not_average(self):
        different = Observation("NBA", "nba-official", "401999001", "home_score", 112,
                                9900, "https://example.com/b")
        result = self.run_gate([self.a, different])
        self.assertEqual((result.status, result.value), ("CONFLICT", None))

    def test_future_data_is_excluded(self):
        future = Observation("NBA", "nba-official", "401999001", "home_score", 110,
                             10001, "https://example.com/b")
        self.assertEqual(self.run_gate([self.a, future]).status, "INSUFFICIENT_EVIDENCE")

    def test_stale_data_is_excluded(self):
        self.assertEqual(self.run_gate([self.a, self.b], max_age_seconds=10).status,
                         "INSUFFICIENT_EVIDENCE")

    def test_fixture_mismatch_is_excluded(self):
        other = Observation("NBA", "nba-official", "other", "home_score", 110,
                            9900, "https://example.com/b")
        self.assertEqual(self.run_gate([self.a, other]).status, "INSUFFICIENT_EVIDENCE")

    def test_invalid_number_is_excluded(self):
        nan = Observation("NBA", "nba-official", "401999001", "home_score",
                          float("nan"), 9900, "https://example.com/b")
        self.assertEqual(self.run_gate([self.a, nan]).status, "INSUFFICIENT_EVIDENCE")

    def test_same_source_conflict_is_detected(self):
        changed = Observation("ESPN-cache", "espn", "401999001", "home_score", 111,
                              9900, "https://example.com/cache")
        self.assertEqual(self.run_gate([self.a, changed, self.b]).status, "CONFLICT")


if __name__ == "__main__":
    unittest.main()
