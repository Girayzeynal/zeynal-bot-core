import unittest

from providers.espn_quality_audit import audit_espn_events


def event(event_id, score="115", completed=True):
    return {
        "id": event_id,
        "date": "2025-10-25T23:00:00Z",
        "competitions": [{
            "status": {"type": {
                "state": "completed" if completed else "in",
                "completed": completed,
            }},
            "competitors": [
                {"homeAway": "home", "team": {"id": "1"}, "score": score},
                {"homeAway": "away", "team": {"id": "2"}, "score": "108"},
            ],
        }],
    }


class ESPNQualityAuditTests(unittest.TestCase):
    def test_reports_identical_conflicting_and_invalid_events(self):
        result = audit_espn_events([
            event("a"), event("a"),
            event("b"), event("b", score="116"),
            event("c"), event("d", completed=False),
        ], observed_at_utc=1761500000)
        self.assertEqual(result["total_raw"], 6)
        self.assertEqual(result["accepted_unique"], 2)
        self.assertEqual(result["duplicate_identical"], 1)
        self.assertEqual(result["conflicting_fixture_ids"], 1)
        self.assertEqual(result["conflicting_records"], 2)
        self.assertEqual(result["conflicting_fixture_ids_detail"], ["b"])
        self.assertEqual(result["invalid_event_indices"], [5])
        self.assertEqual(result["invalid_or_incomplete"], 1)
        self.assertEqual(result["unfinished_events"], 1)
        self.assertEqual(result["malformed_or_unverifiable_events"], 0)
        self.assertAlmostEqual(result["coverage_rate"], 2 / 6)

    def test_malformed_and_unfinished_are_distinct(self):
        result = audit_espn_events([
            event("a", completed=False),
            {"id": "broken"},
            event("b", score="not-a-score"),
        ], observed_at_utc=1761500000)
        self.assertEqual(result["invalid_or_incomplete"], 3)
        self.assertEqual(result["unfinished_events"], 1)
        self.assertEqual(result["malformed_or_unverifiable_events"], 2)
        self.assertEqual(
            result["unfinished_events"] + result["malformed_or_unverifiable_events"],
            result["invalid_or_incomplete"],
        )

    def test_empty_and_invalid_inputs(self):
        result = audit_espn_events([], observed_at_utc=1761500000)
        self.assertEqual(result["total_raw"], 0)
        self.assertIsNone(result["coverage_rate"])
        self.assertEqual(result["conflicting_fixture_ids_detail"], [])
        self.assertEqual(result["invalid_event_indices"], [])
        with self.assertRaises(ValueError):
            audit_espn_events({}, observed_at_utc=1761500000)
        with self.assertRaises(ValueError):
            audit_espn_events([], observed_at_utc=0)


if __name__ == "__main__":
    unittest.main()
